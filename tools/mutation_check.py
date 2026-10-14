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
        "samples = [_bounded_text(projected(value, field.ref.field_path)) for value in field.samples[:3]]",
        "samples = [_bounded_text(projected(value, field.ref.field_path)) for value in field.samples]  # MUTATED",
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
        "snapshot_id is rendered without the projection chokepoint",
        BACKEND / "app/agent/prompts.py",
        "    lines = [f\"snapshot_id: {projected(inventory.snapshot_id, 'snapshot_id')}\"]",
        "    lines = [f\"snapshot_id: {inventory.snapshot_id}\"]  # MUTATED: B1 vector",
    ),
    (
        "resource_id is rendered without the projection chokepoint",
        BACKEND / "app/agent/prompts.py",
        "            f\"  - {projected(resource.resource_id, 'resource_id')} \"",
        "            f\"  - {resource.resource_id} \"  # MUTATED: B1 vector",
    ),
    (
        "the tool name and call id are rendered raw",
        BACKEND / "app/agent/prompts.py",
        "        tool = projected(result.tool, \"tool\")",
        "        tool = result.tool  # MUTATED: B1 vector",
    ),
    (
        "the previous response is quoted without neutralisation",
        BACKEND / "app/agent/prompts.py",
        "\"previous_response\": _bounded_text(str(projected(previous_response, \"previous_response\"))),",
        "\"previous_response\": _bounded_text(previous_response),  # MUTATED: B1 vector",
    ),
    (
        "a table is emitted with no attributes",
        BACKEND / "app/agent/models.py",
        "    tables: list[Table] = []\n    if attributes:",
        "    tables: list[Table] = []\n    if True:  # MUTATED: emits the orders table unconditionally",
    ),
    (
        "the text cap is a no-op",
        BACKEND / "app/agent/prompts.py",
        "def _bounded_text(text: str) -> str:\n    if len(text) <= MAX_PROJECTED_TEXT:\n        return text",
        "def _bounded_text(text: str) -> str:\n    if True:  # MUTATED\n        return text",
    ),
    (
        "the recursion derivation is replaced by the floor",
        BACKEND / "app/agent/graph.py",
        "    worst_case = 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls + 12\n    return max(budgets.recursion_limit, int(worst_case * 1.4))",
        "    return budgets.recursion_limit  # MUTATED: derivation removed",
    ),
    (
        "the field-path scope control is removed",
        BACKEND / "app/agent/tools.py",
        "        unknown = [path for path in self._requested_field_paths(dumped) if path not in self.allowed_field_paths()]",
        "        unknown = []  # MUTATED: field paths unvalidated",
    ),
    (
        "auto mode treats a provider name as configuration",
        BACKEND / "app/agent/models.py",
        "    return any(str(source.get(name, \"\")).strip() for name in PROVIDER_CREDENTIAL_ENV_VARS)",
        "    return any(str(source.get(name, \"\")).strip() for name in PROVIDER_ENV_VARS)  # MUTATED",
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
