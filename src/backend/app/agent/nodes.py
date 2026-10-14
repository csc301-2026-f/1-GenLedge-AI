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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agent import prompts as prompt_module
from app.agent import state as state_module
from app.agent.contracts import AgentBudgets, FailureInfo, InventoryView, ModelDraft, ToolResultRef
from app.agent.errors import (
    CATALOGUE_NOT_FOUND,
    COST_BUDGET_EXHAUSTED,
    EMPTY_INVENTORY,
    MODEL_CALL_BUDGET_EXHAUSTED,
    MODEL_CONFIGURATION_ERROR,
    MODEL_UNAVAILABLE,
    PROMPT_RENDER_FAILED,
    REPOSITORY_UNAVAILABLE,
    TOKEN_BUDGET_EXHAUSTED,
    TOOL_BUDGET_EXHAUSTED,
    WALL_CLOCK_BUDGET_EXHAUSTED,
    AgentFailure,
    InvalidModelOutputError,
)
from app.agent.models import ModelClient, ModelRequest, ModelResponse, parse_model_draft
from app.agent.repositories import CatalogueView, RoutingRepository
from app.agent.state import RoutingJobState
from app.agent.tools import (
    STORAGE_FAILED,
    FakeConnector,
    ToolConnector,
    ToolDispatcher,
    ToolResult,
    tool_schemas,
)

CONTEXT = "context"
PROPOSE = "propose"
TOOL_CALL = "tool_call"

#: The status a successful run leaves behind. `plans/user-stories/US4.md` §4.2 has
#: `propose` write `status`; this is the terminal value it writes when the model
#: answers with a draft and the graph ends.
AWAITING_REVIEW = "awaiting_review"

#: How many result references stay on the state. The store keeps every row, so this
#: bounds checkpoint growth without losing the audit trail; the prompt projection caps
#: what it reads at `prompts.MAX_PROJECTED_TOOL_RESULTS` regardless.
MAX_RETAINED_TOOL_RESULTS = 20

NODE_NAMES: tuple[str, ...] = (CONTEXT, PROPOSE, TOOL_CALL)

logger = logging.getLogger(__name__)


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
    #: Price used to evaluate `AgentBudgets.max_cost_usd`. `None` means the ceiling
    #: cannot be evaluated, and the run says so rather than guessing a price.
    cost_per_1k_tokens_usd: float | None = None

    def last_response(self) -> ModelResponse | None:
        return self.responses[-1] if self.responses else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure_update(
    error: AgentFailure | FailureInfo, state: RoutingJobState | None = None
) -> dict[str, Any]:
    """A terminal update: the failure, the status, and the rounds the run spent.

    `tool_rounds_used` is written by every failure because it is a declared write of both
    `propose` and `tool_call`, and leaving it out of one branch is exactly the drift the
    node-write guard exists to catch. It carries the **accumulated** value, not zero: a
    zeroed counter hides how long the loop actually ran, which is the one diagnostic a
    budget failure has to offer.
    """

    failure = error.to_failure_info() if isinstance(error, AgentFailure) else error
    rounds = state_module.accumulated_rounds(state) if state is not None else 0
    return {
        "failure": failure,
        "status": "failed",
        "tool_rounds_used": rounds,
        "updated_at": _now(),
    }


def _budget_counter(state: RoutingJobState, runtime: GraphRuntime) -> int:
    """The model-call count that governs the budget: the durable record wins.

    A control-store fault is a typed failure, not an escaping exception — the same
    rule `context` applies to its reads. `AgentFailure` is raised and caught by the
    callers, which are all inside a node.
    """

    try:
        durable = runtime.repository.get_model_call_count(state.get("job_id", ""))
    except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
        raise AgentFailure(
            REPOSITORY_UNAVAILABLE,
            f"the durable model-call count could not be read: {type(error).__name__}: {error}",
            retryable=True,
        ) from error
    return max(durable, state.get("model_calls_used", 0)) if durable else state.get("model_calls_used", 0)


