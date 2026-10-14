"""The routing graph state: one `TypedDict`, its reducers and its budget helpers.

`RoutingJobState` follows `plans/user-stories/US4.md` §4.4 with the additions
Person B's task split requires (`catalogue_ref`, `messages`, `prompt_ref`,
`model_mode`). It holds references and small outputs only:

* the inventory is referenced by `inventory_ref`, never inlined, so a checkpoint
  never grows with the source;
* `tool_results` holds refs, never payloads, so a payload cannot re-enter a prompt
  except through the projection in `app.agent.prompts`;
* `model_draft` is the only model-produced field.

Reducers are declared per field and are never implicit. `tool_results` appends;
`messages` is step-scoped and is replaced, not appended, so a tool result cannot
accumulate across steps or across tool-loop turns.
"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict

from app.agent.contracts import (
    AgentBudgets,
    FailureInfo,
    ModelDraft,
    ToolCallRequest,
    ToolResultRef,
)
from app.agent.errors import InvalidStateUpdateError

ACTIVE_STEP = Literal["propose"]


def replace_messages(current: list[Any] | None, update: list[Any] | None) -> list[Any]:
    """Reducer for `messages`: this field is replaced, never appended.

    A node that returns `messages` is stating the whole step-scoped conversation
    for the step it is entering. Returning `[]` clears it; omitting the key from the
    partial update leaves it untouched.
    """

    del current
    return list(update or [])


class RoutingJobState(TypedDict, total=False):
    """Minimal US4 graph state. Provisional and US4-only."""

    # identity, frozen by the runner before the first invoke
    job_id: str
    source_snapshot_ids: list[str]
    inventory_ref: str
    catalogue_ref: str | None
    budgets: AgentBudgets
    model_mode: Literal["fake", "live"]
    active_step: ACTIVE_STEP

    # control flow
    pending_tool_calls: list[ToolCallRequest]
    model_draft: ModelDraft | None
    revision_count: int
    model_calls_used: int
    tool_calls_used: int
    #: Rounds spent in `tool_call` since the model last did something else. A replayed
    #: call is not charged to `tool_calls_used` (it must stay idempotent), so without a
    #: round counter a model that keeps re-requesting one `tool_call_id` would loop
    #: until `max_model_calls` while `max_tool_calls` never fired.
    tool_rounds_used: int
    tokens_used: int
    failure: FailureInfo | None
    status: str | None
    started_at: str | None
    updated_at: str | None

    # accumulated
    tool_results: Annotated[list[ToolResultRef], operator.add]
    messages: Annotated[list[Any], replace_messages]

    # provenance
    prompt_ref: str | None


#: Keys a node may return when it is acting for a given node name, mirroring
#: `plans/user-stories/US4.md` §4.2's "Writes" column. `graphs.guarded` checks every
#: node update against its own list, so a node returning an undeclared key fails
#: loudly instead of merging a field the state design never accounted for.
NODE_WRITES: dict[str, frozenset[str]] = {
    "context": frozenset(
        {
            "source_snapshot_ids",
            "inventory_ref",
            "catalogue_ref",
            "status",
            "failure",
            # `context` fails the job before any model or tool work, so its failure
            # update closes the tool round the same way `propose`'s does.
            "tool_rounds_used",
            "updated_at",
        }
    ),
    "propose": frozenset(
        {
            "model_draft",
            "pending_tool_calls",
            "model_calls_used",
            "tokens_used",
            "revision_count",
            "messages",
            "prompt_ref",
            "status",
            "failure",
            "updated_at",
            # `propose` opens a new tool round when it accepts tool requests, and closes
            # the run's rounds when it accepts a draft.
            "tool_rounds_used",
        }
    ),
    "tool_call": frozenset(
        {
            "tool_results",
            "tool_calls_used",
            "tool_rounds_used",
            "pending_tool_calls",
            "messages",
            # A tool round that cannot proceed — the budget is spent, or the store
            # holding the results is unavailable — must be able to end the job with the
            # typed reason rather than reporting an empty round. `token_budget_exhausted`
            # and `cost_budget_exhausted` are the other two `_failure_update` codes
            # `tool_call` can produce, so the extra room is deliberate, not leftover.
            "failure",
            "status",
            "updated_at",
        }
    ),
}


def validate_node_update(node: str, update: dict[str, Any]) -> None:
    """Reject an update that writes a field its node does not own.

    Raises the **typed** `InvalidStateUpdateError`, not a bare `ValueError`: the
    runner maps it to `FailureInfo(code="invalid_state_update")`, which is what
    `plans/LANGGRAPH_HARNESS_PLAN.md` §9.1 row 2 specifies for a bad node write.
    An untyped exception here escapes `run_routing_job` and takes the job's typed
    failure record with it.
    """

    allowed = NODE_WRITES.get(node)
    if allowed is None:
        return
    unknown = set(update) - allowed
    if unknown:
        raise InvalidStateUpdateError(
            f"node {node!r} wrote undeclared state keys: {sorted(unknown)}"
        )


def initial_state(
    *,
    job_id: str,
    source_snapshot_ids: list[str],
    budgets: AgentBudgets,
    model_mode: Literal["fake", "live"],
    catalogue_ref: str | None = None,
    inventory_ref: str = "",
) -> RoutingJobState:
    """Build the state the runner hands to the first `invoke`.

    Frozen inputs are set here and only here: the runner owns them, not a node.
    """

    started = datetime.now(timezone.utc).isoformat()
    return RoutingJobState(
        job_id=job_id,
        source_snapshot_ids=list(source_snapshot_ids),
        inventory_ref=inventory_ref,
        catalogue_ref=catalogue_ref,
        budgets=budgets,
        model_mode=model_mode,
        active_step="propose",
        pending_tool_calls=[],
        model_draft=None,
        revision_count=0,
        model_calls_used=0,
        tool_calls_used=0,
        tool_rounds_used=0,
        tokens_used=0,
        failure=None,
        status="running",
        started_at=started,
        updated_at=started,
        tool_results=[],
        messages=[],
        prompt_ref=None,
    )


def remaining(budgets: AgentBudgets, state: RoutingJobState) -> dict[str, int]:
    """Report the head-room left on each semantic budget for this job."""

    return {
        "tool_calls": budgets.max_tool_calls - state.get("tool_calls_used", 0),
        "model_calls": budgets.max_model_calls - state.get("model_calls_used", 0),
        "tokens": budgets.max_tokens - state.get("tokens_used", 0),
    }


def budget_exhausted(budgets: AgentBudgets, state: RoutingJobState) -> str | None:
    """Return the first exhausted budget's name, or `None` when one remains.

    Checked *before* a dispatch or a model call, so exhaustion routes to `END`
    with a recorded failure rather than raising or being masked by the graph
    runtime's own recursion limit. Cost and wall clock are evaluated by the node
    from the recorded usage (`nodes._budget_stop`); this predicate covers the three
    that a state counter alone can answer.
    """

    if state.get("tool_calls_used", 0) >= budgets.max_tool_calls:
        return "tool_calls"
    if state.get("tool_rounds_used", 0) >= budgets.max_tool_calls:
        # Rounds, not only charged reads: a replayed call is free, so `tool_calls_used`
        # alone cannot bound a model that keeps re-requesting the same `tool_call_id`.
        return "tool_rounds"
    if state.get("model_calls_used", 0) >= budgets.max_model_calls:
        return "model_calls"
    if state.get("tokens_used", 0) >= budgets.max_tokens:
        return "tokens"
    return None


def accumulated_rounds(state: RoutingJobState) -> int:
    """The tool rounds the run has spent, for a failure update to report.

    A terminal update that wrote a zero here would hide the loop length from the
    operator: a model that re-requested one `tool_call_id` twenty times would leave
    `tool_calls_used=1` and no other trace of what happened.
    """

    return int(state.get("tool_rounds_used", 0) or 0)
