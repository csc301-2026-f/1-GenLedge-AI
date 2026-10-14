"""Architecture rules the plan states, enforced as code rather than as prose.

`plans/LANGGRAPH_HARNESS_PLAN.md` §12.3 Phase 7 and §3.5 make two boundaries
structural:

* **Execution must not import the agent.** `runs` compiles an *approved* version;
  a model never reaches warehouse execution. The plan asks for "a simple import
  scan" to keep that true.
* **The agent must not own another package's job.** `app.agent` proposes; it does
  not run deterministic validation (`app.mappings.validation`), persist
  (`app.mappings.models`), or serve HTTP (`routes.py`).

An AST scan rather than a grep, so a `from . import x` inside a function or a
`TYPE_CHECKING` block counts too — the rule is about coupling, not about syntax.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"


def _imported_modules(path: Path) -> set[str]:
    """Every module named by an import in this file, at any nesting depth."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: resolve against the package path
                package = path.parent.relative_to(BACKEND).parts
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                prefix = ".".join(base)
                found.add(f"{prefix}.{node.module}" if node.module else prefix)
            elif node.module:
                found.add(node.module)
    return found


def _python_files(package: str) -> list[Path]:
    return sorted((APP / package).rglob("*.py"))


def test_runs_never_imports_the_agent():
    """A model must have no path to warehouse execution."""

    offenders: list[str] = []
    for path in _python_files("runs"):
        for module in _imported_modules(path):
            if module == "app.agent" or module.startswith("app.agent."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_the_agent_does_not_own_other_packages_jobs():
    """`app.agent` proposes; validation, persistence and HTTP belong elsewhere."""

    forbidden = ("app.mappings", "app.runs", "app.pipelines")
    offenders: list[str] = []
    for path in _python_files("agent"):
        for module in _imported_modules(path):
            if any(module == name or module.startswith(f"{name}.") for name in forbidden):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_the_agent_does_not_serve_http():
    """No Flask import inside the harness: it must stay framework-independent."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        for module in _imported_modules(path):
            if module == "flask" or module.startswith("flask."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_only_graphs_imports_langgraph():
    """One seam for the optional dependency, so `graph_runtime()` cannot lie."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        if path.name == "graphs.py":
            continue
        for module in _imported_modules(path):
            if module == "langgraph" or module.startswith("langgraph."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_only_models_imports_a_provider_sdk():
    """`app/agent/llm.py` in the plan's naming; here the adapters module."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        if path.name == "models.py":
            continue
        for module in _imported_modules(path):
            if module.split(".")[0] in {"anthropic", "openai"}:
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_the_scan_actually_reads_imports():
    """Guard against a scan that silently matches nothing and always passes."""

    modules = _imported_modules(APP / "agent" / "graph.py")
    assert "app.agent.graphs" in modules
    assert modules, "the scanner found no imports at all"
    # a relative and a nested import are both seen
    assert _imported_modules(APP / "agent" / "nodes.py")
    assert _imported_modules(APP / "common" / "errors.py")


@pytest.mark.parametrize("package", ["agent", "mappings", "runs", "sources", "common"])
def test_the_scan_covers_every_package_that_exists(package):
    """A package added without files must not silently make a rule vacuous."""

    if not (APP / package).is_dir():
        pytest.skip(f"app/{package} does not exist yet")
    assert _python_files(package), f"app/{package} has no python files to scan"
