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
    "graph_runtime",
]

START = "__start__"
END = "__end__"
RECURSION_ERROR = "recursion_limit_exceeded"

try:  # pragma: no cover - exercised by whichever branch the environment takes
    from langgraph.graph import END as _LG_END
    from langgraph.graph import START as _LG_START
    from langgraph.graph import StateGraph as _LGStateGraph

    GRAPH_RUNTIME_AVAILABLE = True
    START = _LG_START
    END = _LG_END
    StateGraph: Any = _LGStateGraph
except ImportError:  # pragma: no cover
    GRAPH_RUNTIME_AVAILABLE = False
    StateGraph = None


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
                raise RuntimeError(RECURSION_ERROR)
            action = self.builder._nodes[node]
            parameters = inspect.signature(action).parameters
            if len(parameters) >= 2:
                update = action(current, context)
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
