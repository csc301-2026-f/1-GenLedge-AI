"""Mutation check: break a critical line, confirm the suite notices, restore.

A passing suite proves nothing if the tests cannot fail. This applies three
one-line mutations to load-bearing logic, runs the suite after each, and restores
the file from a byte-for-byte backup. It exits non-zero if any mutation survives.

Usage:  <venv python> tools/mutation_check.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "src" / "backend"

# (label, file, original text, mutated text)
MUTATIONS = [
    (
        "tool budget is not checked before dispatch",
        BACKEND / "app/agent/nodes.py",
        'if state.get("tool_calls_used", 0) >= budgets.max_tool_calls:',
        'if False and state.get("tool_calls_used", 0) >= budgets.max_tool_calls:',
    ),
    (
        "recorded tool results are not replayed",
        BACKEND / "app/agent/tools.py",
        "        recorded = self.repository.get_tool_result(job_id, request.id)",
        "        recorded = None  # MUTATED: replay disabled",
    ),
    (
        "the three-sample cap is removed",
        BACKEND / "app/agent/prompts.py",
        "        samples = [neutralise_delimiters(redact_value(value, field.ref.field_path)) for value in field.samples[:3]]",
        "        samples = [neutralise_delimiters(redact_value(value, field.ref.field_path)) for value in field.samples]  # MUTATED",
    ),
    (
        "the model-call budget ignores the durable count",
        BACKEND / "app/agent/nodes.py",
        "    return max(durable, state.get(\"model_calls_used\", 0)) if durable else state.get(\"model_calls_used\", 0)",
        "    return state.get(\"model_calls_used\", 0)  # MUTATED: durable count ignored",
    ),
    (
        "a failing tool call is not charged against the budget",
        BACKEND / "app/agent/tools.py",
        "        return ToolOutcome(result=result, replayed=False, charged=charge)",
        "        return ToolOutcome(result=result, replayed=False, charged=False)  # MUTATED",
    ),
    (
        "source text may forge the untrusted-data delimiters",
        BACKEND / "app/agent/prompts.py",
        "        name = neutralise_delimiters(redact_value(resource.name, \"name\"))",
        "        name = redact_value(resource.name, \"name\")  # MUTATED",
    ),
    (
        "the resource name is not projected at all",
        BACKEND / "app/agent/prompts.py",
        "            f\"  - {resource.resource_id} (name={name}, kind={resource.kind}, \"",
        "            f\"  - {resource.resource_id} (kind={resource.kind}, \"  # MUTATED",
    ),
]


def run_suite() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "src/backend/tests/agent"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = [line for line in proc.stdout.splitlines() if "passed" in line or "failed" in line]
    return proc.returncode == 0, (tail[-1] if tail else proc.stdout[-200:])


def main() -> int:
    survivors: list[str] = []
    for label, path, original, mutated in MUTATIONS:
        source = path.read_text(encoding="utf-8")
        if original not in source:
            print(f"[SKIP] {label}: anchor not found in {path.name}")
            survivors.append(label)
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            path.write_text(source.replace(original, mutated, 1), encoding="utf-8")
            passed, summary = run_suite()
        finally:
            shutil.copy2(backup, path)
            backup.unlink()
        if passed:
            print(f"[SURVIVED] {label}  <-- the suite does not detect this")
            survivors.append(label)
        else:
            print(f"[KILLED]   {label}  ({summary})")

    print()
    if survivors:
        print(f"{len(survivors)} mutation(s) survived; the suite is weaker than it looks.")
        return 1
    print(f"All {len(MUTATIONS)} mutations were killed by the suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
