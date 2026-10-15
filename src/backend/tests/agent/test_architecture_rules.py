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


def _imports_in_source(source: str, package: tuple[str, ...]) -> set[str]:
    """Static imports named by a source string, resolved against its package path."""

    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                prefix = ".".join(base)
            else:
                prefix = node.module or ""
            if prefix:
                found.add(prefix)
            # `from app import agent` → `app.agent`; `from . import agent` → `<pkg>.agent`
            found.update(f"{prefix}.{alias.name}" for alias in node.names if prefix)
    return found


def _imported_modules(path: Path) -> set[str]:
    """Every module an import in this file names, including the names it imports.

    `from app import agent` binds `app.agent`, but the *module* in the node is only
    `app` — so a scan that reads `node.module` alone misses it and the
    runs-never-imports-agent rule silently stops applying. Both the module and each
    imported name are recorded.
    """

    return _imports_in_source(path.read_text(encoding="utf-8"), path.parent.relative_to(BACKEND).parts)


def _python_files(package: str) -> list[Path]:
    return sorted((APP / package).rglob("*.py"))


def _dynamic_imports_in_source(source: str) -> set[str]:
    """Modules named by a runtime import: `__import__("x")`, `importlib.import_module("x")`.

    An AST walk for `Import`/`ImportFrom` nodes misses these, and they are exactly how
    someone would route around the rule without noticing they had. Literal strings are
    read too, because `import_module(name="app.agent.graph")` is the same coupling.
    """

    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in {"__import__", "import_module", "import_library"}:
            continue
        literals = [
            argument.value
            for argument in list(node.args) + [kw.value for kw in node.keywords]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
        if literals:
            found.update(literals)
        else:
            # A computed module name cannot be resolved statically. Recorded loudly so
            # a rule refuses it rather than silently passing.
            found.add("<unresolvable dynamic import>")
    return found


def _dynamic_imports(path: Path) -> set[str]:
    return _dynamic_imports_in_source(path.read_text(encoding="utf-8"))


def _all_imports(path: Path) -> set[str]:
    return _imported_modules(path) | _dynamic_imports(path)


def test_the_scan_sees_dynamic_imports_too():
    """Guard: a rule that only reads import statements is bypassable by one call."""

    source = (
        "import importlib\n"
        'importlib.import_module("app.agent.graph")\n'
        '__import__("app.runs")\n'
        "def f():\n"
        '    return importlib.import_module(name="app.pipelines")\n'
        "def g(name):\n"
        "    return importlib.import_module(name)\n"
    )
    found = _dynamic_imports_in_source(source)
    assert "app.agent.graph" in found
    assert "app.runs" in found
    assert "app.pipelines" in found
    # a computed module name cannot be resolved, and must not pass silently
    assert "<unresolvable dynamic import>" in found


def test_runs_never_imports_the_agent():
    """A model must have no path to warehouse execution."""

    offenders: list[str] = []
    for path in _python_files("runs"):
        for module in _all_imports(path):
            if module == "app.agent" or module.startswith("app.agent."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_the_scan_catches_from_app_import_agent():
    """`from app import agent` binds the package without naming it as a module.

    Inside `app/runs/x.py`, `from .. import agent` and `from app import agent` are the
    same coupling; neither names `app.agent` as `node.module`, so both evaded the rule
    until the imported *names* were read.
    """

    absolute = _imports_in_source("from app import agent\n", ("app", "runs"))
    relative = _imports_in_source("from .. import agent\n", ("app", "runs"))
    nested = _imports_in_source("from app.agent import graph\n", ("app", "runs"))

    assert "app.agent" in absolute
    assert "app.agent" in relative, relative
    assert "app.agent.graph" in nested


def test_no_module_uses_an_unresolvable_dynamic_import():
    """A computed import name is recorded as unresolvable, and every rule refuses it.

    The marker exists so a rule cannot pass silently over coupling it could not read.
    Without this, `importlib.import_module(variable)` in `runs/` would be invisible.
    """

    offenders: list[str] = []
    for package in ("agent", "runs", "mappings", "pipelines", "sources", "common"):
        if not (APP / package).is_dir():
            continue
        for path in _python_files(package):
            if "<unresolvable dynamic import>" in _all_imports(path):
                offenders.append(str(path.relative_to(BACKEND)))
    assert not offenders, (
        f"these modules import a computed module name, which no rule can check: {offenders}"
    )


def test_the_agent_does_not_own_other_packages_jobs():
    """`app.agent` proposes; validation, persistence and HTTP belong elsewhere."""

    forbidden = ("app.mappings", "app.runs", "app.pipelines")
    offenders: list[str] = []
    for path in _python_files("agent"):
        for module in _all_imports(path):
            if any(module == name or module.startswith(f"{name}.") for name in forbidden):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_the_agent_does_not_serve_http():
    """No Flask import inside the harness: it must stay framework-independent."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        for module in _all_imports(path):
            if module == "flask" or module.startswith("flask."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_only_graphs_imports_langgraph():
    """One seam for the optional dependency, so `graph_runtime()` cannot lie."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        if path.name == "graphs.py":
            continue
        for module in _all_imports(path):
            if module == "langgraph" or module.startswith("langgraph."):
                offenders.append(f"{path.relative_to(BACKEND)} imports {module}")
    assert not offenders, offenders


def test_only_models_imports_a_provider_sdk():
    """`app/agent/llm.py` in the plan's naming; here the adapters module."""

    offenders: list[str] = []
    for path in _python_files("agent"):
        if path.name == "models.py":
            continue
        for module in _all_imports(path):
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
