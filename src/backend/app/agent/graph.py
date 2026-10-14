"""The compiled routing graph and the runner that owns its inputs.

```text
START -> context -> (propose | END)
propose -> (tool_call | END)
tool_call -> propose
```

Three nodes, exactly. The graph is built against the real LangGraph
`StateGraph` API when the package is installed and against the labelled local
runner from `app.agent.graphs` when it is not, so the same node functions are
exercised either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.agent import nodes as node_module
from app.agent.contracts import AgentBudgets, FailureInfo, InventoryView, ModelDraft
from app.agent.errors import ModelConfigurationError
from app.agent.graphs import (
    END,
    START,
    GRAPH_RUNTIME_AVAILABLE,
    LocalStateGraph,
    RecursionLimitExceeded,
    StateGraph,
    graph_runtime,
    guarded,
)
from app.agent.models import ModelClient, ModelResponse, ResolvedModelMode, build_model_client, resolve_model_mode
from app.agent.nodes import CONTEXT, PROPOSE, TOOL_CALL, GraphRuntime
from app.agent.repositories import RoutingRepository
from app.agent.state import RoutingJobState, initial_state
from app.agent.tools import FakeConnector, ToolConnector

logger = logging.getLogger(__name__)

RECURSION_LIMIT_EXCEEDED = "recursion_limit_exceeded"

try:  # pragma: no cover - depends on whether langgraph is installed
    from langgraph.errors import GraphRecursionError
except ImportError:  # pragma: no cover - the local runner has its own error type

    class GraphRecursionError(RuntimeError):  # type: ignore[no-redef]
        """Placeholder so the mapping below is uniform across runtimes."""

DECLARED_NODES: tuple[str, ...] = (CONTEXT, PROPOSE, TOOL_CALL)
DECLARED_EDGES: tuple[tuple[str, str], ...] = (
    (START, CONTEXT),
    (PROPOSE, TOOL_CALL),
    (TOOL_CALL, PROPOSE),
)
DECLARED_CONDITIONAL_EDGES: dict[str, dict[str, str]] = {
    CONTEXT: {"propose": PROPOSE, "end": END},
    PROPOSE: {"tool_call": TOOL_CALL, "end": END},
}


@dataclass(frozen=True)
class GraphShape:
    """The graph as the runner declares it; the integration test asserts on this."""

    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    conditional_edges: dict[str, dict[str, str]]


@dataclass
class RoutingRunResult:
    """Everything the worker needs after one graph run. No prompt text is included."""

    final_state: RoutingJobState
    runtime: GraphRuntime
    mode: ResolvedModelMode
    model_draft: ModelDraft | None
    failure: FailureInfo | None
    status: str
    model_responses: list[ModelResponse] = field(default_factory=list)

    @property
    def tool_result_refs(self) -> list[str]:
        return [item.result_ref for item in self.final_state.get("tool_results", [])]


def graph_shape() -> GraphShape:
    """The declared graph shape: three nodes, the edges of `US4` §4.3."""

    return GraphShape(
        nodes=DECLARED_NODES,
        edges=DECLARED_EDGES,
        conditional_edges={key: dict(value) for key, value in DECLARED_CONDITIONAL_EDGES.items()},
    )


def build_graph() -> Any:
    """Build and compile the three-node graph against whichever runtime is present.

    Each node is wrapped by `graphs.guarded`, so a node that returns a state key it
    does not declare fails as a state-guard error rather than merging silently.
    """

    builder = StateGraph(RoutingJobState) if GRAPH_RUNTIME_AVAILABLE else LocalStateGraph(RoutingJobState)
    builder.add_node(CONTEXT, guarded(CONTEXT, node_module.context_node))
    builder.add_node(PROPOSE, guarded(PROPOSE, node_module.propose_node))
    builder.add_node(TOOL_CALL, guarded(TOOL_CALL, node_module.tool_call_node))
    builder.add_edge(START, CONTEXT)
    builder.add_conditional_edges(CONTEXT, node_module.route_after_context, DECLARED_CONDITIONAL_EDGES[CONTEXT])
    builder.add_conditional_edges(PROPOSE, node_module.route_after_propose, DECLARED_CONDITIONAL_EDGES[PROPOSE])
    builder.add_edge(TOOL_CALL, PROPOSE)
    return builder.compile()


def derived_recursion_limit(budgets: AgentBudgets) -> int:
    """The runtime backstop, derived so the semantic budgets always fire first.

    Every tool round costs two supersteps (the model node and `tool_call`), which
    is `plans/LANGGRAPH_HARNESS_PLAN.md` §6.5's derivation. The configured
    `AgentBudgets.recursion_limit` is the floor, so a job is never stopped by the
    framework inside its own semantic budget.
    """

    worst_case = 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls + 12
    return max(budgets.recursion_limit, int(worst_case * 1.4))


def run_routing_job(
    *,
    job_id: str,
    source_snapshot_ids: list[str],
    repository: RoutingRepository,
    connector: ToolConnector | None = None,
    budgets: AgentBudgets | None = None,
    catalogue_ref: str | None = None,
    model: ModelClient | None = None,
    mode: ResolvedModelMode | None = None,
    env: Mapping[str, str] | None = None,
    cost_per_1k_tokens_usd: float | None = None,
) -> RoutingRunResult:
    """Run one routing job end to end and return the terminal state.

    The runner — not a node — builds the initial state from frozen configuration,
    which is what keeps a mid-job configuration change from extending a loop.
    `cost_per_1k_tokens_usd` is the price table `AgentBudgets.max_cost_usd` is
    evaluated against; with no price the ceiling is reported as unevaluable rather
    than guessed.
    """

    frozen_budgets = budgets or AgentBudgets()
    resolved = mode or resolve_model_mode(env=env)

    # `context` owns loading the inventory; the model adapter needs it too, so the
    # runner loads it once for adapter construction. It is not model input.
    inventory: InventoryView | None = None
    for snapshot_id in source_snapshot_ids:
        inventory = repository.get_inventory(snapshot_id)
        if inventory is not None:
            break
    catalogue = repository.get_catalogue(catalogue_ref)

    runtime = GraphRuntime(
        repository=repository,
        connector=connector or FakeConnector(),
        inventory=inventory,
        catalogue=catalogue,
        cost_per_1k_tokens_usd=cost_per_1k_tokens_usd,
    )
    if model is not None:
        runtime.model = model
    elif inventory is not None and inventory.fields:
        runtime.model = build_model_client(resolved, inventory=inventory, catalogue=catalogue, env=env)

    job_state = initial_state(
        job_id=job_id,
        source_snapshot_ids=source_snapshot_ids,
        budgets=frozen_budgets,
        model_mode=resolved.mode,
        catalogue_ref=catalogue_ref,
    )
    repository.create_job(job_id, source_snapshot_ids=list(source_snapshot_ids), catalogue_ref=catalogue_ref)
    graph = build_graph()
    final = _run_graph(graph, job_state, runtime, frozen_budgets)

    failure = final.get("failure")
    return RoutingRunResult(
        final_state=final,
        runtime=runtime,
        mode=resolved,
        model_draft=final.get("model_draft"),
        failure=failure,
        status=str(final.get("status") or _terminal_status(failure)),
        model_responses=list(runtime.responses),
    )


def _terminal_status(failure: FailureInfo | None) -> str:
    """The status a run leaves when no node wrote one.

    `context` writes `running` and `propose` writes its own terminal status, so this
    is only reached by a run that ended without either — which the graph does not
    produce. It reports the invariant honestly rather than assuming success.
    """

    return "failed" if failure is not None else "incomplete"


def _run_graph(graph: Any, job_state: RoutingJobState, runtime: GraphRuntime, budgets: AgentBudgets) -> RoutingJobState:
    """Invoke the graph, mapping the runtime's own backstop to a typed failure.

    The semantic budgets are derived to fire first, so reaching the recursion limit
    is a derivation bug. It is still reported as `recursion_limit_exceeded` with the
    accumulated counters rather than escaping as a framework error (master §9.1
    row 15).
    """

    config = {
        "configurable": {"thread_id": job_state["job_id"]},
        "recursion_limit": derived_recursion_limit(budgets),
    }
    try:
        return graph.invoke(job_state, context=runtime, config=config)
    except RecursionLimitExceeded:
        return _recursion_failure(
            job_state,
            "the graph reached its derived recursion limit; the semantic budgets should "
            "have fired first",
        )
    except GraphRecursionError:
        return _recursion_failure(job_state, "the graph runtime stopped the run at its recursion limit")


def _recursion_failure(job_state: RoutingJobState, message: str) -> RoutingJobState:
    # A partial terminal state, deliberately: the counters accumulated so far are
    # the diagnostic, and `total=False` makes every key optional.
    failed: RoutingJobState = dict(job_state)
    failed["failure"] = FailureInfo(
        code=RECURSION_LIMIT_EXCEEDED,
        message=message,
        retryable=False,
    )
    failed["status"] = "failed"
    return failed


def startup_banner(
    *,
    mode: ResolvedModelMode | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """The startup line: the resolved mode, never a secret.

    `GENLEDGE_MODEL_MODE=live` without provider configuration raises here, which is
    the documented behaviour; callers that must not fail at import time use
    `log_resolved_mode` instead.
    """

    resolved = mode or resolve_model_mode(env=env)
    return f"agent_runtime={graph_runtime()} {resolved.banner}"


def log_resolved_mode(*, env: Mapping[str, str] | None = None) -> str | None:
    """Log the resolved mode at startup without ever exposing a secret.

    Returns the banner, or `None` when live mode was requested without provider
    configuration. A missing configuration must surface on the job, not crash the
    process that merely imported the package.
    """

    try:
        banner = startup_banner(env=env)
    except ModelConfigurationError as error:
        logger.warning("agent model mode unresolved: %s", error.message)
        return None
    logger.info("%s", banner)
    return banner


def init_agent(app: Any = None) -> None:
    """Register the agent with a Flask app.

    Nothing is registered yet: the review endpoints belong to Person D and the
    persistence they read does not exist on this branch. The startup banner is
    emitted here so the resolved model mode is visible from process start.

    `app` is the documented interface (`app.extensions` will hold the compiled
    graph once persistence lands); it is deliberately unused today.
    """

    del app

    log_resolved_mode()


__all__ = [
    "DECLARED_CONDITIONAL_EDGES",
    "DECLARED_EDGES",
    "DECLARED_NODES",
    "GraphShape",
    "RoutingRunResult",
    "build_graph",
    "derived_recursion_limit",
    "graph_shape",
    "init_agent",
    "log_resolved_mode",
    "run_routing_job",
    "startup_banner",
]
