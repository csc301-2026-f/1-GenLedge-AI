"""Do the regression tests actually fail when their fix is reverted?

    python tools/sensitivity_check.py

A regression test that cannot fail proves nothing, and neither does a report that says
"covered by tests". This tool answers the narrower question directly: for each named fix,
revert **that fix only** in a throwaway copy of the backend, run the tests that claim to
cover it, and require them to fail. Then it restores the copy and requires the same tests
to pass again.

It is deliberately not `tools/mutation_check.py`:

* the mutations are **semantic reverts of one fix each**, written by hand against the
  current source and named after the review finding they belong to, rather than a broad
  battery of line-level edits;
* nothing here is written to the development tree. Every edit lands in a copy, and the
  copy's path is printed so a kill mid-run costs a directory, not a checkout;
* a mutation whose anchor no longer matches the source is reported as `[STALE]` and exits
  non-zero — a silently skipped mutation is how a battery starts lying;
* the unmutated copy is run first, so a baseline that is not green is `[BROKEN]` rather
  than counted as a kill.

The copy location must be writable and outside the source tree. `--root` overrides it;
the default is the repository's ignored `.mutation-scratch/` directory, which is where
`tools/mutation_check.py` puts its copies too.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "src" / "backend"


@dataclass(frozen=True)
class Mutation:
    """One fix, reverted. `find` must appear exactly once in `path`."""

    finding: str
    label: str
    path: str
    find: str
    replace: str
    #: `-k` expression selecting the tests that claim to cover this fix.
    tests: str
    #: Test ids that must appear as failures. Empty means "any failure counts".
    expected: tuple[str, ...] = field(default=())


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        finding="C1 connector error redaction (error_code)",
        label="an undeclared connector code is persisted verbatim",
        path="app/agent/tools.py",
        find="            code = CONNECTOR_ERROR",
        replace="            code = code  # noqa: the declared code is persisted as-is",
        tests="i1_",
        expected=(
            "test_i1_an_unknown_connector_code_is_replaced_not_persisted",
            "test_i1_a_very_long_connector_code_cannot_be_persisted",
        ),
    ),
    Mutation(
        finding="C1 connector error redaction (validation report)",
        label="_brief renders every location part (connector-authored key names leak)",
        path="app/agent/tools.py",
        find=(
            "        str(part) if isinstance(part, int) or str(part) in declared_fields "
            "else UNDECLARED_FIELD_MARKER"
        ),
        replace="        str(part)",
        tests="i1_ or undeclared_connector_field",
        expected=(
            "test_i1_a_connector_chosen_field_name_cannot_reach_the_persisted_result",
            "test_an_undeclared_connector_field_is_rejected_not_absorbed",
        ),
    ),
    Mutation(
        finding="C1 connector error redaction (storage path)",
        label="the storage_failed message is persisted unredacted",
        path="app/agent/tools.py",
        find="                        message=redact_message(",
        replace="                        message=(",
        tests="i1_",
        expected=("test_i1_a_store_exception_cannot_write_a_credential_into_the_result",),
    ),
    Mutation(
        finding="C1 connector error redaction (fail-safe boundary)",
        label="persist redact_message(details) instead of the fixed message",
        path="app/agent/tools.py",
        find="            persisted_message = connector_error_message(code)",
        replace="            persisted_message = redact_message(details)",
        tests="i1_",
        expected=(
            # the unfamiliar shape is the one the blocklist cannot see
            "test_i1_an_unfamiliar_credential_shape_cannot_reach_the_persisted_result",
            "test_i1_an_ordinary_connector_error_is_replaced_by_the_typed_message",
            "test_i1_an_unknown_connector_code_is_replaced_not_persisted",
        ),
    ),
    Mutation(
        finding="C2 live provider validation",
        label="SUPPORTED_LIVE_PROVIDERS += openai",
        path="app/agent/models.py",
        find='SUPPORTED_LIVE_PROVIDERS: tuple[str, ...] = ("anthropic",)',
        replace='SUPPORTED_LIVE_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")',
        tests="provider",
        expected=(
            "test_an_advertised_provider_is_refused_when_no_adapter_exists_for_it",
            "test_build_model_client_refuses_an_unsupported_provider",
            "test_live_model_refuses_an_unsupported_provider",
        ),
    ),
    Mutation(
        finding="C3 durable model-call records",
        label="record_model_call fault: raise -> log and continue",
        path="app/agent/nodes.py",
        find="""    except Exception as error:  # noqa: BLE001 - the call happened; the record is the authority
        raise AgentFailure(
            REPOSITORY_UNAVAILABLE,
            "the durable model-call record could not be written, so the call could not "
            f"be charged: {type(error).__name__}: {error}",
            retryable=True,
        ) from error""",
        replace="""    except Exception as error:  # noqa: BLE001 - the call happened; the record is the authority
        logger.warning("swallowed: %s", error)
        return""",
        tests="i3_",
        expected=(
            "test_i3_a_raising_adapter_whose_record_cannot_be_written_ends_the_run",
            "test_i3_a_repair_call_whose_record_cannot_be_written_ends_the_run",
        ),
    ),
    Mutation(
        finding="C4 tool_node_timeout_seconds",
        label="dispatch calls the connector directly (no deadline)",
        path="app/agent/tools.py",
        find="            raw = self._call_connector(request.name, payload, job_id)",
        replace="            raw = self.connector.call(request.name, payload, job_id)",
        tests="i2_",
        expected=("test_i2_a_hung_connector_fails_its_call_not_the_node",),
    ),
    Mutation(
        finding="C4 model_node_timeout_seconds",
        label="the model-node deadline check is disabled",
        path="app/agent/nodes.py",
        find="    if _exceeded(node_started, model_deadline):",
        replace="    if False and _exceeded(node_started, model_deadline):",
        tests="i2_",
        expected=("test_i2_an_over_budget_model_answer_is_refused_and_charged",),
    ),
    Mutation(
        finding="C5 prompt manifest hashing",
        label="canonical_prompt_text no longer folds line endings",
        path="app/agent/prompts.py",
        find='    return raw.decode("utf-8").replace("\\r\\n", "\\n").replace("\\r", "\\n")',
        replace='    return raw.decode("utf-8")',
        tests="manifest or crlf or canonicalisation",
        expected=(
            "test_a_crlf_checkout_hashes_the_same_as_an_lf_checkout",
            "test_the_canonicalisation_matches_the_regeneration_tool",
        ),
    ),
)

_FAILURE = re.compile(r"^FAILED \S+?::([A-Za-z_][\w]*)(?:\[|$)", re.M)


def _python() -> str:
    """The interpreter with pytest and pydantic: the repository venv, or this one."""

    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _copy_backend(destination: Path) -> Path:
    """Copy the working implementation — uncommitted work included — to `destination`.

    The layout mirrors the repository (`<destination>/src/backend` plus
    `<destination>/tools`), because some tests resolve siblings by walking up from their
    own file — `test_the_canonicalisation_matches_the_regeneration_tool` looks for
    `tools/prompt_manifest.py` at the repository root — and a flattened copy would make
    them fail for a reason that has nothing to do with the mutation.
    """

    root = destination / "tree"
    backend = root / "src" / "backend"
    for stale in (root / "src", root / "tools"):
        shutil.rmtree(stale, ignore_errors=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        BACKEND,
        backend,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    shutil.copytree(
        ROOT / "tools",
        root / "tools",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (backend / "pytest.ini").write_text(
        "[pytest]\naddopts = -q\npythonpath = .\n", encoding="utf-8"
    )
    return backend


def _run_tests(backend: Path, tests: str, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    arguments = [
        _python(),
        "-m",
        "pytest",
        "tests/agent",
        "-k",
        tests,
        "-p",
        "no:cacheprovider",
        "--tb=no",
        "-q",
    ]
    if extra:
        arguments.extend(extra)
    return subprocess.run(
        arguments,
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
        env={**_env(), "PYTHONIOENCODING": "utf-8"},
    )


def _env() -> dict[str, str]:
    import os

    environment = dict(os.environ)
    environment.pop("GENLEDGE_MODEL_MODE", None)
    environment.pop("GENLEDGE_LLM_PROVIDER", None)
    # A recorded mode must not change what these tests do.
    environment["GENLEDGE_MODEL_MODE"] = "fake"
    return environment


def _verdict(mutation: Mutation, backend: Path) -> tuple[str, str]:
    """Apply one mutation, judge it, and restore the file. Returns (status, detail)."""

    target = backend / mutation.path
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(mutation.find)
    if occurrences != 1:
        return "STALE", f"anchor matched {occurrences} times in {mutation.path}"

    baseline = _run_tests(backend, mutation.tests)
    if baseline.returncode != 0:
        return "BROKEN", f"unmutated copy is not green: {_tail(baseline.stdout)}"

    try:
        target.write_text(original.replace(mutation.find, mutation.replace, 1), encoding="utf-8")
        mutated = _run_tests(backend, mutation.tests)
    finally:
        target.write_text(original, encoding="utf-8")
        if target.read_text(encoding="utf-8") != original:
            return "BROKEN", "the restore did not land"

    failed = set(_FAILURE.findall(mutated.stdout))
    if not failed:
        return "SURVIVED", "no test failed, so nothing actually covers this fix"
    missing = [name for name in mutation.expected if name not in failed]
    if missing:
        return "SURVIVED", f"expected failures absent: {missing}; got {sorted(failed)}"
    return "KILLED", ", ".join(sorted(failed))


def _tail(text: str, limit: int = 400) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(ROOT / ".mutation-scratch" / "sensitivity"),
        help="writable directory for the throwaway copy (outside the source tree)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    options = parser.parse_args()

    destination = Path(options.root).resolve()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"cannot create the copy location {destination}: {error}", file=sys.stderr)
        print("pass --root <writable directory>", file=sys.stderr)
        return 2
    if BACKEND == destination or BACKEND in destination.parents:
        print(f"refusing to copy the backend into itself: {destination}", file=sys.stderr)
        return 2

    backend = _copy_backend(destination)
    print(f"copy: {backend}")
    print(f"suite: {backend / 'pytest.ini'}")
    print()

    results: list[dict[str, str]] = []
    for mutation in MUTATIONS:
        status, detail = _verdict(mutation, backend)
        results.append(
            {
                "finding": mutation.finding,
                "label": mutation.label,
                "status": status,
                "detail": detail,
            }
        )
        print(f"[{status:8}] {mutation.finding}")
        print(f"           {mutation.label}")
        print(f"           {detail}")

    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print()
    print(
        "summary: "
        + ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        + f" of {len(results)} mutations"
    )
    if options.json:
        print(json.dumps(results, indent=2))

    bad = [item for item in results if item["status"] != "KILLED"]
    if bad:
        print()
        print("NOT a clean run. Each entry below is either a test that cannot fail, an")
        print("uncovered fix, or a stale anchor — all three need a human:")
        for item in bad:
            print(f"  [{item['status']}] {item['finding']}: {item['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
