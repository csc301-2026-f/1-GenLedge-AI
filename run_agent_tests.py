"""A minimal pytest-compatible runner, for machines that cannot install pytest.

**Use `python -m pytest tests` whenever it is available — that is the authoritative
command.** This script exists because the machine this slice was developed on has no
network access, so `pydantic`, `flask`, `langgraph` and `pytest` could not be
installed into the one interpreter that has `pydantic` (a conda environment on the
Desktop). It provides the small slice of the pytest API `tests/agent/` uses —
`pytest.raises`, `pytest.mark.parametrize`, `pytest.mark.skipif` and the
`monkeypatch` fixture — so the real test bodies run unmodified.

It is a development aid, not part of the deliverable. `verify_us4_person_b.py` is
the independent, requirement-level check; this script runs the suite.

Usage:
    <python with pydantic> run_agent_tests.py
Exit code 0 when every collected case passes.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "src" / "backend"
sys.path.insert(0, str(BACKEND))

if not (BACKEND / "app" / "agent" / "contracts.py").is_file():
    sys.exit(f"cannot find the agent package under {BACKEND}")


# --- pytest shim ---------------------------------------------------------------
class _Skipped(Exception):
    pass


class _Raises:
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"DID NOT RAISE {self.expected}")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        if self.match is not None and not re.search(self.match, str(exc)):
            raise AssertionError(f"pattern {self.match!r} not found in {str(exc)!r}")
        return True


class _Mark:
    def parametrize(self, argnames, argvalues, **kwargs):
        names = [item.strip() for item in argnames.split(",")] if isinstance(argnames, str) else list(argnames)

        def decorator(func):
            func._parametrize = getattr(func, "_parametrize", []) + [(names, list(argvalues))]
            return func

        return decorator

    def skipif(self, condition, reason=""):
        def decorator(func):
            if condition:
                func._skip = reason or "skipped"
            return func

        return decorator

    def skip(self, reason=""):
        def decorator(func):
            func._skip = reason or "skipped"
            return func

        return decorator


class _Missing:
    pass


_MISSING = _Missing()


class _MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setenv(self, name, value):
        import os

        self._undo.append(("env", name, os.environ.get(name)))
        os.environ[name] = value

    def delenv(self, name, raising=True):
        import os

        old = os.environ.get(name)
        if old is None and raising:
            raise KeyError(name)
        self._undo.append(("env", name, old))
        os.environ.pop(name, None)

    def setitem(self, mapping, key, value):
        self._undo.append(("item", mapping, key, mapping.get(key, _MISSING)))
        mapping[key] = value

    def setattr(self, target, name, value):
        self._undo.append(("attr", target, name, getattr(target, name, _MISSING)))
        setattr(target, name, value)

    def undo(self):
        import os

        while self._undo:
            entry = self._undo.pop()
            if entry[0] == "env":
                _, name, old = entry
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
            elif entry[0] == "item":
                _, mapping, key, old = entry
                if old is _MISSING:
                    mapping.pop(key, None)
                else:
                    mapping[key] = old
            else:
                _, target, name, old = entry
                if old is _MISSING:
                    delattr(target, name)
                else:
                    setattr(target, name, old)


def _skip(reason=""):
    raise _Skipped(reason)


def _importorskip(name, *args, **kwargs):
    try:
        return importlib.import_module(name)
    except ImportError:
        raise _Skipped(f"missing {name}")


def _fixture_decorator(*args, **kwargs):
    def apply(func):
        func._is_fixture = True
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return apply(args[0])
    return lambda func: apply(func)


_FIXTURES: dict = {}


def register_fixture(name, factory):
    _FIXTURES[name] = factory


def _make_fixture(func):
    def factory(monkeypatch):
        if "monkeypatch" in inspect.signature(func).parameters:
            return func(monkeypatch)
        return func()

    return factory


def _fixture_kwargs(func, monkeypatch):
    kwargs = {}
    for name in inspect.signature(func).parameters:
        if name == "monkeypatch":
            kwargs[name] = monkeypatch
        elif name in _FIXTURES:
            kwargs[name] = _FIXTURES[name](monkeypatch)
    return kwargs


shim = type(sys)("pytest")
shim.raises = lambda expected, match=None, **kwargs: _Raises(expected, match)
shim.mark = _Mark()
shim.skip = _skip
shim.importorskip = _importorskip
shim.fail = lambda msg="": (_ for _ in ()).throw(AssertionError(msg))
shim.fixture = _fixture_decorator
sys.modules["pytest"] = shim


# --- runner --------------------------------------------------------------------
def _load_tests_package():
    """Register `tests` and `tests.agent` without requiring `tests/__init__.py`."""

    tests_dir = BACKEND / "tests"
    root = importlib.util.module_from_spec(importlib.util.spec_from_loader("tests", None))
    root.__path__ = [str(tests_dir)]  # type: ignore[attr-defined]
    sys.modules["tests"] = root

    agent_dir = tests_dir / "agent"
    pkg = importlib.util.module_from_spec(importlib.util.spec_from_loader("tests.agent", None))
    pkg.__path__ = [str(agent_dir)]  # type: ignore[attr-defined]
    sys.modules["tests.agent"] = pkg


def _run_case(func, kwargs, label, results):
    monkeypatch = _MonkeyPatch()
    try:
        func(**kwargs, **_fixture_kwargs(func, monkeypatch))
    except _Skipped as skip:
        results["skipped"].append((label, str(skip)))
    except Exception:  # noqa: BLE001
        results["failed"].append((label, traceback.format_exc()))
    else:
        results["passed"].append(label)
    finally:
        monkeypatch.undo()


def main() -> int:
    _load_tests_package()
    results: dict[str, list] = {"passed": [], "failed": [], "skipped": []}
    for path in sorted((BACKEND / "tests" / "agent").glob("test_*.py")):
        module = importlib.import_module(f"tests.agent.{path.stem}")
        for name, value in vars(module).items():
            if getattr(value, "_is_fixture", False):
                register_fixture(name, _make_fixture(value))
        for name, func in vars(module).items():
            if not name.startswith("test_") or not callable(func):
                continue
            label = f"{path.stem}::{name}"
            if getattr(func, "_skip", None):
                results["skipped"].append((label, func._skip))
                continue
            parametrize = getattr(func, "_parametrize", None)
            if not parametrize:
                _run_case(func, {}, label, results)
                continue
            for names, values in parametrize:
                for case in values:
                    case_values = case if isinstance(case, (tuple, list)) else (case,)
                    _run_case(func, dict(zip(names, case_values)), f"{label}[{case_values}]", results)

    print(f"passed={len(results['passed'])} failed={len(results['failed'])} skipped={len(results['skipped'])}")
    for label, reason in results["skipped"]:
        print(f"SKIP {label}: {reason}")
    for label, tb in results["failed"]:
        print(f"\nFAIL {label}\n{tb}")
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
