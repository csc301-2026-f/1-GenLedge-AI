"""The LangGraph import seam.

`langgraph` is the intended runtime (see `plans/LANGGRAPH_HARNESS_PLAN.md` §8.1).
This module is the *only* place that imports it, so:

* the graph code is written once against the real `StateGraph` API —
  `add_node`, `add_edge`, `add_conditional_edges`, `compile`, `invoke`;
* a checkout without `langgraph` installed still executes the same three nodes
  through `LocalGraphRunner`, so the graph logic is testable offline. The
  fallback is labelled, never silent: `graph_runtime()` says which one is live and
  `tests/agent/test_graph_shape.py` asserts the real library is used whenever it
  is importable.

`LocalGraphRunner` implements the subset of LangGraph semantics this graph uses:
a node receives the whole state and returns a partial update, a field annotated
with a reducer merges, every other field is replaced, and `recursion_limit`
counts supersteps.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable

__all__ = [
    "END",
    "GRAPH_RUNTIME_AVAILABLE",
    "START",
    "LocalGraphRunner",
    "LocalStateGraph",
    "RecursionLimitExceeded",
    "graph_runtime",
    "guarded",
    "runtime_for",
]

START = "__start__"
END = "__end__"
RECURSION_ERROR = "recursion_limit_exceeded"

try:  # pragma: no cover - exercised by whichever branch the environment takes
    from langgraph.graph import END as _LG_END
    from langgraph.graph import START as _LG_START
    from langgraph.graph import StateGraph as _LGStateGraph
    from langgraph.runtime import Runtime as _LGRuntime

    GRAPH_RUNTIME_AVAILABLE = True
    START = _LG_START
    END = _LG_END
    StateGraph: Any = _LGStateGraph
except ImportError:  # pragma: no cover
    GRAPH_RUNTIME_AVAILABLE = False
    StateGraph = None
    _LGRuntime = None


class _SimpleRuntime:
    """A stand-in for LangGraph's `Runtime` carrying only the run-scoped payload."""

    __slots__ = ("context",)

    def __init__(self, context: Any) -> None:
        self.context = context


def runtime_for(context: Any) -> Any:
    """Wrap a run-scoped payload the way the active runtime delivers it.

    LangGraph hands nodes a `Runtime` whose `.context` is the object passed to
    `invoke(context=...)`; the local runner delivers the payload directly. `guarded`
    unwraps `.context` when it is present, so both reach the node identically.
    """

    if _LGRuntime is not None:
        return _LGRuntime(context=context)
    return _SimpleRuntime(context)


def graph_runtime() -> str:
    """Name the runtime in use: `langgraph` or the labelled local fallback."""

    return "langgraph" if GRAPH_RUNTIME_AVAILABLE else "local-fallback"


def _channel_reducer(annotation: Any) -> Callable[[Any, Any], Any] | None:
    """Return the reducer declared on a state field, if any."""

    metadata = getattr(annotation, "__metadata__", None)
    if metadata:
        for item in metadata:
            if callable(item):
                return item
    return None


class RecursionLimitExceeded(RuntimeError):
    """The local runner's backstop. Mapped to `recursion_limit_exceeded` by the callers."""


def guarded(node_name: str, action: Callable[..., Any]) -> Callable[..., Any]:
    """Adapt a node to the graph runtime and check its partial update.

    Three jobs, because this is the one place every runtime goes through:

    * **Injection.** LangGraph injects a parameter **named** `runtime` as a keyword,
      and only if it can see that parameter in the callable's signature. Wrapping a
      node in `*args, **kwargs` therefore silently breaks the injection — the node
      runs without a runtime at all. This wrapper declares `runtime` itself so the
      library finds it, and hands the wrapped node the run-scoped payload it expects
      (`runtime.context`), not the framework object.
    * **Boundary 5.** A node returning a key it does not own is `invalid_state_update`
      (`plans/LANGGRAPH_HARNESS_PLAN.md` §5.4), not a silent merge.
    * **Runtime portability.** `LocalGraphRunner` calls the same wrapper and passes a
      plain payload, so a node cannot work on one runtime and break on the other.
    """

    from app.agent.state import validate_node_update  # noqa: PLC0415 - avoids a cycle at import

    def wrapped(state: dict[str, Any], runtime: Any = None) -> dict[str, Any]:
        payload = getattr(runtime, "context", runtime)
        update = action(state, runtime=payload)
        if update:
            validate_node_update(node_name, dict(update))
        return update

    wrapped.__name__ = getattr(action, "__name__", node_name)
    return wrapped


class LocalStateGraph:
    """A `StateGraph`-shaped builder used only when `langgraph` is absent."""

    def __init__(self, state_schema: type) -> None:
        self.state_schema = state_schema
        self._nodes: dict[str, Callable[..., Any]] = {}
        self._edges: list[tuple[str, str]] = []
        self._conditional: list[tuple[str, Callable[..., str], dict[str, str]]] = []
        self._entry: str | None = None

    def add_node(self, name: str, action: Callable[..., Any]) -> "LocalStateGraph":
        self._nodes[str(name)] = action
        return self

    def add_edge(self, start: str, end: str) -> "LocalStateGraph":
        self._edges.append((str(start), str(end)))
        if str(start) == START:
            self._entry = str(end)
        return self

    def add_conditional_edges(
        self,
        start: str,
        condition: Callable[..., str],
        mapping: dict[str, str] | None = None,
    ) -> "LocalStateGraph":
        self._conditional.append((str(start), condition, dict(mapping or {})))
        return self

    def compile(self) -> "LocalGraphRunner":
        return LocalGraphRunner(self)


class LocalGraphRunner:
    """Executes a `LocalStateGraph`. Never used when `langgraph` is importable."""

    def __init__(self, builder: LocalStateGraph) -> None:
        self.builder = builder

    def invoke(
        self,
        state: dict[str, Any] | None = None,
        *,
        context: Any = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reducers: dict[str, Callable[[Any, Any], Any]] = {}
        hints = typing.get_type_hints(self.builder.state_schema, include_extras=True)
        for key, annotation in hints.items():
            reducer = _channel_reducer(annotation)
            if reducer is not None:
                reducers[key] = reducer

        current: dict[str, Any] = dict(state or {})
        limit = int((config or {}).get("recursion_limit") or 200)
        steps = 0

        def apply(update: dict[str, Any]) -> None:
            for key, value in update.items():
                if key in reducers:
                    current[key] = reducers[key](current.get(key), value)
                else:
                    current[key] = value

        node = self.builder._entry or START
        conditional = {start: (fn, mapping) for start, fn, mapping in self.builder._conditional}
        next_of = dict(self.builder._edges)

        while node not in (END, None):
            steps += 1
            if steps > limit:
                raise RecursionLimitExceeded(RECURSION_ERROR)
            action = self.builder._nodes[node]
            parameters = inspect.signature(action).parameters
            if len(parameters) >= 2:
                # The runtime travels as a keyword, exactly as LangGraph delivers it.
                update = action(current, runtime=runtime_for(context))
            else:
                update = action(current)
            if update:
                apply(update)
            if node in conditional:
                fn, mapping = conditional[node]
                target = fn(current)
                node = mapping.get(target, target)
            else:
                node = next_of.get(node, END)
        return current