def _record_model_call(runtime: GraphRuntime, state: RoutingJobState, response: ModelResponse | None) -> None:
    """Record one provider call durably. Best effort, but never silently skipped.

    The durable row count is the model budget's authority (`repositories.py`), so a
    call that happened must be recorded even when the adapter raised: an unrecorded
    call is a call a crash loop can spend again.
    """

    try:
        runtime.repository.record_model_call(
            state.get("job_id", ""), node=PROPOSE, tokens=response.tokens if response else 0
        )
    except Exception as error:  # noqa: BLE001 - the call happened; the record is best effort
        logger.warning("could not record the model call for %s: %s", state.get("job_id"), error)


# --- context -------------------------------------------------------------------


def context_node(state: RoutingJobState, *, runtime: GraphRuntime) -> dict[str, Any]:
    """Load the frozen inventory and the optional catalogue. No model call."""

    budgets = state["budgets"]
    snapshot_ids = list(state.get("source_snapshot_ids", []))
    if not snapshot_ids:
        return _failure_update(
            AgentFailure(EMPTY_INVENTORY, "the job names no source snapshot", retryable=False)
        )

    # A repository fault is a typed failure, not an escaping exception: master §9.1
    # row 20 wants "node fails; job failed" for a persistence outage, and a traceback
    # out of `run_routing_job` is not that.
    try:
        inventory: InventoryView | None = None
        for snapshot_id in snapshot_ids:
            inventory = runtime.repository.get_inventory(snapshot_id)
            if inventory is not None:
                break
    except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
        return _failure_update(
            AgentFailure(
                REPOSITORY_UNAVAILABLE,
                f"the inventory could not be read: {type(error).__name__}: {error}",
                retryable=True,
            )
        )
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

    # An unresolvable `catalog_ref` is a typed failure, not a silent downgrade: a
    # reviewer who asked for reuse must not be handed a cold-start proposal with no
    # signal that AC3's semantics flipped.
    requested_catalogue = state.get("catalogue_ref")
    try:
        catalogue = runtime.repository.get_catalogue(requested_catalogue)
    except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
        return _failure_update(
            AgentFailure(
                REPOSITORY_UNAVAILABLE,
                f"the catalogue could not be read: {type(error).__name__}: {error}",
                retryable=True,
            )
        )
    if requested_catalogue and catalogue is None:
        return _failure_update(
            AgentFailure(
                CATALOGUE_NOT_FOUND,
                f"catalogue {requested_catalogue!r} was not found for this job",
                retryable=False,
            )
        )
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


def _budget_stop(state: RoutingJobState, runtime: GraphRuntime, budgets: AgentBudgets) -> FailureInfo | None:
    """The first exhausted budget, as a typed failure, or `None` when one remains.

    Every budget here is checked **before** the work it bounds, so exhaustion is a
    recorded outcome rather than a framework error or an overspend.
    """

    used = _budget_counter(state, runtime)
    if used >= budgets.max_model_calls:
        return FailureInfo(
            code=MODEL_CALL_BUDGET_EXHAUSTED,
            message=f"model call budget exhausted ({budgets.max_model_calls})",
            retryable=False,
        )
    if state.get("tokens_used", 0) >= budgets.max_tokens:
        return FailureInfo(
            code=TOKEN_BUDGET_EXHAUSTED,
            message=f"token budget exhausted ({budgets.max_tokens})",
            retryable=False,
        )
    elapsed = _elapsed_seconds(state)
    if elapsed is not None and elapsed >= budgets.max_wall_clock_seconds:
        return FailureInfo(
            code=WALL_CLOCK_BUDGET_EXHAUSTED,
            message=f"wall clock budget exhausted ({budgets.max_wall_clock_seconds}s)",
            retryable=False,
        )
    spent = _estimated_cost_usd(state, runtime)
    if spent is not None and spent >= budgets.max_cost_usd:
        return FailureInfo(
            code=COST_BUDGET_EXHAUSTED,
            message=f"cost budget exhausted (${spent:.4f} of ${budgets.max_cost_usd})",
            retryable=False,
        )
    return None


def _elapsed_seconds(state: RoutingJobState) -> float | None:
    """Seconds since the run's start marker, or `None` when it is not recorded."""

    started = _started_at(state)
    if started is None:
        return None
    return (datetime.now(timezone.utc) - started).total_seconds()


