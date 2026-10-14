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
from typing import Annotated, Any, Literal, TypedDict

from app.agent.contracts import (
    AgentBudgets,
    FailureInfo,
    ModelDraft,
    ToolCallRequest,
    ToolResultRef,
)

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
    tokens_used: int
    failure: FailureInfo | None
    status: str | None
    updated_at: str | None

    # accumulated
    tool_results: Annotated[list[ToolResultRef], operator.add]
    messages: Annotated[list[Any], replace_messages]

    # provenance
    prompt_ref: str | None


#: Keys a node may return when it is acting for a given node name, mirroring
#: `plans/user-stories/US4.md` §4.2's "Writes" column. A node returning a key
#: outside its own list is a programming error, and `validate_node_update` turns
#: it into a typed `invalid_state_update` failure instead of a silent merge.
NODE_WRITES: dict[str, frozenset[str]] = {
    "context": frozenset(
        {"source_snapshot_ids", "inventory_ref", "catalogue_ref", "status", "failure", "updated_at"}
    ),
    "propose": frozenset(
        {
            "model_draft",
            "pending_tool_calls",
            "model_calls_used",
            "tokens_used",
            "messages",
            "prompt_ref",
            "status",
            "failure",
            "updated_at",
        }
    ),
    "tool_call": frozenset(
        {"tool_results", "tool_calls_used", "pending_tool_calls", "messages", "updated_at"}
    ),
}


def validate_node_update(node: str, update: dict[str, Any]) -> None:
    """Reject an update that writes a field its node does not own."""

    allowed = NODE_WRITES.get(node)
    if allowed is None:
        return
    unknown = set(update) - allowed
    if unknown:
        raise ValueError(
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
        tokens_used=0,
        failure=None,
        status="running",
        updated_at=None,
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
    runtime's own recursion limit.
    """

    if state.get("tool_calls_used", 0) >= budgets.max_tool_calls:
        return "tool_calls"
    if state.get("model_calls_used", 0) >= budgets.max_model_calls:
        return "model_calls"
    if state.get("tokens_used", 0) >= budgets.max_tokens:
        return "tokens"
    return None
