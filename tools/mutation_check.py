"""Mutation check: break a critical line **in a throwaway copy**, confirm the suite notices.

A passing suite proves nothing if the tests cannot fail. This applies one-line
mutations to load-bearing logic, one at a time, and requires the suite to fail for
each one.

Safety model (this is the point of the rewrite):

* **The development tree is never mutated.** `src/backend` is copied, together with
  the root `pytest.ini`, into a fresh temporary directory; every byte that is
  written goes there. A kill at any moment therefore cannot leave a mutation in the
  working tree — the isolation is structural, not best-effort.
* **A baseline runs first.** The copy must be green before any mutation is applied,
  so an already-failing tree can never be reported as "all mutations killed".
* **Restores are verified.** Each mutation is reverted from an in-memory snapshot
  and the file is re-hashed; a failed restore aborts the run.
* **The original tree is fingerprinted** before and after, and the run fails if any
  tracked file changed.

Signal handling note: `SIGINT`/`SIGTERM` handlers are installed where the platform
supports them, but this does **not** make recovery signal-proof — on Windows
`os.kill(pid, SIGTERM)` terminates the process outright, and no handler runs. That
is acceptable here *because the mutations never touch the real tree*: an abrupt
death costs a stale temporary directory, never a corrupted checkout. The
temporary directory is removed on every normal and exception path.

Usage:  <venv python> tools/mutation_check.py [--keep-temp] [-k SUBSTRING]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "src" / "backend"
TEMP_PREFIX = "genledge-mutation-"
BASELINE_TIMEOUT_SECONDS = 900
#: The fingerprint exists to prove the real tree was untouched. Hashing 300 frontend
#: sources for every run would be slow and pointless; these are the paths a mutation
#: could plausibly damage, and they are the ones this tool copies.
FINGERPRINT_PREFIXES = (
    "src/backend/",
    "pytest.ini",
    "tools/mutation_check.py",
    "verify_us4_person_b.py",
)


#: The one in-repo location the battery may use, and only when nothing else is writable.
#: A workspace-scoped sandbox can deny every system temp directory; refusing to run at
#: all would leave the battery unusable exactly where it is most needed. The path is
#: explicit and gitignored, and `preflight` accepts it only because it is this constant —
#: `build_copy` still writes solely under `<scratch>/genledge-mutation-*`.
SCRATCH_DIR = ROOT / ".mutation-scratch"

#: Candidate parents, best first. `None` means "wherever `tempfile` would go".
#:
#: System temp leads, because it is outside the repository by construction. The
#: in-workspace directory is the last resort for an environment whose only writable area
#: is the workspace — note that a confined sandbox may still refuse a *new nested* tree
#: there, in which case the run reports that it cannot create a workspace rather than
#: mutating anything in place.
TEMP_PARENTS: tuple[Path | None, ...] = (
    (Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp") if os.environ.get("USERPROFILE") else None,
    Path(r"C:\Windows\Temp") if os.name == "nt" else Path("/tmp"),
    None,
    SCRATCH_DIR,
)


def _temp_parent_candidates() -> list[Path | None]:
    """Places a throwaway copy may live, best first.

    The environment's `TEMP` is not trusted on its own: a confined shell may point it at
    a sandbox-private directory that cannot hold a copied tree, so the profile's real
    temp directory and the system one are tried as well.
    """

    seen: list[Path | None] = []
    for candidate in TEMP_PARENTS:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _writable(parent: Path) -> bool:
    """Probe a candidate with an operation that fails fast when it is denied.

    `tempfile.mkdtemp(dir=...)` can **block** rather than raise in a confined sandbox — a
    whole battery run stalled at zero CPU inside it — so the candidate is probed with
    `os.mkdir` first, which either succeeds or raises immediately. A timeout is treated as
    usable: refusing every candidate on a slow filesystem would be worse than trying one
    that then raises inside the guard.
    """

    probe = parent / f".genledge-probe-{os.getpid()}"
    try:
        os.mkdir(probe)
    except FileExistsError:
        pass
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - a sandbox can raise something exotic
        return False
    try:
        os.rmdir(probe)
    except OSError:
        pass
    return True


def make_workspace() -> Path | None:
    """Create the throwaway copy's parent, or `None` when nowhere is writable.

    Each candidate is probed independently and a failure moves to the next. The caller
    treats `None` as "cannot run here" and reports it, rather than raising a traceback
    from the middle of a copy.
    """

    for parent in _temp_parent_candidates():
        try:
            if parent is None:
                # `None` means "wherever `tempfile` would go", which is not known until it
                # is asked. Probing that directory first matters: it is ordered ahead of
                # the in-workspace last resort, so an unprobed `mkdtemp` here can hang (or
                # succeed uselessly) and the fallback is never reached.
                default = Path(tempfile.gettempdir())
                if not _writable(default):
                    continue
                return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
            parent.mkdir(parents=True, exist_ok=True)
            if not _writable(parent):
                continue
            return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=str(parent)))
        except OSError:
            continue
        except Exception:  # noqa: BLE001 - a confined shell can fail in unusual ways
            continue
    return None

#: Mutations the suite is expected to notice. `(label, relative path, original, mutated)`.
MUTATIONS: list[tuple[str, str, str, str]] = [
    # --- tool dispatch ---------------------------------------------------------
    (
        "tool budget is not checked before dispatch",
        "app/agent/nodes.py",
        'if state.get("tool_calls_used", 0) >= budgets.max_tool_calls:',
        'if False and state.get("tool_calls_used", 0) >= budgets.max_tool_calls:',
    ),
    (
        "recorded tool results are not replayed",
        "app/agent/tools.py",
        "        recorded = self.repository.get_tool_result(job_id, request.id)",
        "        recorded = None  # MUTATED: replay disabled",
    ),
    (
        "a replay is not checked against the recorded tool name",
        "app/agent/tools.py",
        '            if recorded.tool != request.name or recorded.arguments != arguments.model_dump():',
        '            if False:  # MUTATED: replay identity unchecked',
    ),
    (
        "the batch already-seen guard is dropped",
        "app/agent/tools.py",
        "        if request.id in seen_call_ids:",
        "        if False:  # MUTATED: duplicate ids accepted",
    ),
    (
        "a failing tool call is not charged against the budget",
        "app/agent/tools.py",
        "        return ToolOutcome(result=result, replayed=False, charged=charge)",
        "        return ToolOutcome(result=result, replayed=False, charged=False)  # MUTATED",
    ),
    (
        "the field-path scope control is removed",
        "app/agent/tools.py",
        '        unknown = [path for path in requested if path not in allowed]',
        '        unknown = []  # MUTATED: field paths unvalidated',
    ),
    (
        "the per-resource field-path scope control is removed",
        "app/agent/tools.py",
        '        allowed = set().union(*(self.field_paths_for(item) for item in declared)) if declared else self.allowed_field_paths()',
        '        allowed = self.allowed_field_paths()  # MUTATED: cross-resource field read allowed',
    ),
    (
        "a tool-result write failure is treated as success",
        "app/agent/tools.py",
        "            self.repository.record_tool_result(result)",
        "            pass  # MUTATED: a failed write looks like a successful call",
    ),
    (
        "pre-dispatch refusals are persisted again",
        "app/agent/tools.py",
        "                persist=False,\n            )\n\n        payload = arguments.model_dump()",
        "                persist=True,  # MUTATED\n            )\n\n        payload = arguments.model_dump()",
    ),
    # --- redaction -------------------------------------------------------------
    (
        "credential detection is disabled entirely",
        "app/agent/tools.py",
        '        _CREDENTIAL.search(haystack)',
        '        False and _CREDENTIAL.search(haystack)  # MUTATED',
    ),
    (
        "e-mail detection is disabled",
        "app/agent/tools.py",
        '        or _EMAIL.search(haystack)',
        '        or False  # MUTATED',
    ),
    (
        "contact and identifier detection is disabled",
        "app/agent/tools.py",
        '        or _IDENTIFIER.search(haystack)',
        '        or False  # MUTATED',
    ),
    (
        "the sensitive-field-name rule is disabled",
        "app/agent/tools.py",
        '    return bool(_SENSITIVE_FIELD.search(name) or _SECRET_SHAPED.search(name))',
        '    return bool(False and _SENSITIVE_FIELD.search(name))  # MUTATED',
    ),
    (
        "non-string scalars are never content-checked",
        "app/agent/tools.py",
        '        return REDACTION_MARKER if _restricted_text(str(value)) else value',
        '        return value  # MUTATED: a numeric credential is never examined',
    ),
    # --- projection / prompt boundary ------------------------------------------
    (
        "the three-sample cap is removed",
        "app/agent/prompts.py",
        '            for value in field.samples[:3]',
        '            for value in field.samples  # MUTATED: the sample cap is gone',
    ),
    (
        "the text cap is a no-op",
        "app/agent/prompts.py",
        "def _bounded_text(text: str) -> str:\n    if len(text) <= MAX_PROJECTED_TEXT:\n        return text",
        "def _bounded_text(text: str) -> str:\n    if True:  # MUTATED\n        return text",
    ),
    (
        "snapshot_id is rendered without the projection chokepoint",
        "app/agent/prompts.py",
        "    lines = [f\"snapshot_id: {projected(inventory.snapshot_id, 'snapshot_id')}\"]",
        "    lines = [f\"snapshot_id: {inventory.snapshot_id}\"]  # MUTATED: B1 vector",
    ),
    (
        "resource_id is rendered without the projection chokepoint",
        "app/agent/prompts.py",
        "            f\"  - {projected(resource.resource_id, 'resource_id')} \"",
        "            f\"  - {resource.resource_id} \"  # MUTATED: B1 vector",
    ),
    (
        "the tool name and call id are rendered raw",
        "app/agent/prompts.py",
        "        tool = projected(result.tool, \"tool\")",
        "        tool = result.tool  # MUTATED: B1 vector",
    ),
    (
        "the tool call id is not neutralised",
        "app/agent/prompts.py",
        "        call_id = projected(result.tool_call_id, \"tool_call_id\")",
        "        call_id = result.tool_call_id  # MUTATED",
    ),
    (
        "the tool error code is not neutralised",
        "app/agent/prompts.py",
        "            \"error_code\": projected(result.error_code, \"error_code\"),",
        "            \"error_code\": result.error_code,  # MUTATED",
    ),
    (
        "the field path is not neutralised",
        "app/agent/prompts.py",
        "        path = _bounded_text(projected(_field_path(field.ref.resource_id, field.ref.field_path), \"field_path\"))",
        "        path = _bounded_text(_field_path(field.ref.resource_id, field.ref.field_path))  # MUTATED",
    ),
    (
        "the previous response is quoted without neutralisation",
        "app/agent/prompts.py",
        "\"previous_response\": _bounded_text(str(projected(previous_response, \"previous_response\"))),",
        "\"previous_response\": _bounded_text(previous_response),  # MUTATED: B1 vector",
    ),
    # --- model accounting ------------------------------------------------------
    (
        "the model-call budget ignores the durable count",
        "app/agent/nodes.py",
        "    return max(durable, state.get(\"model_calls_used\", 0)) if durable else state.get(\"model_calls_used\", 0)",
        "    return state.get(\"model_calls_used\", 0)  # MUTATED: durable count ignored",
    ),
    (
        "the model call is not recorded durably",
        "app/agent/nodes.py",
        '    try:\n        runtime.repository.record_model_call(\n            state.get("job_id", ""), node=PROPOSE, tokens=response.tokens if response else 0\n        )',
        '    try:\n        pass  # MUTATED: the durable call count never advances',
    ),
    (
        "the raise path does not record the attempted call",
        "app/agent/nodes.py",
        '        _record_model_call(runtime, state, None)\n        update = _failure_update(failure, state)',
        '        update = _failure_update(failure, state)  # MUTATED: the raised call is unrecorded',
    ),
    (
        "the tool-call round is not charged",
        "app/agent/nodes.py",
        '            if outcome.charged:\n                used += 1',
        '            if outcome.charged and False:  # MUTATED: rounds are free\n                used += 1',
    ),
    # --- runtime / modes -------------------------------------------------------
    (
        "the recursion derivation is replaced by the floor",
        "app/agent/graph.py",
        "    worst_case = 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls + 12\n    return max(budgets.recursion_limit, int(worst_case * 1.4))",
        "    return budgets.recursion_limit  # MUTATED: derivation removed",
    ),
    (
        "an invalid state update is not mapped to a typed failure",
        "app/agent/graph.py",
        '    except InvalidStateUpdateError as error:',
        '    except InvalidStateUpdateError as error:  # MUTATED\n        raise',
    ),
    (
        "a table is emitted with no attributes",
        "app/agent/models.py",
        "    tables: list[Table] = []\n    if attributes:",
        "    tables: list[Table] = []\n    if True:  # MUTATED: emits the orders table unconditionally",
    ),
    (
        "auto mode treats a provider name as configuration",
        "app/agent/models.py",
        "    return any(str(source.get(name, \"\")).strip() for name in PROVIDER_CREDENTIAL_ENV_VARS)",
        "    return any(str(source.get(name, \"\")).strip() for name in PROVIDER_ENV_VARS)  # MUTATED",
    ),
]


def tree_fingerprint() -> dict[str, str]:
    """sha256 of the paths a mutation could plausibly damage.

    Scoped by `FINGERPRINT_PREFIXES` so the check is fast enough to run twice per
    invocation; the copy only ever contains these paths, so nothing else can be touched.
    """

    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", *FINGERPRINT_PREFIXES],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in listing
        if (ROOT / name).is_file()
    }


def build_copy(destination: Path) -> None:
    """Copy the *current* implementation — including uncommitted work — plus pytest.ini.

    The destination directories are created with `Path.mkdir` before any copying.
    `shutil.copytree` makes its own destination with `os.makedirs`, which a confined
    Windows sandbox can refuse even where an equivalent `mkdir` succeeds — the copy then
    fails with `WinError 5` before a single file is written.
    """

    backend = destination / "src" / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        BACKEND,
        backend,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.bak"),
    )
    shutil.copy2(ROOT / "pytest.ini", destination / "pytest.ini")


def run_suite(cwd: Path) -> tuple[bool | None, str]:
    """Run the agent suite in the copy. Returns `(green, summary)`.

    `green` is `None` when the run could not be judged — a non-zero exit with no named
    test failure, which is a collection, import or usage error rather than evidence about
    the mutation. Counting that as a kill would inflate the battery.
    """

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--tb=no", "-q", "-rf", "tests/agent"],
        cwd=cwd / "src" / "backend",
        capture_output=True,
        text=True,
        timeout=BASELINE_TIMEOUT_SECONDS,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    # pytest reports usage and collection problems as `ERROR: ...`, which is not a test
    # noticing the mutation. A kill has to be a *named test* failure.
    usage_error = [line for line in combined.splitlines() if line.startswith("ERROR:")]
    failing = [
        line
        for line in combined.splitlines()
        if line.startswith("FAILED") or (line.startswith("ERROR ") and "::" in line)
    ]
    if usage_error:
        return None, f"pytest could not run the suite: {usage_error[0][:110]}"
    if failing:
        return False, f"{len(failing)} failing: {failing[0][:110]}"
    if proc.returncode != 0:
        # A non-zero exit with no named test failure is a collection or import error,
        # not evidence about the mutation.
        tail = combined.strip().splitlines()[-1][:110] if combined.strip() else "no output"
        return None, f"collection/import error: {tail}"
    return True, "green"


def preflight(destination: Path) -> tuple[bool, str]:
    """Refuse to start unless the copy is a suitable destructive-test target."""

    backend = destination / "src" / "backend"
    if not backend.is_dir():
        return False, f"the copy has no backend at {backend}"
    if (destination / "pytest.ini").is_file() is False:
        return False, "the copy has no pytest.ini; a root-level run could collect the real tree"
    resolved = backend.resolve()
    inside_repo = ROOT.resolve() in resolved.parents or resolved == ROOT.resolve()
    in_scratch = SCRATCH_DIR.resolve() in resolved.parents
    if inside_repo and not in_scratch:
        # The last-resort scratch directory is the single exception, and it is accepted
        # by identity rather than by path shape: anything else inside the repository is
        # refused, because a mutation there is the defect this tool exists to prevent.
        return False, f"refusing to mutate inside the repository: {resolved}"
    if not (resolved / "app" / "agent" / "nodes.py").is_file():
        return False, "the copy does not look like the backend (app/agent/nodes.py missing)"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-temp", action="store_true", help="do not delete the copy")
    parser.add_argument("-k", "--only", default="", help="run only labels containing this text")
    args = parser.parse_args()

    before = tree_fingerprint()

    temp_root = make_workspace()
    if temp_root is None:
        print("REFUSED: no writable location for a throwaway copy.")
        print("         The battery must never mutate the development tree, so it does")
        print("         not run at all rather than running in place.")
        return 2
    interrupted = False

    def _note_signal(signum, _frame):  # pragma: no cover - depends on the OS
        nonlocal interrupted
        interrupted = True
        raise KeyboardInterrupt(f"signal {signum}")

    installed = []
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _note_signal)
            installed.append(name)
        except (ValueError, OSError):  # pragma: no cover - not the main thread / unsupported
            pass

    try:
        try:
            build_copy(temp_root)
        except OSError as error:
            print(f"REFUSED: the throwaway copy could not be created under {temp_root}")
            print(f"         {type(error).__name__}: {error}")
            print("         The battery never mutates the development tree, so it does not")
            print("         run at all rather than running in place.")
            return 2
        ok, reason = preflight(temp_root)
        print(f"copy       : {temp_root}")
        print(f"preflight  : {'ok' if ok else 'REFUSED'} — {reason}")
        print(f"signals    : {', '.join(installed) if installed else 'none installable on this platform'}")
        if not ok:
            return 2

        print("baseline   : running the unmutated copy ...")
        green, summary = run_suite(temp_root)
        print(f"baseline   : {'GREEN' if green else 'RED'} — {summary}")
        if not green:
            print()
            print("ABORT: the copy is not green before any mutation. A mutation run on a")
            print("       failing tree reports every mutation as killed for the wrong reason.")
            return 2

        selected = [m for m in MUTATIONS if args.only.lower() in m[0].lower()]
        print(f"mutations  : {len(selected)} of {len(MUTATIONS)}")
        print()

        survivors: list[str] = []
        anchor_missing: list[str] = []
        #: Mutations whose run failed to collect: neither killed nor survived.
        unproven: list[str] = []
        for index, (label, relative, original, mutated) in enumerate(selected, start=1):
            path = temp_root / "src" / "backend" / relative
            snapshot = path.read_text(encoding="utf-8")
            snapshot_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
            if original not in snapshot:
                print(f"[ANCHOR-MISSING] {label}")
                anchor_missing.append(label)
                continue
            try:
                path.write_text(snapshot.replace(original, mutated, 1), encoding="utf-8")
                passed, summary = run_suite(temp_root)
            finally:
                path.write_text(snapshot, encoding="utf-8")
                restored = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                if restored != snapshot_hash:
                    print(f"FATAL: could not restore {relative}; aborting")
                    return 3
            if passed is None:
                print(f"[BROKEN]   {index:>2}. {label}  ({summary})")
                unproven.append(label)
            elif passed:
                print(f"[SURVIVED] {index:>2}. {label}")
                survivors.append(label)
            else:
                print(f"[KILLED]   {index:>2}. {label}  ({summary})")

        print()
        after = tree_fingerprint()
        if before != after:
            changed = sorted(set(before.items()) ^ set(after.items()))
            print(f"FATAL: the repository changed during the run: {changed[:5]}")
            return 3
        print(f"integrity  : all {len(before)} tracked implementation files unchanged")

        if anchor_missing:
            # A skipped mutation is not a killed one. Reporting success here was a
            # real defect: thirteen stale anchors let the tool print "All N mutations
            # were killed" while testing none of the redaction, replay or scope fixes.
            print(f"{len(anchor_missing)} mutation(s) could not be applied (anchor not found):")
            for label in anchor_missing:
                print(f"  not applied: {label}")
            print("The table is stale: an anchor no longer matches the source.")
            return 4
        if unproven:
            print(f"{len(unproven)} mutation(s) could not be judged (the suite did not collect):")
            for label in unproven:
                print(f"  unproven: {label}")
            return 5
        if survivors:
            print(f"{len(survivors)} mutation(s) survived; the suite is weaker than it looks.")
            for label in survivors:
                print(f"  survived: {label}")
            return 1
        print(f"All {len(selected)} mutations were killed by the suite.")
        return 0
    except KeyboardInterrupt:
        print("\ninterrupted: the development tree was never mutated; the copy is discarded")
        return 130
    finally:
        if args.keep_temp:
            print(f"keeping temporary copy at {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