def _started_at(state: RoutingJobState) -> datetime | None:
    raw = state.get("started_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _estimated_cost_usd(state: RoutingJobState, runtime: GraphRuntime) -> float | None:
    """Cost from the recorded token count and the configured price, if any.

    Cost is computed at read time from a price table rather than stored, so a price
    change does not rewrite history (master §8.2). With no configured price the
    ceiling cannot be evaluated and `None` says so instead of guessing.
    """

    price = runtime.cost_per_1k_tokens_usd
    if price is None:
        return None
    return (state.get("tokens_used", 0) / 1000.0) * price


def propose_node(state: RoutingJobState, *, runtime: GraphRuntime) -> dict[str, Any]:
    """One structured model call per invocation, with one repair attempt.

    Every storage read this node performs is wrapped: a control-store fault becomes a
    typed `repository_unavailable` failure, never a traceback out of
    `run_routing_job` (`nodes.context_node` applies the same rule to its reads).
    """

    try:
        return _propose(state, runtime=runtime)
    except AgentFailure as error:
        return _failure_update(error, state)
    except Exception as error:  # noqa: BLE001 - the node boundary owns typed failures
        return _failure_update(
            AgentFailure(
                REPOSITORY_UNAVAILABLE,
                f"propose failed on a {type(error).__name__}: {error}",
                retryable=True,
            ),
            state,
        )


def _propose(state: RoutingJobState, *, runtime: GraphRuntime) -> dict[str, Any]:
    budgets = state["budgets"]

    # `tool_call -> propose` is an unconditional edge, so `propose` runs even when the
    # round it just left failed terminally. A recorded failure is final: re-deciding it
    # here used to clear the failure (and reset the tool-round counter), which re-armed
    # the loop and made `max_tool_calls` unable to stop a model that kept re-requesting
    # one `tool_call_id`.
    existing = state.get("failure")
    if existing is not None:
        return _failure_update(existing, state)

    inventory = runtime.inventory
    if inventory is None:
        return _failure_update(
            AgentFailure(EMPTY_INVENTORY, "context did not load an inventory", retryable=False),
            state,
        )

    stop = _budget_stop(state, runtime, budgets)
    if stop is not None:
        return _failure_update(stop, state)

    model = runtime.model
    if model is None:
        return _failure_update(
            AgentFailure(
                MODEL_CONFIGURATION_ERROR,
                "no model client was configured for this run",
                retryable=False,
            ),
            state,
        )

    try:
        rendered = prompt_module.render_proposal_prompt(
            job_id=state.get("job_id", ""),
            inventory=inventory,
            catalogue=runtime.catalogue,
            tool_results=runtime.tool_results,
            budgets=budgets,
        )
    except prompt_module.PromptError as error:
        # A rendering fault is a typed job failure. It must never escape the graph.
        return _failure_update(
            AgentFailure(PROMPT_RENDER_FAILED, f"prompt rendering failed: {error}", retryable=False),
            state,
        )
    request = ModelRequest(
        node=PROPOSE,
        system=rendered.system,
        user=rendered.user,
        prompt_ref=rendered.ref,
        job_id=state.get("job_id", ""),
        # Tools are bound so a live provider can request one. Without this the tool
        # loop is unreachable outside the fake adapter.
        tools=tool_schemas(),
        results=tuple(runtime.tool_results),
    )
    # An adapter that raises is a typed failure, not an escaping exception. `LiveModel`
    # returns typed error codes rather than raising, but a `ModelClient` is an
    # interface: a second implementation, or a bug in the first, must not take the job
    # down with a traceback (master §9.1 rows 4–7).
    try:
        response = model.invoke(request)
    except Exception as error:  # noqa: BLE001 - an adapter fault is data, not a crash
        failure = AgentFailure(
            MODEL_UNAVAILABLE,
            f"the model adapter raised {type(error).__name__}: {error}",
            retryable=True,
        )
        # The provider was called, even though it raised. Recording it durably is what
        # keeps the budget authority honest across a crash: an unrecorded call is a call
        # a crash loop can spend again, which is the opposite of what the module claims.
        _record_model_call(runtime, state, None)
        update = _failure_update(failure, state)
        update.update(
            {
                "model_calls_used": _budget_counter(state, runtime),
                "messages": _messages(rendered, ModelResponse(error_code=failure.code)),
                "prompt_ref": rendered.ref,
            }
        )
        return update
    runtime.responses.append(response)
    _record_model_call(runtime, state, response)
    calls_used = _budget_counter(state, runtime)
    tokens_used = state.get("tokens_used", 0) + response.tokens

    if response.error_code:
        update = _failure_update(
            AgentFailure(response.error_code, response.error_message or response.error_code),
            state,
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
                ),
                state,
            )
        else:
            update = {
                "pending_tool_calls": list(response.tool_calls),
                # A new tool round begins; `tool_call` increments and bounds the total.
                "tool_rounds_used": state.get("tool_rounds_used", 0),
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

    draft, contract_error = parse_model_draft(response.text)
    if draft is None:
        repaired, repair_tokens, attempted = _attempt_repair(
            contract_error or "invalid model output",
            previous_response=response.text,
            runtime=runtime,
            state=state,
            calls_used=calls_used,
            budgets=budgets,
        )
        # A repair is charged as soon as it is attempted: the provider was called,
        # so the in-state counter and the durable count must both see it.
        if attempted:
            calls_used = _budget_counter(state, runtime)
            tokens_used += repair_tokens
        if repaired is None:
            after = " after one repair attempt" if attempted else " (no repair was attempted)"
            update = _failure_update(
                InvalidModelOutputError(f"model output failed the contract{after}: {contract_error}"),
                state,
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
        # The draft ends the run, so the round counter is closed here.
        "tool_rounds_used": 0,
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
    previous_response: str,
    runtime: GraphRuntime,
    state: RoutingJobState,
    calls_used: int,
    budgets: AgentBudgets,
) -> tuple[ModelDraft | None, int, bool]:
    """Exactly one repair call, carrying the same evidence as the proposal call.

    Returns `(draft, tokens, attempted)`. `attempted` is `True` only when the
    provider was actually called, so the caller charges the budget exactly once and
    only for a call that happened.
    """

    if calls_used >= budgets.max_model_calls:
        return None, 0, False
    model = runtime.model
    inventory = runtime.inventory
    if model is None or inventory is None:
        return None, 0, False
    try:
        rendered = prompt_module.render_repair_prompt(
            validation_errors=errors,
            previous_response=previous_response,
            job_id=state.get("job_id", ""),
            inventory=inventory,
            catalogue=runtime.catalogue,
            tool_results=runtime.tool_results,
            budgets=budgets,
        )
    except prompt_module.PromptError:
        return None, 0, False
    request = ModelRequest(
        node=PROPOSE,
        system=rendered.system,
        user=rendered.user,
        prompt_ref=rendered.ref,
        job_id=state.get("job_id", ""),
        tools=tool_schemas(),
        repair=True,
        results=tuple(runtime.tool_results),
    )
    try:
        response = model.invoke(request)
    except Exception as error:  # noqa: BLE001 - an adapter fault is data, not a crash
        # The provider was called. Reporting `attempted=False` here told the reviewer
        # "no repair was attempted" while two requests had gone out, and left the call
        # out of the durable count.
        logger.warning("the repair call for %s raised: %s", state.get("job_id"), error)
        _record_model_call(runtime, state, None)
        runtime.repairs_used += 1
        return None, 0, True
    runtime.responses.append(response)
    _record_model_call(runtime, state, response)
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


def _tool_call_failure(error: AgentFailure | FailureInfo, state: RoutingJobState) -> dict[str, Any]:
    """A terminal `tool_call` update that also closes the pending round.

    Clearing `pending_tool_calls` is load-bearing, not tidiness. The routers decide from
    state, and `route_after_propose` sends the run back to `tool_call` whenever
    `pending_tool_calls` is non-empty — so a failure that left the requests in place was
    re-routed into another round, the round counter was reset by the next `propose`, and
    the tool budget never actually stopped the loop (it just failed four rounds and
    restarted).
    """

    update = _failure_update(error, state)
    update["pending_tool_calls"] = []
    return update


def tool_call_node(state: RoutingJobState, *, runtime: GraphRuntime) -> dict[str, Any]:
    """Authorize, budget, replay, dispatch, redact and persist each pending call.

    The step contract is `US4.md` §4.2. Two properties are load-bearing here:

    * **the tool budget is enforced on rounds, not only on connector reads.** A model
      that keeps re-requesting a `tool_call_id` it already used gets a free replay,
      which would leave `max_tool_calls` unable to stop a loop at all; charging the
      round makes the configured budget the bound it claims to be, while a genuine
      *retry* of the same call still replays its recorded result and returns it.
    * **a storage fault is a typed failure, not a traceback.** Every repository
      interaction goes through the dispatcher or a guard, so a control-store outage
      ends the job as `repository_unavailable` instead of escaping the graph.
    """

    dispatcher = runtime.dispatcher
    pending = list(state.get("pending_tool_calls", []))
    if dispatcher is None or not pending:
        return {"pending_tool_calls": [], "updated_at": _now()}

    used = state.get("tool_calls_used", 0)
    rounds = state.get("tool_rounds_used", 0) + 1
    if rounds > state["budgets"].max_tool_calls:
        # Charged connector reads are not the only thing `max_tool_calls` bounds: a
        # replayed call is free, so a model that keeps re-requesting the same
        # `tool_call_id` would otherwise loop until `max_model_calls` while the tool
        # budget never fired. The round is the bound.
        return _tool_call_failure(
            AgentFailure(
                TOOL_BUDGET_EXHAUSTED,
                f"tool call budget exhausted ({state['budgets'].max_tool_calls}); "
                "the run spent its tool rounds without producing a proposal",
                retryable=False,
            ),
            state,
        )
    if used >= state["budgets"].max_tool_calls:
        # Every remaining read is over budget: no dispatch, no partial batch.
        return _tool_call_failure(
            AgentFailure(
                TOOL_BUDGET_EXHAUSTED,
                f"tool call budget exhausted ({state['budgets'].max_tool_calls})",
                retryable=False,
            ),
            state,
        )

    refs: list[ToolResultRef] = []
    seen_call_ids: set[str] = set()
    #: Refs already on the state. Within one run the reducer is `operator.add`, so a
    #: replayed call must not append a second copy; a re-run against a warm store starts
    #: with an empty list, and there the recorded result *is* the evidence the prompt needs.
    seen_refs = {ref.result_ref for ref in state.get("tool_results", [])}
    try:
        for request in pending:
            outcome = dispatcher.dispatch(
                request,
                job_id=state.get("job_id", ""),
                # `used` is the count of *charged* calls so far, and it advances inside this
                # loop. Passing an index instead counted refused requests as if they had
                # spent budget, so a batch whose first entry was refused pre-dispatch got
                # its second, valid entry refused with `budget_exhausted` while nothing had
                # reached the connector.
                tool_calls_used=used,
                seen_call_ids=seen_call_ids,
            )
            if outcome.charged:
                used += 1
            if outcome.result.error_code == STORAGE_FAILED:
                # The result could not be recorded, so there is no evidence row and no
                # replay key. Continuing would build a proposal on a tool call the
                # system cannot account for.
                return _tool_call_failure(
                    AgentFailure(REPOSITORY_UNAVAILABLE, outcome.result.message or "storage failed",
                                 retryable=True),
                    state,
                )
            if outcome.replayed and outcome.ref.result_ref in seen_refs:
                # The ref is already on this state, so `operator.add` must not see it twice.
                # The *payload* still has to be reachable: the prompt projects the last
                # `MAX_PROJECTED_TOOL_RESULTS` results, so an older replay dropped entirely
                # would be invisible, the model would re-ask, and the run would die on a
                # budget instead of using evidence it had already fetched. Moving it to the
                # end keeps both properties.
                runtime.tool_results = [
                    item for item in runtime.tool_results if item.result_ref != outcome.ref.result_ref
                ] + [outcome.result]
                continue
            # Errors are kept too: they are the typed data the model has to adapt to, and
            # the projection is where they become prompt text. So are replays whose ref is
            # not on this state yet — dropping them made the prompt say "No tool results
            # recorded yet", the model re-asked for the same call, and a resumed job died
            # on the model budget instead of using the evidence it had just fetched.
            runtime.tool_results.append(outcome.result)
            refs.append(outcome.ref)
            seen_refs.add(outcome.ref.result_ref)
    except AgentFailure as error:
        return _tool_call_failure(error, state)
    except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
        return _tool_call_failure(
            AgentFailure(
                REPOSITORY_UNAVAILABLE,
                f"tool dispatch failed on a {type(error).__name__}: {error}",
                retryable=True,
            ),
            state,
        )

    return {
        "tool_results": refs[-MAX_RETAINED_TOOL_RESULTS:],
        "tool_calls_used": used,
        "tool_rounds_used": rounds,
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
