"""The three node functions and the routing predicates.

`context -> propose <-> tool_call -> END`, exactly as `plans/user-stories/US4.md`
§4.3 specifies. Each node reads the whole state, performs one unit of work, and
returns a partial update; the graph runtime merges it. Routers read only
`failure`, `pending_tool_calls` and the budget counters — never model text — so no
model output can choose a destination.

Node mechanics that are load-bearing rather than incidental:

* `propose` performs **one** model call per invocation. It never executes a tool.
* A malformed model answer gets **one** repair call, then `invalid_model_output`.
* `tool_call` clears `pending_tool_calls` and always returns to `propose`.
* The model budget is checked against the **durable** call count as well as the
  in-state counter, so a crash loop cannot re-spend the same budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agent import prompts as prompt_module
from app.agent import state as state_module
from app.agent.contracts import AgentBudgets, FailureInfo, InventoryView, ModelDraft, ToolResultRef
from app.agent.errors import (
    EMPTY_INVENTORY,
    MODEL_CALL_BUDGET_EXHAUSTED,
    TOOL_BUDGET_EXHAUSTED,
    AgentFailure,
    InvalidModelOutputError,
)
from app.agent.models import ModelClient, ModelRequest, ModelResponse, parse_model_draft
from app.agent.repositories import CatalogueView, RoutingRepository
from app.agent.state import RoutingJobState
from app.agent.tools import FakeConnector, ToolConnector, ToolDispatcher, ToolResult

CONTEXT = "context"
PROPOSE = "propose"
TOOL_CALL = "tool_call"

#: The status a successful run leaves behind. `plans/user-stories/US4.md` §4.2 has
#: `propose` write `status`; this is the terminal value it writes when the model
#: answers with a draft and the graph ends.
AWAITING_REVIEW = "awaiting_review"

NODE_NAMES: tuple[str, ...] = (CONTEXT, PROPOSE, TOOL_CALL)


@dataclass
class GraphRuntime:
    """Per-run dependencies. Not checkpointed, and never rendered into a prompt."""

    repository: RoutingRepository
    connector: ToolConnector = field(default_factory=FakeConnector)
    inventory: InventoryView | None = None
    catalogue: CatalogueView | None = None
    model: ModelClient | None = None
    dispatcher: ToolDispatcher | None = None
    tool_results: list[ToolResult] = field(default_factory=list)
    responses: list[ModelResponse] = field(default_factory=list)
    repairs_used: int = 0

    def last_response(self) -> ModelResponse | None:
        return self.responses[-1] if self.responses else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure_update(error: AgentFailure | FailureInfo) -> dict[str, Any]:
    failure = error.to_failure_info() if isinstance(error, AgentFailure) else error
    return {"failure": failure, "status": "failed", "updated_at": _now()}


def _budget_counter(state: RoutingJobState, runtime: GraphRuntime) -> int:
    """The model-call count that governs the budget: the durable record wins."""

    durable = runtime.repository.get_model_call_count(state.get("job_id", ""))
    return max(durable, state.get("model_calls_used", 0)) if durable else state.get("model_calls_used", 0)


# --- context -------------------------------------------------------------------


def context_node(state: RoutingJobState, runtime: GraphRuntime) -> dict[str, Any]:
    """Load the frozen inventory and the optional catalogue. No model call."""

    budgets = state["budgets"]
    snapshot_ids = list(state.get("source_snapshot_ids", []))
    if not snapshot_ids:
        return _failure_update(
            AgentFailure(EMPTY_INVENTORY, "the job names no source snapshot", retryable=False)
        )

    inventory: InventoryView | None = None
    for snapshot_id in snapshot_ids:
        inventory = runtime.repository.get_inventory(snapshot_id)
        if inventory is not None:
            break
    if inventory is None:
        return _failure_update(
            AgentFailure(EMPTY_INVENTORY, "the frozen snapshot has no inventory", retryable=False)
        )
    if not inventory.fields:
        return _failure_update(
            AgentFailure(
                EMPTY_INVENTORY,
                f"snapshot {inventory.snapshot_id} contains no discovered fields",
                retryable=False,
            )
        )

    catalogue = runtime.repository.get_catalogue(state.get("catalogue_ref"))
    runtime.inventory = inventory
    runtime.catalogue = catalogue
    runtime.dispatcher = ToolDispatcher(
        connector=runtime.connector,
        repository=runtime.repository,
        inventory=inventory,
        budgets=budgets,
    )
    return {
        "source_snapshot_ids": [inventory.snapshot_id],
        "inventory_ref": f"inventory:{inventory.snapshot_id}",
        "catalogue_ref": catalogue.catalog_ref if catalogue else None,
        "status": "running",
        "failure": None,
        "updated_at": _now(),
    }


# --- propose -------------------------------------------------------------------


def propose_node(state: RoutingJobState, runtime: GraphRuntime) -> dict[str, Any]:
    """One structured model call per invocation, with one repair attempt."""

    budgets = state["budgets"]
    inventory = runtime.inventory
    if inventory is None:
        return _failure_update(
            AgentFailure(EMPTY_INVENTORY, "context did not load an inventory", retryable=False)
        )

    used = _budget_counter(state, runtime)
    if used >= budgets.max_model_calls:
        return _failure_update(
            AgentFailure(
                MODEL_CALL_BUDGET_EXHAUSTED,
                f"model call budget exhausted ({budgets.max_model_calls})",
                retryable=False,
            )
        )
    if state.get("tokens_used", 0) >= budgets.max_tokens:
        return _failure_update(
            AgentFailure(
                MODEL_CALL_BUDGET_EXHAUSTED,
                f"token budget exhausted ({budgets.max_tokens})",
                retryable=False,
            )
        )

    model = runtime.model
    if model is None:
        return _failure_update(
            AgentFailure(MODEL_CALL_BUDGET_EXHAUSTED, "no model client was configured", retryable=False)
        )

    rendered = prompt_module.render_proposal_prompt(
        job_id=state.get("job_id", ""),
        inventory=inventory,
        catalogue=runtime.catalogue,
        tool_results=runtime.tool_results,
        budgets=budgets,
    )
    request = ModelRequest(
        node=PROPOSE,
        system=rendered.system,
        user=rendered.user,
        prompt_ref=rendered.ref,
        job_id=state.get("job_id", ""),
        results=tuple(runtime.tool_results),
    )
    response = model.invoke(request)
    runtime.responses.append(response)
    calls_used = state.get("model_calls_used", 0) + 1
    tokens_used = state.get("tokens_used", 0) + response.tokens

    if response.error_code:
        update = _failure_update(
            AgentFailure(response.error_code, response.error_message or response.error_code)
        )
        update.update(
            {
                "model_calls_used": calls_used,
                "tokens_used": tokens_used,
                "messages": _messages(rendered, response),
                "prompt_ref": rendered.ref,
            }
        )
        return update

    if response.tool_calls:
        # The tool budget is checked here, **before** dispatch, so exhaustion ends
        # the run with a typed failure instead of a repeated refusal (US4 §4.3).
        if state.get("tool_calls_used", 0) >= budgets.max_tool_calls:
            update = _failure_update(
                AgentFailure(
                    TOOL_BUDGET_EXHAUSTED,
                    f"tool call budget exhausted ({budgets.max_tool_calls})",
                    retryable=False,
                )
            )
        else:
            update = {
                "pending_tool_calls": list(response.tool_calls),
                "status": "running",
                "failure": None,
            }
        update.update(
            {
                "model_calls_used": calls_used,
                "tokens_used": tokens_used,
                "messages": _messages(rendered, response),
                "prompt_ref": rendered.ref,
                "updated_at": _now(),
            }
        )
        return update

    draft, error = parse_model_draft(response.text)
    if draft is None:
        repaired, repair_tokens, attempted = _attempt_repair(
            error or "invalid model output",
            runtime=runtime,
            state=state,
            calls_used=calls_used,
            max_model_calls=budgets.max_model_calls,
        )
        # A repair is charged as soon as it is attempted: the provider was called,
        # so the in-state counter and the durable count must both see it.
        if attempted:
            calls_used += 1
            tokens_used += repair_tokens
        if repaired is None:
            update = _failure_update(
                InvalidModelOutputError(
                    f"model output failed the contract after one repair attempt: {error}"
                )
            )
            update.update(
                {
                    "model_calls_used": calls_used,
                    "tokens_used": tokens_used,
                    "messages": _messages(rendered, response),
                    "prompt_ref": rendered.ref,
                }
            )
            return update
        draft = repaired

    revision = state.get("revision_count", 0) + 1
    accepted = draft.model_copy(update={"revision": revision})
    return {
        "model_draft": accepted,
        "pending_tool_calls": [],
        "revision_count": revision,
        "model_calls_used": calls_used,
        "tokens_used": tokens_used,
        "messages": _messages(rendered, response),
        "prompt_ref": rendered.ref,
        # `propose -> END`: the run is over, and a reviewable draft exists.
        "status": AWAITING_REVIEW,
        "failure": None,
        "updated_at": _now(),
    }


def _attempt_repair(
    errors: str,
    *,
    runtime: GraphRuntime,
    state: RoutingJobState,
    calls_used: int,
    max_model_calls: int,
) -> tuple[ModelDraft | None, int, bool]:
    """Exactly one repair call.

    Returns `(draft, tokens, attempted)`. `attempted` is `True` only when the
    provider was actually called, so the caller charges the budget exactly once and
    only for a call that happened.
    """

    if calls_used >= max_model_calls:
        return None, 0, False
    model = runtime.model
    if model is None:
        return None, 0, False
    rendered = prompt_module.render_repair_prompt(validation_errors=errors)
    request = ModelRequest(
        node=PROPOSE,
        system=rendered.system,
        user=rendered.user,
        prompt_ref=rendered.ref,
        job_id=state.get("job_id", ""),
        repair=True,
    )
    response = model.invoke(request)
    runtime.responses.append(response)
    runtime.repairs_used += 1
    if response.error_code or response.tool_calls:
        return None, response.tokens, True
    draft, _ = parse_model_draft(response.text)
    return draft, response.tokens, True


def _messages(rendered: prompt_module.RenderedPrompt, response: ModelResponse) -> list[dict[str, Any]]:
    """Step-scoped messages: provenance and outcome, never the whole prompt body."""

    return [
        {"role": "user", "prompt_ref": rendered.ref, "prompt_sha256": rendered.sha256},
        {
            "role": "assistant",
            "tool_calls": [call.id for call in response.tool_calls],
            "stop_reason": response.stop_reason,
        },
    ]


# --- tool_call -----------------------------------------------------------------


def tool_call_node(state: RoutingJobState, runtime: GraphRuntime) -> dict[str, Any]:
    """Authorize, budget, replay, dispatch, redact and persist each pending call."""

    dispatcher = runtime.dispatcher
    pending = list(state.get("pending_tool_calls", []))
    if dispatcher is None or not pending:
        return {"pending_tool_calls": [], "updated_at": _now()}

    used = state.get("tool_calls_used", 0)
    refs: list[ToolResultRef] = []
    for request in pending:
        outcome = dispatcher.dispatch(request, job_id=state.get("job_id", ""), tool_calls_used=used)
        if outcome.charged:
            used += 1
        if outcome.result.status == "ok":
            runtime.tool_results.append(outcome.result)
        refs.append(outcome.ref)

    return {
        "tool_results": refs,
        "tool_calls_used": used,
        "pending_tool_calls": [],
        "messages": [
            {"role": "tool", "tool_call_ids": [request.id for request in pending]},
        ],
        "updated_at": _now(),
    }


# --- routers -------------------------------------------------------------------


def route_after_context(state: RoutingJobState) -> str:
    """`context -> END` on an empty or unsupported inventory; else `propose`."""

    return "end" if state.get("failure") else "propose"


def route_after_propose(state: RoutingJobState) -> str:
    """`propose -> tool_call` when tools were requested; else END.

    Reads `pending_tool_calls` and `failure` only. The tool budget is enforced by
    `propose` (before it accepts the request), so a `tool_calls_used` at the bound
    never reaches here with pending calls.
    """

    if state.get("failure"):
        return "end"
    return "tool_call" if state.get("pending_tool_calls") else "end"


def budget_exhausted(budgets: AgentBudgets, state: RoutingJobState) -> str | None:
    """Re-exported from `state` so nodes and tests share one predicate."""

    return state_module.budget_exhausted(budgets, state)


__all__ = [
    "AWAITING_REVIEW",
    "CONTEXT",
    "GraphRuntime",
    "NODE_NAMES",
    "PROPOSE",
    "TOOL_CALL",
    "budget_exhausted",
    "context_node",
    "propose_node",
    "route_after_context",
    "route_after_propose",
    "tool_call_node",
]
