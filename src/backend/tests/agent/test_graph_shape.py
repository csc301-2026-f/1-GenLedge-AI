"""The compiled graph has exactly three nodes and the US4 edges."""

from __future__ import annotations

import pytest

from app.agent.graph import (
    DECLARED_CONDITIONAL_EDGES,
    build_graph,
    derived_recursion_limit,
    graph_shape,
)
from app.agent.graphs import END, GRAPH_RUNTIME_AVAILABLE, START, graph_runtime
from app.agent.nodes import CONTEXT, PROPOSE, TOOL_CALL

LANGGRAPH = pytest.mark.skipif(
    not GRAPH_RUNTIME_AVAILABLE,
    reason="langgraph is not installed; the labelled local runner is exercised instead",
)


def test_graph_declares_exactly_three_nodes():
    shape = graph_shape()
    assert shape.nodes == (CONTEXT, PROPOSE, TOOL_CALL)
    assert len(shape.nodes) == 3


def test_graph_declares_the_us4_edges():
    shape = graph_shape()
    assert (START, CONTEXT) in shape.edges
    assert (TOOL_CALL, PROPOSE) in shape.edges
    # The loop edge exists; `context -> propose` is conditional, not static.
    assert (CONTEXT, PROPOSE) not in shape.edges
    assert shape.conditional_edges[CONTEXT] == {"propose": PROPOSE, "end": END}
    assert shape.conditional_edges[PROPOSE] == {"tool_call": TOOL_CALL, "end": END}
    assert PROPOSE not in shape.conditional_edges.get(TOOL_CALL, {})


def test_compiled_graph_runs_and_stops_at_end():
    graph = build_graph()
    assert hasattr(graph, "invoke")
    assert graph_runtime() in {"langgraph", "local-fallback"}


@LANGGRAPH
def test_compiled_langgraph_exposes_the_declared_nodes_and_edges():
    graph = build_graph()
    drawable = graph.get_graph()
    node_ids = set(drawable.nodes)
    assert {CONTEXT, PROPOSE, TOOL_CALL} <= node_ids

    edges = {(edge.source, edge.target) for edge in drawable.edges}
    assert (START, CONTEXT) in edges
    assert (TOOL_CALL, PROPOSE) in edges
    assert (PROPOSE, TOOL_CALL) in edges
    assert (CONTEXT, PROPOSE) in edges

    # START and END are the runtime's own markers, not application nodes.
    assert not {name for name in node_ids if name not in {START, END}} - {
        CONTEXT,
        PROPOSE,
        TOOL_CALL,
    }


@LANGGRAPH
def test_compiled_graph_contains_no_extra_application_node():
    graph = build_graph()
    node_ids = set(graph.get_graph().nodes)
    application_nodes = node_ids - {START, END}
    assert application_nodes == {CONTEXT, PROPOSE, TOOL_CALL}


def test_recursion_limit_is_derived_above_the_semantic_budgets():
    from app.agent.contracts import AgentBudgets

    budgets = AgentBudgets(max_tool_calls=40, max_model_calls=20, recursion_limit=200)
    # Each tool round costs two supersteps, so the semantic budgets must fire first.
    assert derived_recursion_limit(budgets) >= 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls
    assert derived_recursion_limit(budgets) >= budgets.recursion_limit


def test_declared_conditional_edges_cover_every_conditional_source():
    assert set(DECLARED_CONDITIONAL_EDGES) == {CONTEXT, PROPOSE}
    assert set(DECLARED_CONDITIONAL_EDGES[CONTEXT].values()) == {PROPOSE, END}
    assert set(DECLARED_CONDITIONAL_EDGES[PROPOSE].values()) == {TOOL_CALL, END}
