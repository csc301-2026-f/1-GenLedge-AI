"""Regression tests for the confirmed defects of the US4 harness rework.

Each test is named after the defect it pins (`A1`–`E3`, the ids of the review that
found them) and every one of them **fails if its fix is reverted**:

* `A` — a control-store fault must be a typed `repository_unavailable` failure, never
  a traceback out of a node or out of `run_routing_job`, and a tool result that could
  not be written must never be reported as a successful execution.
* `B` — the replay identity is the harness's `(job_id, tool_call_id)` **plus** the
  recorded tool name and arguments, and `max_tool_calls` bounds the *loop* (rounds),
  not only the charged connector reads.
* `C` — one sentinel per redaction category of
  `plans/us4-four-person-task-split.md` line 184 ("email, phone, address,
  identifiers, credential-like values, and unknown sensitive fields"), asserted both
  on the redaction helpers and on the text that reaches a provider.
* `D` — the node-write guard raises the typed `invalid_state_update`, and every key a
  failure path writes is declared, so a typed failure cannot trip the guard.
* `E` — a provider call that happened is recorded durably, a repair that raises is
  still charged, and `max_model_calls` is a hard cap checked before the call.
* `I` — the five findings of the follow-up PR review: connector exception text is
  redacted before it is persisted, an unsupported live provider is refused, an
  unrecordable model call ends the run, both node timeouts are enforced at the seam
  that owns them, and a prompt digest does not depend on the checkout's line endings.

Everything here is deterministic and offline: repositories are the in-memory doubles
of `app.agent.repositories`, models are local stubs, and no test touches a provider.
"""

from __future__ import annotations

import logging
import threading
import time
from time import monotonic
from typing import Any, cast

import pytest

from app.agent import tools as tools_module
from app.agent.contracts import AgentBudgets, ToolCallRequest
from app.agent.deadlines import (
    model_node_timeout_seconds,
    tool_call_timeout_seconds,
)
from app.agent.errors import (
    EMPTY_INVENTORY,
    INVALID_MODEL_OUTPUT,
    INVALID_STATE_UPDATE,
    MODEL_CALL_BUDGET_EXHAUSTED,
    MODEL_UNAVAILABLE,
    REPOSITORY_UNAVAILABLE,
    TOOL_BUDGET_EXHAUSTED,
    AgentFailure,
    InvalidStateUpdateError,
)
from app.agent.graph import run_routing_job
from app.agent.models import (
    ModelRequest,
    ModelResponse,
    build_fake_draft,
    derived_model_timeout_seconds,
)
from app.agent.nodes import (
    CONTEXT,
    PROPOSE,
    TOOL_CALL,
    GraphRuntime,
    _failure_update,
    _tool_call_failure,
    context_node,
    tool_call_node,
)
from app.agent.prompts import project_tool_results
from app.agent.repositories import (
    SNAPSHOT_ID,
    InMemoryRoutingRepository,
    empty_inventory_repository,
    seeded_repository,
)
from app.agent.state import NODE_WRITES, RoutingJobState, validate_node_update
from app.agent.tools import (
    BUDGET_EXHAUSTED,
    CONNECTOR_ERROR,
    CONNECTOR_ERROR_MESSAGES,
    CONNECTOR_TIMEOUT,
    CONNECTOR_TIMEOUT_MESSAGE,
    DECLARED_ERROR_CODES,
    INVALID_ARGUMENTS,
    INVALID_TOOL_REQUEST,
    REDACTION_MARKER,
    REPLAY_MISMATCH,
    RESOURCE_NOT_FOUND,
    SNAPSHOT_DRIFTED,
    STORAGE_FAILED,
    UNAUTHORIZED_SOURCE,
    UNDECLARED_FIELD_MARKER,
    UNSUPPORTED,
    ConnectorError,
    FakeConnector,
    ToolDispatcher,
    ToolResult,
    redact_message,
    redact_payload,
    redact_value,
)

from .doubles import ScriptedModel, inventory

SOURCE_ID = "source-orders-1"

#: The one call id the sticky model re-requests forever. Model-authored, so the
#: harness — not the model — decides what a repeat of it means.
STICKY_CALL_ID = "sticky-1"


def _call(tool_call_id: str = "regression-1", *, limit: int = 3) -> ToolCallRequest:
    return ToolCallRequest(
        id=tool_call_id,
        name="sample_rows",
        arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": limit},
    )


def _describe_call(tool_call_id: str) -> ToolCallRequest:
    return ToolCallRequest(
        id=tool_call_id,
        name="describe_resource",
        arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]"},
    )


def _dispatcher(repository, connector, **budget_overrides) -> ToolDispatcher:
    return ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
        budgets=AgentBudgets(**budget_overrides),
    )


class _FaultyRepository(InMemoryRoutingRepository):
    """The in-memory double with exactly one method replaced by a control-store fault.

    Built from `seeded_repository().inventories`, so the graph reaches the fault
    instead of failing earlier for a missing snapshot.
    """

    def __init__(self, fault: str) -> None:
        super().__init__(inventories=seeded_repository().inventories)
        self.fault = fault

    def _raise_if(self, method: str) -> None:
        if self.fault == method:
            raise RuntimeError(f"the control store is down: {method}")

    def record_tool_result(self, result: ToolResult):
        self._raise_if("record_tool_result")
        return super().record_tool_result(result)

    def get_tool_result(self, job_id: str, tool_call_id: str):
        self._raise_if("get_tool_result")
        return super().get_tool_result(job_id, tool_call_id)

    def get_model_call_count(self, job_id: str) -> int:
        self._raise_if("get_model_call_count")
        return super().get_model_call_count(job_id)


def _node_runtime(repository, **budget_overrides) -> tuple[GraphRuntime, FakeConnector]:
    """A graph runtime whose dispatcher writes to `repository`."""

    connector = FakeConnector()
    runtime = GraphRuntime(
        repository=repository,
        connector=connector,
        dispatcher=_dispatcher(repository, connector, **budget_overrides),
    )
    return runtime, connector


def _tool_call_state(
    job_id: str,
    *pending: ToolCallRequest,
    budgets: AgentBudgets | None = None,
) -> RoutingJobState:
    frozen = budgets or AgentBudgets(max_tool_calls=5, max_model_calls=5)
    return cast(
        "RoutingJobState",
        {
            "job_id": job_id,
            "budgets": frozen,
            "tool_calls_used": 0,
            "tool_rounds_used": 0,
            "tool_results": [],
            "pending_tool_calls": list(pending),
        },
    )


class _StickyToolCallModel:
    """A model that never varies its request: one constant `tool_call_id`, forever.

    A cooperating model stops before the budget matters, so the loop bound is only
    observable against a deliberately non-cooperative double. `draft_after` makes it
    answer with a valid draft once the tool budget should already have stopped it,
    which is how a wrongly-cleared failure would be masked into a success.
    """

    name = "sticky-tool-call"

    def __init__(self, *, draft_after: int | None = None) -> None:
        self.draft_after = draft_after
        self.requests: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.draft_after is not None and len(self.requests) > self.draft_after:
            return ModelResponse(text=build_fake_draft(inventory(), None, None).model_dump_json())
        return ModelResponse(
            tool_calls=[
                ToolCallRequest(
                    id=STICKY_CALL_ID,
                    name="sample_rows",
                    arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": 3},
                )
            ],
            input_tokens=1,
            output_tokens=1,
            stop_reason="tool_use",
        )

    @property
    def calls(self) -> int:
        return len(self.requests)


# --- A. typed storage failures (B2/B3) ------------------------------------------


def test_a1_a_failing_tool_result_write_is_a_typed_repository_failure():
    """`record_tool_result` raising must end the round typed, not escape the node."""

    repository = _FaultyRepository("record_tool_result")
    runtime, connector = _node_runtime(repository)
    state = _tool_call_state("job-a1", _call())

    update = tool_call_node(state, runtime=runtime)

    assert update["failure"].code == REPOSITORY_UNAVAILABLE
    assert update["failure"].retryable is True
    assert update["status"] == "failed"
    assert update["pending_tool_calls"] == [], "a failed round must not be re-routed"
    # the read reached the source; only the durable record failed
    assert connector.calls, "the connector was reached before the write failed"
    assert repository.get_tool_result("job-a1", "regression-1") is None


def test_a2_a_failing_tool_result_read_is_a_typed_repository_failure():
    """The replay lookup is a store read too: it must not raise out of the node."""

    repository = _FaultyRepository("get_tool_result")
    runtime, connector = _node_runtime(repository)
    state = _tool_call_state("job-a2", _call())

    update = tool_call_node(state, runtime=runtime)

    assert update["failure"].code == REPOSITORY_UNAVAILABLE
    assert update["failure"].retryable is True
    assert update["status"] == "failed"
    assert update["pending_tool_calls"] == []
    assert connector.calls == [], "the replay lookup failed before any dispatch"


def test_a3_a_failing_model_call_count_read_fails_the_job_with_a_typed_code():
    """The whole run must record `repository_unavailable`, not raise a traceback."""

    model = ScriptedModel([])
    run = run_routing_job(
        job_id="job-a3",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=_FaultyRepository("get_model_call_count"),
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == REPOSITORY_UNAVAILABLE
    assert run.failure.retryable is True
    assert run.status == "failed"
    assert run.model_draft is None
    # the durable count is the budget's authority, so it is read *before* the call
    assert model.calls == 0, "no provider call is made when the budget cannot be read"


class _UndeclaredFieldConnector:
    """A connector that answers with a field the harness never declared."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def call(self, name: str, arguments: dict[str, Any], job_id: str) -> dict[str, Any]:
        self.calls.append((name, dict(arguments), job_id))
        return {
            "resource_id": arguments.get("resource_id", ""),
            "sampling": "head",
            "rows": [],
            "undeclared_extra": 1,
        }


@pytest.mark.parametrize("connector_kind", ["ok", "undeclared_field"])
def test_a4_a_failed_write_is_not_reported_as_a_successful_tool_execution(connector_kind):
    """A read that could not be recorded has no evidence row, so it is not a success.

    Both a clean answer and an out-of-contract one go through the same guarded write.
    Reporting `ok` for either would publish an unpersisted result — and a later retry
    would have no replay key to observe it with.
    """

    repository = _FaultyRepository("record_tool_result")
    connector = FakeConnector() if connector_kind == "ok" else _UndeclaredFieldConnector()
    dispatcher = _dispatcher(repository, connector)

    outcome = dispatcher.dispatch(_call("a4-1"), job_id="job-a4", tool_calls_used=0)

    assert connector.calls, "the connector was reached"
    assert outcome.result.status != "ok", "an unpersisted result is not a success"
    assert outcome.result.error_code == STORAGE_FAILED
    assert outcome.result.payload == {}
    # the read happened, so the attempt is charged -- otherwise a store that fails
    # every write makes the loop free
    assert outcome.charged is True
    assert repository.tool_results == {}, "nothing was recorded"
    assert repository.get_tool_result("job-a4", "a4-1") is None


# --- B. harness-owned replay identity and tool budget (M1) ----------------------


def test_b1_a_reused_tool_call_id_inside_one_batch_is_refused():
    """The id is model-authored: a repeat inside one batch is not a replay.

    Answering the second request from the first's recorded payload would hand the
    model data for a call it did not make.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=5)
    seen_call_ids: set[str] = set()

    first = dispatcher.dispatch(
        _call("batch-1", limit=3), job_id="job-b1", tool_calls_used=0, seen_call_ids=seen_call_ids
    )
    second = dispatcher.dispatch(
        _call("batch-1", limit=7), job_id="job-b1", tool_calls_used=1, seen_call_ids=seen_call_ids
    )

    assert first.result.status == "ok"
    assert second.result.status == "error"
    assert second.result.error_code == INVALID_TOOL_REQUEST
    assert second.replayed is False
    assert second.charged is False
    assert second.result.payload == {}, "the second request must not receive the first's payload"
    assert second.result.payload != first.result.payload
    assert len(connector.calls) == 1, "the connector must be called at most once"
    # a whole-batch refusal records nothing partial
    assert repository.get_tool_result("job-b1", "batch-1") == first.result


def test_b2_a_replay_with_a_different_tool_name_is_refused():
    """The same `(job_id, tool_call_id)` naming another tool is not a retry."""

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=5)

    first = dispatcher.dispatch(_call("b2-1"), job_id="job-b2", tool_calls_used=0)
    second = dispatcher.dispatch(_describe_call("b2-1"), job_id="job-b2", tool_calls_used=1)

    assert first.result.status == "ok"
    assert first.result.tool == "sample_rows"
    assert second.result.status == "error"
    assert second.result.error_code == REPLAY_MISMATCH
    assert second.replayed is False
    assert second.charged is False
    assert second.result.payload == {}, "the first tool's payload must not be served"
    assert "SKU-1" not in str(second.result.payload)
    assert len(connector.calls) == 1


def test_b3_a_replay_with_different_arguments_is_refused_under_the_same_id():
    """Same tool, different arguments is a different call, not a retry of the first."""

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=5)

    first = dispatcher.dispatch(_call("b3-1", limit=3), job_id="job-b3", tool_calls_used=0)
    second = dispatcher.dispatch(_call("b3-1", limit=7), job_id="job-b3", tool_calls_used=1)

    assert first.result.status == "ok"
    assert second.result.status == "error"
    assert second.result.error_code == REPLAY_MISMATCH
    assert second.replayed is False
    assert second.charged is False
    assert second.result.payload == {}
    assert second.result.payload != first.result.payload
    assert len(connector.calls) == 1


def test_b4_an_identical_retry_still_replays_without_a_charge():
    """The guard must not turn a genuine retry into a refusal."""

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=5)

    first = dispatcher.dispatch(_call("b4-1"), job_id="job-b4", tool_calls_used=0)
    retry = dispatcher.dispatch(_call("b4-1"), job_id="job-b4", tool_calls_used=1)

    assert first.replayed is False and first.charged is True
    assert retry.replayed is True
    assert retry.charged is False
    assert retry.result.status == "ok"
    assert retry.result.payload == first.result.payload
    assert retry.result.result_ref == first.result.result_ref
    assert len(connector.calls) == 1


def test_b5_a_constant_tool_call_id_is_stopped_by_the_tool_budget():
    """The load-bearing one: `max_tool_calls` bounds the loop, not just the reads.

    A replayed call is free, so a model that keeps re-requesting one id would loop
    until `max_model_calls` while the tool budget never fired.
    """

    model = _StickyToolCallModel()
    budgets = AgentBudgets(max_tool_calls=3, max_model_calls=20)
    run = run_routing_job(
        job_id="job-b5",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=model,
        budgets=budgets,
    )

    assert run.failure is not None
    assert run.failure.code == TOOL_BUDGET_EXHAUSTED
    assert run.status == "failed"
    assert run.model_draft is None
    # it stopped at the tool budget, not after burning the model budget
    assert run.final_state["model_calls_used"] <= 4
    assert model.calls <= 4, "the loop must not run on to max_model_calls"
    assert model.calls < budgets.max_model_calls
    assert run.final_state["tool_calls_used"] <= budgets.max_tool_calls


def test_b6_a_batch_larger_than_the_remaining_tool_budget_does_not_over_dispatch():
    """The running count bounds the batch, not only its first call."""

    repository = seeded_repository()
    runtime, connector = _node_runtime(repository, max_tool_calls=1)
    budgets = AgentBudgets(max_tool_calls=1, max_model_calls=5)
    state = _tool_call_state("job-b6", _call("b6-1"), _call("b6-2"), budgets=budgets)

    update = tool_call_node(state, runtime=runtime)

    assert len(connector.calls) <= 1, "a call beyond the remaining budget must not reach a source"
    assert update["tool_calls_used"] == 1
    assert update.get("failure") is None, "an over-budget batch is a typed refusal, not a crash"
    refused = [result for result in runtime.tool_results if result.error_code]
    assert [result.error_code for result in refused] == [BUDGET_EXHAUSTED]


def test_b7_a_terminal_tool_call_failure_is_sticky():
    """`tool_call -> propose` is unconditional, so `propose` must not clear a failure.

    Clearing it re-armed the loop and let a later draft mask the tool failure as a
    successful proposal.
    """

    # 2 charged rounds, but the sticky id replays: the *round* bound is what fires
    model = _StickyToolCallModel(draft_after=3)
    budgets = AgentBudgets(max_tool_calls=2, max_model_calls=20)
    run = run_routing_job(
        job_id="job-b7",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=model,
        budgets=budgets,
    )

    assert run.failure is not None
    assert run.failure.code == TOOL_BUDGET_EXHAUSTED, "the tool failure is the job's failure"
    assert run.status == "failed"
    assert run.final_state["status"] == "failed"
    assert run.final_state["failure"].code == TOOL_BUDGET_EXHAUSTED
    assert run.model_draft is None, "the draft that would have masked the failure is unreachable"
    assert model.calls == 3, "propose must not re-arm the loop after a terminal tool failure"
    assert run.final_state["pending_tool_calls"] == []


def test_b8_a_replayed_call_does_not_duplicate_its_reference():
    """One executed call leaves one reference, however many rounds replayed it.

    `tool_results` reduces with `operator.add`, so re-appending a replayed ref put one
    entry per round on the state and repeated the same payload in every later prompt.
    """

    connector = FakeConnector()
    model = _StickyToolCallModel()
    budgets = AgentBudgets(max_tool_calls=3, max_model_calls=20)
    run = run_routing_job(
        job_id="job-b8",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        connector=connector,
        model=model,
        budgets=budgets,
    )

    refs = run.final_state["tool_results"]
    assert refs, "the one executed call is on the state"
    assert len(refs) == len({ref.tool_call_id for ref in refs}), "a replay duplicated a reference"
    assert len(run.runtime.tool_results) == len(refs), "the projection sees one payload per call"
    assert len(connector.calls) == 1, "the replayed rounds must not re-read the source"
    assert run.final_state["tool_rounds_used"] <= budgets.max_tool_calls


# --- C. redaction categories (M4): one sentinel per named category --------------


def _projected(payload: dict[str, Any]) -> str:
    """The prompt text a recorded payload produces.

    `redacted=False` is deliberate: this is the shape a buggy or older writer leaves
    behind, and the projection is the boundary that actually reaches a provider.
    """

    return project_tool_results(
        [
            ToolResult(
                result_ref="tool:job-redact:call-redact",
                job_id="job-redact",
                tool_call_id="call-redact",
                tool="sample_rows",
                status="ok",
                payload=payload,
                redacted=False,
            )
        ]
    )


def _redacted_and_projected(field: str, value: Any) -> tuple[dict[str, Any], str]:
    """Redact one row carrying `value` under `field`, and render the same payload.

    The row always carries an ordinary value too, so every category asserts both
    halves of the policy: the sentinel is gone **and** ordinary data survives.
    """

    payload = {"rows": [{field: value, "note": "keep me"}]}
    return redact_payload(payload), _projected(payload)


def test_c1_an_email_embedded_in_a_sentence_is_redacted():
    sentinel = "ada.lovelace+review@example.co.uk"
    sentence = f"please mail {sentinel} before Friday; the address is not a field value"

    assert redact_value(sentence) == REDACTION_MARKER
    redacted, projected = _redacted_and_projected("note", sentence)
    assert sentinel not in str(redacted)
    assert sentinel not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize(
    ("sentinel", "field"),
    [
        ("call 555-123-4567 before the review", "note"),
        ("+1 555.123.4567 is the on-call line", "note"),
        # an int carries no separators, so only the field name can classify it
        (5551234567, "phone"),
        (15551234567, "phone"),
    ],
)
def test_c2_a_phone_number_is_redacted_as_a_string_and_as_an_int(sentinel, field):
    """The int case is the one that used to pass through untouched."""

    if isinstance(sentinel, int):
        assert redact_value(sentinel, field) == REDACTION_MARKER
    else:
        assert redact_value(sentinel) == REDACTION_MARKER

    redacted, projected = _redacted_and_projected(field, sentinel)
    assert str(sentinel) not in str(redacted)
    assert str(sentinel) not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


def test_c3_a_postal_address_inside_free_text_is_redacted():
    sentinel = "ship to 742 Evergreen Terrace, Springfield 49007"
    assert redact_value(sentinel) == REDACTION_MARKER

    redacted, projected = _redacted_and_projected("note", sentinel)
    assert "Evergreen Terrace" not in str(redacted)
    assert "Evergreen Terrace" not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize("card", [4111111111111111, 378282246310005, 5500005555555559])
def test_c4_a_payment_card_like_digit_run_is_redacted_as_an_int(card):
    """A card-like digit run is never safe to project, whatever the field is called."""

    assert redact_value(card) == REDACTION_MARKER

    redacted, projected = _redacted_and_projected("card_number", card)
    assert str(card) not in str(redacted)
    assert str(card) not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize("identifier", ["078-05-1120", "219 09 9999", "123-45-6789"])
def test_c5_a_national_identifier_is_redacted(identifier):
    assert redact_value(identifier) == REDACTION_MARKER

    redacted, projected = _redacted_and_projected("note", identifier)
    assert identifier not in str(redacted)
    assert identifier not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://genledge:sentinel-dsn-secret@db.internal:5432/warehouse",
        "mysql://root:sentinel-dsn-secret@db.internal:3306/app",
        "mongodb+srv://genledge:sentinel-dsn-secret@cluster0.example.net/db",
    ],
)
def test_c6_a_dsn_with_embedded_credentials_is_redacted(dsn):
    """The scheme list is open-ended: `scheme://user:pass@host` is a DSN whoever makes it."""

    assert redact_value(dsn) == REDACTION_MARKER

    redacted, projected = _redacted_and_projected("dsn", dsn)
    assert dsn not in str(redacted)
    assert "sentinel-dsn-secret" not in str(redacted)
    assert dsn not in projected
    assert "sentinel-dsn-secret" not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize(
    "credential_key", ["sk-live-0000deadbeef", "ghp_0123456789abcdef", "AKIAIOSFODNN7EXAMPLE"]
)
def test_c7_a_credential_literal_used_as_a_dict_key_is_redacted(credential_key):
    """A credential literal as a *key* matches no field name; both halves must go."""

    row = {credential_key: "sentinel-row-value"}
    redacted = redact_value(row)
    assert list(redacted) == [REDACTION_MARKER], "the credential's key survived"
    assert list(redacted.values()) == [REDACTION_MARKER], "the value under it survived"

    # the shape a connector actually produces: a credential-shaped *row* key inside
    # the payload, which is where the prompt projection reads it
    payload = {"rows": [row, {"note": "keep me"}]}
    assert credential_key not in str(redact_payload(payload))
    projected = _projected(payload)
    assert credential_key not in projected
    assert "sentinel-row-value" not in projected
    assert "keep me" in projected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "sentinel-plain-text"),
        ("phone", 5551234567),
        ("secret", 40353607),
        ("email", "sentinel-not-an-email-shape"),
        ("api_key", "sentinel-plain-key"),
        ("routing_number", 123456789),
        ("national_id", "sentinel-national-id"),
        ("dob", "sentinel-dob"),
    ],
)
def test_c8_a_value_under_a_sensitive_key_name_is_redacted_whatever_it_contains(field, value):
    """For an unknown sensitive field the name decides, so nothing recognisable is needed."""

    redacted, projected = _redacted_and_projected(field, value)
    assert str(value) not in str(redacted), "the value under a sensitive name survived"
    assert str(value) not in projected
    assert "keep me" in str(redacted) and "keep me" in projected


@pytest.mark.parametrize(
    "payload",
    [
        {"note": "keep me", "count": 3, "unit_price": 10.25},
        {"order_id": "O-1001"},
        {"total": 120.5},
    ],
)
def test_c9_ordinary_values_survive_redaction(payload):
    """The guard against over-redaction: an ordinary payload is returned unchanged."""

    assert redact_payload(payload) == payload
    assert redact_value(payload) == payload
    projected = _projected(payload)
    for value in payload.values():
        assert str(value) in projected, f"an ordinary value was redacted: {value!r}"


# --- D. typed state-update errors (M6) ------------------------------------------


def test_d1_an_undeclared_write_is_a_typed_error_not_a_bare_value_error():
    """A bare `ValueError` escapes `run_routing_job` and takes the failure record with it."""

    with pytest.raises(InvalidStateUpdateError) as caught:
        validate_node_update(CONTEXT, {"model_draft": None})

    error = caught.value
    assert error.code == INVALID_STATE_UPDATE
    assert error.retryable is False
    assert isinstance(error, AgentFailure)
    assert not isinstance(error, ValueError), "the guard raised a bare ValueError"
    assert "model_draft" in error.message


def test_d2_a_rogue_write_from_tool_call_is_a_typed_failure_not_a_traceback():
    """The same write-guard contract on a **different** node than `context`."""

    import app.agent.nodes as nodes_module

    original = nodes_module.tool_call_node

    def rogue_tool_call(state, *, runtime):
        return {**original(state, runtime=runtime), "model_draft": None}

    nodes_module.tool_call_node = rogue_tool_call
    try:
        model = ScriptedModel(
            [ModelResponse(tool_calls=[_call("d2-1")], stop_reason="tool_use")]
        )
        run = run_routing_job(
            job_id="job-d2",
            source_snapshot_ids=[SNAPSHOT_ID],
            repository=seeded_repository(),
            model=model,
            budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
        )
    finally:
        nodes_module.tool_call_node = original

    assert run.failure is not None
    assert run.failure.code == INVALID_STATE_UPDATE
    assert run.failure.retryable is False
    assert run.status == "failed"
    assert run.model_draft is None
    assert "model_draft" in run.failure.message


@pytest.mark.parametrize("node", [CONTEXT, PROPOSE, TOOL_CALL])
def test_d3_every_key_a_failure_update_writes_is_declared_for_that_node(node):
    """A failure update cannot trip the guard: all four of its keys are declared."""

    update = _failure_update(
        AgentFailure(REPOSITORY_UNAVAILABLE, "synthetic control-store outage", retryable=True)
    )

    validate_node_update(node, update)
    assert {"failure", "status", "tool_rounds_used", "updated_at"} <= NODE_WRITES[node]
    assert "failure" in NODE_WRITES[node]


def test_d3_a_tool_call_failure_closes_the_round_with_declared_keys():
    # The failure update reports the rounds the run spent, so it needs the state that
    # accumulated them; a zeroed counter would hide the loop length from an operator.
    state = cast("RoutingJobState", {"job_id": "job-d3", "tool_rounds_used": 2})
    update = _tool_call_failure(
        AgentFailure(TOOL_BUDGET_EXHAUSTED, "synthetic tool budget stop", retryable=False), state
    )

    validate_node_update(TOOL_CALL, update)
    assert update["pending_tool_calls"] == []
    assert update["tool_rounds_used"] == 2, "the accumulated round count is reported, not zeroed"
    assert {"failure", "pending_tool_calls"} <= NODE_WRITES[TOOL_CALL]
    assert "tool_rounds_used" in NODE_WRITES[CONTEXT]


def test_d3_real_node_failure_updates_pass_the_write_guard():
    """Driven, not hand-built: the keys a node actually returns in its failure path."""

    context_runtime = GraphRuntime(repository=empty_inventory_repository())
    context_update = context_node(
        cast(
            "RoutingJobState",
            {
                "job_id": "job-d3-context",
                "budgets": AgentBudgets(max_tool_calls=1, max_model_calls=1),
                "source_snapshot_ids": [SNAPSHOT_ID],
            },
        ),
        runtime=context_runtime,
    )
    validate_node_update(CONTEXT, context_update)
    assert context_update["failure"].code == EMPTY_INVENTORY

    budgets = AgentBudgets(max_tool_calls=0, max_model_calls=1)
    runtime, _ = _node_runtime(seeded_repository(), max_tool_calls=0, max_model_calls=1)
    tool_update = tool_call_node(_tool_call_state("job-d3-tool", _call(), budgets=budgets), runtime=runtime)
    validate_node_update(TOOL_CALL, tool_update)
    assert tool_update["failure"].code == TOOL_BUDGET_EXHAUSTED


# --- E. budget accounting (M1, model side) --------------------------------------


class _RaisingModel:
    """A provider adapter that raises instead of returning a typed error."""

    name = "raising"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise RuntimeError("the provider is unreachable")

    @property
    def calls(self) -> int:
        return len(self.requests)


class _RepairRaisesModel(_RaisingModel):
    """The first answer fails the contract; the single repair call raises."""

    name = "repair-raises"

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.repair:
            raise RuntimeError("the provider died on the repair call")
        return ModelResponse(text="not json at all")


def test_e1_a_raising_adapter_is_recorded_durably_and_fails_typed():
    """A call that happened must be charged: an unrecorded call is free to re-spend."""

    repository = seeded_repository()
    model = _RaisingModel()
    run = run_routing_job(
        job_id="job-e1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == MODEL_UNAVAILABLE
    assert run.failure.retryable is True
    assert run.status == "failed"
    assert model.calls == 1
    assert repository.get_model_call_count("job-e1") >= 1, "the call was not recorded durably"
    assert run.final_state["model_calls_used"] >= 1


def test_e2_a_repair_call_that_raises_is_still_charged():
    """The repair was attempted, so it is charged — and cannot be reported as un-attempted."""

    repository = seeded_repository()
    model = _RepairRaisesModel()
    run = run_routing_job(
        job_id="job-e2",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert "after one repair attempt" in run.failure.message, "the attempt was reported as absent"
    assert run.final_state["model_calls_used"] == 2
    assert repository.get_model_call_count("job-e2") == 2
    assert sum(1 for request in model.requests if request.repair) == 1


def test_e3_max_model_calls_is_a_hard_cap_checked_before_the_call():
    """The cap is checked before the work it bounds, so exhaustion is a recorded outcome."""

    model = ScriptedModel([build_fake_draft(inventory(), None, None).model_dump_json()])
    run = run_routing_job(
        job_id="job-e3",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=0),
    )

    assert run.failure is not None
    assert run.failure.code == MODEL_CALL_BUDGET_EXHAUSTED
    assert run.failure.retryable is False
    assert run.status == "failed"
    assert model.calls == 0, "no provider call is made once the model budget is spent"
    assert run.model_responses == []
    assert model.queue, "the scripted answer was never consumed"


# --- F: the defects the *second* review cycle found ------------------------------
#
# `A`-`E` pin the first remediation. These pin three defects found when that work was
# itself reviewed, each of which was described as fixed while nothing tested it.


class _NestedCredentialConnector:
    """A connector whose row value is an object under a credential-named key."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        return {
            "resource_id": arguments.get("resource_id"),
            "sampling": "head",
            "rows": [
                {
                    "credentials": {"user": "svc-account", "pass": "PLAINTEXT-PASSWORD"},
                    "note": "keep me",
                }
            ],
        }


def test_f1_a_restricted_key_redacts_its_whole_subtree():
    """A key that names restricted data takes its value wholesale, container included.

    The regression: the field-name rule used to run *after* the container branches, so a
    mapping under `credentials` matched the dict branch first, the key was replaced, and
    the plaintext inside it survived — reaching the provider on a row stamped `redacted`.

    The two entry points describe different things, and both are asserted here: the
    *value* path (a name is known) collapses to one marker, and the *envelope* path keeps
    the payload's shape so callers can still index it.
    """

    subtree = {"user": "svc-account", "pass": "PLAINTEXT-PASSWORD"}
    assert redact_value(subtree, "credentials") == REDACTION_MARKER
    assert redact_payload({"credentials": subtree}) == {"credentials": REDACTION_MARKER}
    assert redact_payload({"note": "keep me"}) == {"note": "keep me"}
    # a key that *is* credential material is not a field name and does not survive
    assert redact_payload({"sk-live-9f8a7b6c": "value"}) == {REDACTION_MARKER: REDACTION_MARKER}

    # whichever shape is produced, no restricted value may appear anywhere in it
    for rendered in (
        redact_value({"credentials": subtree}),
        redact_payload({"credentials": subtree}),
        redact_value(subtree, "credentials"),
    ):
        assert "PLAINTEXT-PASSWORD" not in str(rendered)
        assert "svc-account" not in str(rendered)


def test_f1_a_nested_credential_never_reaches_the_prompt():
    connector = _NestedCredentialConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-nested",
            name="sample_rows",
            arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
        ),
        job_id="job-nested",
        tool_calls_used=0,
    )
    assert outcome.result.status == "ok"
    rendered = project_tool_results([outcome.result])
    assert "PLAINTEXT-PASSWORD" not in rendered, "a nested credential reached the prompt"
    assert "svc-account" not in rendered
    assert "keep me" in rendered, "ordinary data must survive"


def test_f1_ordinary_nested_structures_are_untouched():
    payload = {"rows": [{"note": "keep me", "count": 3, "unit_price": 10.25}]}
    assert redact_payload(payload) == payload


@pytest.mark.parametrize("method", ["get_inventory", "get_catalogue", "create_job"])
def test_f2_a_runner_level_store_fault_is_typed_not_a_traceback(method):
    """The three repository calls the runner makes *before* the graph starts.

    `_run_graph`'s handlers never see these, so a fault during the very first inventory
    read used to escape `run_routing_job` as a traceback rather than a typed failure —
    and the first read is the most likely moment for one.
    """

    class _Faulted(InMemoryRoutingRepository):
        def __init__(self, **kwargs: Any) -> None:
            self.which = kwargs.pop("which")
            super().__init__(**kwargs)

        def _boom(self):
            raise RuntimeError("control store down")

        def get_inventory(self, snapshot_id):  # type: ignore[override]
            return self._boom() if self.which == "get_inventory" else super().get_inventory(snapshot_id)

        def get_catalogue(self, catalog_ref):  # type: ignore[override]
            return self._boom() if self.which == "get_catalogue" else super().get_catalogue(catalog_ref)

        def create_job(self, job_id, **kwargs):  # type: ignore[override]
            return self._boom() if self.which == "create_job" else super().create_job(job_id, **kwargs)

    repository = _Faulted(which=method, inventories=seeded_repository().inventories)
    run = run_routing_job(
        job_id=f"job-f2-{method}",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        budgets=AgentBudgets(max_tool_calls=4, max_model_calls=4),
    )
    assert run.failure is not None
    assert run.failure.code == REPOSITORY_UNAVAILABLE
    assert run.failure.retryable is True
    assert run.status == "failed"
    assert run.model_draft is None


@pytest.mark.parametrize("token", ["../../etc/passwd", "a/../../b", "..\\windows\\system32"])
def test_f3_a_traversal_token_is_refused_before_the_connector(token):
    """`SafeToken` admits `.` and `/`, which is exactly what a traversal needs."""

    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-traversal",
            name="list_resources",
            arguments={"source_id": "source-orders-1", "path": token},
        ),
        job_id="job-traversal",
        tool_calls_used=0,
    )
    assert outcome.result.status == "error"
    assert outcome.result.error_code == INVALID_ARGUMENTS
    assert connector.calls == [], "a traversal token must not reach the source"


def test_f3_ordinary_pass_through_tokens_still_work():
    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-ordinary-path",
            name="list_resources",
            arguments={"source_id": "source-orders-1", "path": "orders/lines[]"},
        ),
        job_id="job-ordinary",
        tool_calls_used=0,
    )
    assert outcome.result.status == "ok", outcome.result.message

# --- G: the defects found when the *second* cycle's fixes were verified -----------


def test_g1_a_replayed_result_reaches_the_prompt_not_only_the_cache():
    """A warm replay must hand its recorded evidence to the model.

    The duplicate-ref fix skipped a replayed call entirely, which was right within one run
    and wrong across runs: a resumed job started with an empty `tool_results`, the prompt
    said "No tool results recorded yet", the model re-asked for the same call, and the job
    died on the model budget instead of finishing with the evidence it had already fetched.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    budgets = AgentBudgets(max_tool_calls=4, max_model_calls=4)

    first = run_routing_job(
        job_id="job-g1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )
    assert first.failure is None
    assert len(connector.calls) == 1

    replay = run_routing_job(
        job_id="job-g1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )

    assert replay.failure is None, f"the replayed run failed: {replay.failure}"
    assert replay.status == "awaiting_review"
    assert replay.model_draft is not None
    assert len(connector.calls) == 1, "a replay must not re-read the source"
    assert replay.final_state["tool_results"], "the recorded result must reach the state"
    assert replay.final_state["tool_results"][0].replayed is True
    assert len(replay.model_responses) == 2, "the model used the replay, it did not re-ask"


def test_g1_a_replay_does_not_double_count_within_one_run():
    """The other half: a ref already on the state is not appended a second time."""

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )
    call = ToolCallRequest(
        id="g1-call",
        name="sample_rows",
        arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
    )
    first = dispatcher.dispatch(call, job_id="job-g1-dedup", tool_calls_used=0)
    assert first.replayed is False

    fresh = cast(
        "RoutingJobState",
        {
            "job_id": "job-g1-dedup",
            "budgets": AgentBudgets(max_tool_calls=5, max_model_calls=5),
            "tool_calls_used": 1,
            "tool_results": [],
            "pending_tool_calls": [call],
        },
    )
    runtime = GraphRuntime(repository=repository, connector=connector, dispatcher=dispatcher)
    update = tool_call_node(fresh, runtime=runtime)
    assert update["tool_calls_used"] == 1, "a replay is not charged again"
    assert len(update["tool_results"]) == 1, "a fresh state needs the replayed ref"

    already = cast(
        "RoutingJobState",
        dict(fresh, tool_results=list(update["tool_results"])),
    )
    runtime2 = GraphRuntime(repository=repository, connector=connector, dispatcher=dispatcher)
    second = tool_call_node(already, runtime=runtime2)
    assert second["tool_results"] == [], "an already-recorded ref is not appended again"
    assert len(connector.calls) == 1


@pytest.mark.parametrize(
    "token",
    [
        "/etc/passwd",
        "/",
        "C:/Windows/win.ini",
        r"\\server\share\file",
        "....//....//etc/passwd",
    ],
)
def test_g2_an_absolute_or_collapsing_token_is_refused(token):
    """`..` segments are not the only way out of a source root.

    `os.path.join(root, "/etc/passwd")` returns the absolute path, and a normaliser that
    strips one `../` per pass turns `....//` into `../../`. Both reached the connector.
    """

    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-absolute",
            name="list_resources",
            arguments={"source_id": "source-orders-1", "path": token},
        ),
        job_id="job-absolute",
        tool_calls_used=0,
    )
    assert outcome.result.status == "error", f"{token!r} reached the source"
    assert outcome.result.error_code == INVALID_ARGUMENTS
    assert connector.calls == []


@pytest.mark.parametrize(
    "token", ["orders", "orders/lines[]", "./orders", "orders/./lines[]", "a.b/c"]
)
def test_g2_a_legitimate_path_token_still_works(token):
    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-legit",
            name="list_resources",
            arguments={"source_id": "source-orders-1", "path": token},
        ),
        job_id="job-legit",
        tool_calls_used=0,
    )
    assert outcome.result.status == "ok", outcome.result.message


@pytest.mark.parametrize(
    "key", ["pass", "pwd", "passphrase", "private_key", "access_key", "authorization",
            "bearer", "jwt", "pin", "card_number"]
)
def test_g3_the_commonest_credential_key_names_are_restricted(key):
    """`pass`, `pwd` and friends are as common as `password` and were not covered."""

    assert redact_value({"rows": [{key: "hunter2"}]}) == {
        "rows": [{key: REDACTION_MARKER}]
    }

# --- H: the defects found when the *third* cycle's fixes were verified ------------


def test_h1_a_replay_scrolled_out_of_the_projection_window_still_reaches_the_prompt():
    """A replayed result must be visible to the model, not merely un-duplicated.

    The prompt projects the last `MAX_PROJECTED_TOOL_RESULTS` results. Skipping a replay
    whose ref was already on the state therefore also dropped its *payload* once the run
    held more results than the window — the model re-asked, and the job died on a budget
    with the evidence already in hand.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    budgets = AgentBudgets(max_tool_calls=40, max_model_calls=10)
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=budgets,
    )
    call = ToolCallRequest(
        id="c0",
        name="sample_rows",
        arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
    )
    # six recorded results: the first is older than the projection window
    for index in range(6):
        dispatcher.dispatch(
            ToolCallRequest(
                id=f"c{index}",
                name="sample_rows",
                arguments={
                    "source_id": "source-orders-1",
                    "resource_id": "orders.lines[]",
                    "limit": 3,
                },
            ),
            job_id="job-h1",
            tool_calls_used=index,
        )
    recorded = [repository.get_tool_result("job-h1", f"c{index}") for index in range(6)]
    assert all(item is not None for item in recorded)

    runtime = GraphRuntime(repository=repository, connector=connector, dispatcher=dispatcher)
    runtime.tool_results = [item for item in recorded if item is not None]
    state = cast(
        "RoutingJobState",
        {
            "job_id": "job-h1",
            "budgets": budgets,
            "tool_calls_used": 6,
            "tool_rounds_used": 6,
            "tool_results": [
                ToolResult(
                    result_ref=item.result_ref,
                    job_id="job-h1",
                    tool_call_id=item.tool_call_id,
                    tool="sample_rows",
                    status="ok",
                    payload={},
                )
                for item in runtime.tool_results
            ],
            "pending_tool_calls": [call],
        },
    )
    update = tool_call_node(state, runtime=runtime)

    # the ref is already on the state, so it is not appended a second time ...
    assert update["tool_results"] == [], "an already-recorded ref is not appended again"
    # ... but the payload is now the most recent one, so the prompt can still read it
    assert runtime.tool_results[-1].tool_call_id == "c0", "the replayed payload must be in view"


def test_h2_a_refusal_does_not_spend_another_calls_head_room():
    """A pre-dispatch refusal costs nothing, so it must not consume the budget.

    Passing a batch index as `tool_calls_used` counted refused requests as if they had
    spent budget: with `max_tool_calls=1`, a batch whose first entry was refused
    pre-dispatch had its second, valid entry refused with `budget_exhausted` while nothing
    had reached the connector.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(max_tool_calls=1),
    )
    seen: set[str] = set()
    refused = dispatcher.dispatch(
        ToolCallRequest(
            id="h2-bad",
            name="sample_rows",
            arguments={
                "source_id": "not-in-this-snapshot",
                "resource_id": "orders.lines[]",
                "fields": ["lines[].sku"],
                "limit": 3,
            },
        ),
        job_id="job-h2",
        tool_calls_used=0,
        seen_call_ids=seen,
    )
    assert refused.charged is False
    assert refused.result.error_code == UNAUTHORIZED_SOURCE

    valid = dispatcher.dispatch(
        ToolCallRequest(
            id="h2-good",
            name="sample_rows",
            arguments={
                "source_id": "source-orders-1",
                "resource_id": "orders.lines[]",
                "fields": ["lines[].sku"],
                "limit": 3,
            },
        ),
        job_id="job-h2",
        tool_calls_used=0,
        seen_call_ids=seen,
    )
    assert valid.result.status == "ok", (
        f"a refusal spent the budget: {valid.result.error_code} {valid.result.message}"
    )
    assert valid.charged is True
    assert len(connector.calls) == 1


# --- I: the five findings of the follow-up PR review -----------------------------
#
# I1  a connector's own exception text must not carry a credential into the *persisted*
#     `ToolResult.message` (`redact_message`).
# I2  `model_node_timeout_seconds` and `tool_node_timeout_seconds` must be enforced at
#     the seam that owns each one, and the strength of each guarantee must be honest.
# I3  a model call whose durable record cannot be written must end the run, because
#     `agent_model_calls` is the model budget's authority.
# I4  an unsupported live provider must be refused instead of being routed through the
#     Anthropic SDK (see `test_adapters_and_modes.py` for the adapter routing cases).
# I5  a prompt digest must be a property of the prompt, not of the checkout's line
#     endings (see `test_prompt_safety.py`).

#: Sentinel values that must never appear in a persisted tool result. Each is a shape
#: a real connector's exception message is known to carry: a driver quotes the DSN it
#: could not reach, an HTTP client quotes the `Authorization` header it was given, and
#: both quote the host and the user.
CONNECTOR_DSN = "postgresql://genledge:sentinel-dsn-secret@db.internal:5432/warehouse"
CONNECTOR_AUTH = "Authorization: Bearer sk-ant-sentinel-bearer-value"
CONNECTOR_EMAIL = "ops-sentinel@example.com"

#: One message with no restricted shape at all: the control for over-redaction.
ORDINARY_CONNECTOR_ERROR = "the source did not answer in time"


class _LeakyConnector:
    """A connector whose exception text carries credentials, as a real one's does."""

    def __init__(self, message: str = CONNECTOR_DSN) -> None:
        self.message = message

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        raise ConnectorError("connector_error", self.message)


class _LeakyUnexpectedConnector(_LeakyConnector):
    """The same leak as an *unexpected* exception, which is the other catch branch."""

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        raise RuntimeError(self.message)


class _FailingRecordingRepository(InMemoryRoutingRepository):
    """A repository whose `record_tool_result` fails the way a driver does."""

    def __init__(self, message: str) -> None:
        super().__init__(inventories=seeded_repository().inventories)
        self.message = message

    def record_tool_result(self, result: ToolResult):
        raise RuntimeError(self.message)


@pytest.mark.parametrize("sentinel", [CONNECTOR_DSN, CONNECTOR_AUTH, CONNECTOR_EMAIL])
@pytest.mark.parametrize("connector_kind", [_LeakyConnector, _LeakyUnexpectedConnector])
def test_i1_a_connector_exception_cannot_write_a_credential_into_the_result(sentinel, connector_kind):
    """The persisted row — not only the prompt — is where the redaction has to hold.

    `test_c6_*` pins the redaction rule for a payload *value*. This pins the other
    route a credential takes into `ToolResult`: the connector's own exception text,
    which reaches `ToolResult.message` through `_error` and is then readable again
    through `get_tool_result`.
    """

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, connector_kind(sentinel))
    outcome = dispatcher.dispatch(_call("i1-leak"), job_id="job-i1", tool_calls_used=0)

    assert outcome.result.status == "error"
    assert outcome.result.error_code == CONNECTOR_ERROR
    assert sentinel not in str(outcome.result.message)
    assert sentinel not in str(outcome.result.payload)
    # the row the store holds is the row a replay hands back
    stored = repository.get_tool_result("job-i1", "i1-leak")
    assert stored is not None
    assert sentinel not in str(stored.message)
    assert sentinel not in stored.model_dump_json()
    # the typed code survives, so the model still knows what to adapt to
    assert stored.error_code == CONNECTOR_ERROR
    # and the secret does not reach the next prompt either
    assert sentinel not in project_tool_results([stored])


def test_i1_an_ordinary_connector_error_is_replaced_by_the_typed_message():
    """An ordinary connector failure is structured and safe, not a redaction marker.

    Two properties, and the old version of this test asserted only the first half of the
    first one: the *classification* survives (the typed `error_code`, the harness's fixed
    message, the charge, the persistence), and an ordinary connector's prose is **not**
    persisted. Prose is not the evidence the model adapts to — the code is — so replacing
    it costs the model nothing and is what makes the boundary fail-safe. The second
    assertion is here because the first version of this fix flattened a credential-bearing
    message to `[redacted]`, which also passes "the secret is gone" while telling the
    operator nothing.
    """

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _LeakyConnector(ORDINARY_CONNECTOR_ERROR))
    outcome = dispatcher.dispatch(_call("i1-plain"), job_id="job-i1-plain", tool_calls_used=0)

    assert outcome.result.status == "error"
    assert outcome.result.error_code == CONNECTOR_ERROR
    assert outcome.charged is True, "a call that reached the connector stays charged"
    assert outcome.result.message == CONNECTOR_ERROR_MESSAGES[CONNECTOR_ERROR]
    assert outcome.result.message is not None
    assert outcome.result.message.strip(), "the message still explains itself"
    assert REDACTION_MARKER not in outcome.result.message, "a marker is not an explanation"
    assert ORDINARY_CONNECTOR_ERROR not in str(outcome.result.message)

    stored = repository.get_tool_result("job-i1-plain", "i1-plain")
    assert stored is not None
    assert stored.message == CONNECTOR_ERROR_MESSAGES[CONNECTOR_ERROR]
    assert stored.error_code == CONNECTOR_ERROR
    assert ORDINARY_CONNECTOR_ERROR not in project_tool_results([stored])
    # the code reaches the next prompt, so the model can still adapt
    assert CONNECTOR_ERROR in project_tool_results([stored])


#: A credential shape **no pattern in this module recognises**: an opaque session cookie
#: with a vendor-specific name, no credential word, no DSN, no `sk-` prefix, no card run.
#: This is the case the old design could not survive — a blocklist leaks the first shape
#: nobody enumerated — and it is the whole reason the persisted message is now built from
#: the error code instead of from the exception's text.
UNFAMILIAR_CREDENTIAL = (
    "upstream rejected the request: X-Acme-Session=Zx9Qv2Lm7Rt4Wp1Kd8Nh5Bs3Gy6Jc0Fa"
)
UNFAMILIAR_CREDENTIAL_VALUE = "Zx9Qv2Lm7Rt4Wp1Kd8Nh5Bs3Gy6Jc0Fa"


def test_i1_an_unfamiliar_credential_shape_cannot_reach_the_persisted_result():
    """The fail-safe case: a credential the blocklist does not know is still not stored.

    Asserted against the **constructed and persisted** rows, not against the redaction
    helper: `redact_message(UNFAMILIAR_CREDENTIAL)` returns the text unchanged (there is
    nothing in it to match), so a test of the helper alone would pass while the credential
    sat in the control store. What makes it safe is that no connector exception text is
    persisted at all.
    """

    assert redact_message(UNFAMILIAR_CREDENTIAL) == UNFAMILIAR_CREDENTIAL, (
        "if this ever matches a pattern, the test has stopped proving the fail-safe case; "
        "pick another unfamiliar shape"
    )

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _LeakyConnector(UNFAMILIAR_CREDENTIAL))
    outcome = dispatcher.dispatch(_call("i1-unfamiliar"), job_id="job-i1-unfamiliar", tool_calls_used=0)

    assert outcome.result.status == "error"
    assert outcome.result.error_code == CONNECTOR_ERROR
    assert UNFAMILIAR_CREDENTIAL_VALUE not in str(outcome.result.message)
    assert UNFAMILIAR_CREDENTIAL_VALUE not in outcome.result.model_dump_json()

    stored = repository.get_tool_result("job-i1-unfamiliar", "i1-unfamiliar")
    assert stored is not None
    assert UNFAMILIAR_CREDENTIAL_VALUE not in str(stored.message)
    assert UNFAMILIAR_CREDENTIAL_VALUE not in stored.model_dump_json()
    assert UNFAMILIAR_CREDENTIAL_VALUE not in project_tool_results([stored])
    assert stored.message == CONNECTOR_ERROR_MESSAGES[CONNECTOR_ERROR]


def test_i1_an_unfamiliar_credential_cannot_reach_it_through_an_unexpected_exception():
    """The other catch branch, where there is no declared code to fall back on."""

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _LeakyUnexpectedConnector(UNFAMILIAR_CREDENTIAL))
    outcome = dispatcher.dispatch(_call("i1-unfamiliar-b"), job_id="job-i1-unfamiliar-b", tool_calls_used=0)

    assert outcome.result.error_code == CONNECTOR_ERROR
    assert UNFAMILIAR_CREDENTIAL_VALUE not in str(outcome.result.message)
    stored = repository.get_tool_result("job-i1-unfamiliar-b", "i1-unfamiliar-b")
    assert stored is not None
    assert UNFAMILIAR_CREDENTIAL_VALUE not in stored.model_dump_json()


def test_i1_a_connector_declared_code_survives_and_keeps_its_own_message():
    """An approved, declared code is preserved, and maps to its own fixed message.

    The connector's *code* is part of the contract — `plans/LANGGRAPH_HARNESS_PLAN.md`
    §8.4 names the envelope codes — so it is persisted verbatim and it selects the safe
    sentence. Only the free-text prose is dropped.
    """

    declared = "connector_unavailable"

    class _DeclaredCodeConnector:
        def call(self, name, arguments, job_id):
            raise ConnectorError(declared, f"temporarily unavailable: {UNFAMILIAR_CREDENTIAL}")

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _DeclaredCodeConnector())
    outcome = dispatcher.dispatch(_call("i1-code"), job_id="job-i1-code", tool_calls_used=0)

    assert outcome.result.error_code == declared, "the declared code is preserved"
    assert outcome.result.message == CONNECTOR_ERROR_MESSAGES[declared]
    assert UNFAMILIAR_CREDENTIAL_VALUE not in str(outcome.result.message)
    stored = repository.get_tool_result("job-i1-code", "i1-code")
    assert stored is not None
    assert stored.error_code == declared
    assert stored.message == CONNECTOR_ERROR_MESSAGES[declared]


def test_i1_an_unknown_connector_code_is_replaced_not_persisted(caplog):
    """A code the envelope does not declare is foreign text, so the row does not hold it.

    `ConnectorError.code` is connector-declared. The message was already chosen from a
    closed table, but the code itself was persisted verbatim — any text, any length,
    unredacted — and it is the field the model acts on, so it is the one string the
    message boundary could not reach. An undeclared code now becomes `connector_error`
    (a classification the model can still act on) and the declared string goes to the
    restricted channel. `prompts.py` had been projecting `error_code` through
    `redact_value` because the model treated it as source-derived; the row now agrees.
    """

    class _InventedCodeConnector:
        def call(self, name, arguments, job_id):
            raise ConnectorError(f"acme-{UNFAMILIAR_CREDENTIAL}", "see the vendor dashboard")

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _InventedCodeConnector())

    with caplog.at_level(logging.DEBUG, logger="app.agent.tools"):
        outcome = dispatcher.dispatch(_call("i1-invented"), job_id="job-i1-invented", tool_calls_used=0)

    assert outcome.result.error_code == CONNECTOR_ERROR, "the row holds a declared code"
    assert outcome.result.message == CONNECTOR_ERROR_MESSAGES[CONNECTOR_ERROR]
    assert UNFAMILIAR_CREDENTIAL_VALUE not in str(outcome.result.message)

    stored = repository.get_tool_result("job-i1-invented", "i1-invented")
    assert stored is not None
    assert stored.error_code == CONNECTOR_ERROR
    assert UNFAMILIAR_CREDENTIAL_VALUE not in stored.model_dump_json(), (
        "the declared code must not be persisted"
    )
    assert UNFAMILIAR_CREDENTIAL_VALUE not in project_tool_results([stored])
    # the classification the model reads is always one of ours
    assert stored.error_code in DECLARED_ERROR_CODES
    # and the declared code is not lost — it is on the restricted channel
    assert any(UNFAMILIAR_CREDENTIAL_VALUE in record.getMessage() for record in caplog.records)


def test_i1_a_very_long_connector_code_cannot_be_persisted():
    """The envelope is a bound as well as a closed set: length cannot be abused either."""

    class _HugeCodeConnector:
        def call(self, name, arguments, job_id):
            raise ConnectorError("A" * 5000, "whatever")

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _HugeCodeConnector())
    outcome = dispatcher.dispatch(_call("i1-huge"), job_id="job-i1-huge", tool_calls_used=0)

    assert outcome.result.error_code == CONNECTOR_ERROR
    stored = repository.get_tool_result("job-i1-huge", "i1-huge")
    assert stored is not None
    assert len(stored.error_code or "") <= max(len(code) for code in DECLARED_ERROR_CODES)


def test_i1_every_code_the_harness_itself_emits_is_declared():
    """The control for the other direction: our own codes must not be rewritten.

    If `DECLARED_ERROR_CODES` were missing one of the module's own literals, the harness
    would start genericising its *own* classification — the same defect from the other
    side.

    The check is an **AST scan of `tools.py`'s own `_error(...)` call sites**, not a
    hand-written or name-pattern list — a hand-written list is how a drift tripwire stops
    tripping, and a first attempt here using a name suffix (`*_ERROR`, `*_FAILED`, …) was
    demonstrated to miss a literal named `SOME_NEW_FAILURE`. The scan resolves each call
    site's code argument as follows, and the guards below assert it is not blind (≥10 call
    sites, ≥5 module constants, the scope-refusal constants present by name):

    * a module-level UPPER_CASE string constant — must be in `DECLARED_ERROR_CODES`;
    * a string literal — must be in `DECLARED_ERROR_CODES`;
    * any other shape (an f-string, a missing argument, a call) — an offender, so
      unrecognised forms fail closed rather than being skipped;
    * the local `code` and any `<x>.code` attribute — **skipped by name**, which is the
      limit an independent review measured: a new `code = "some_new_failure"` local, a
      module-local `_Codes.code` attribute, or a call through an alias of `self._error`
      would each reach `_error` with the control test still green. What makes those
      harmless today is the **runtime** gate rather than this test: an undeclared code is
      replaced before the row is built, which
      `test_i1_an_unknown_connector_code_is_replaced_not_persisted` proves end to end. So
      this test's job is narrower than "no undeclared code can reach `_error`" — it is
      "the constants, literals and scope refusals the module actually writes are declared",
      and it is honest about not resolving provenance.
    """

    import ast
    import pathlib

    source = pathlib.Path(tools_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper() and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                constants[name] = node.value.value

    def _error_calls(tree_or_node) -> list[ast.Call]:
        found = []
        for node in ast.walk(tree_or_node):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", None) == "_error" or getattr(func, "id", None) == "_error":
                found.append(node)
        return found

    def code_argument(call: ast.Call) -> ast.expr | None:
        for keyword in call.keywords:
            if keyword.arg == "code":
                return keyword.value
        return call.args[2] if len(call.args) > 2 else None

    assert len(constants) >= 5, f"the constant scan found almost nothing: {sorted(constants)}"

    # 1. the local `code` must be built from declared constants, in `_scope_error`.
    #
    # This checks the *source* of the refusal codes, not the provenance of every `code`
    # local — see the docstring: a call site passing a differently-fed local named `code`
    # is skipped by name, and the runtime gate is what makes that safe. The scope-refusal
    # returns are the ones this module actually writes, so they are worth checking.
    scope_returns = [
        node.value.elts[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and node.value.elts
    ]
    scope_names = {element.id for element in scope_returns if isinstance(element, ast.Name)}
    scope_literals = {
        element.value for element in scope_returns if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert scope_names, "no `return <code>, <message>` found in tools.py, so the scan is blind"
    bad_scope = sorted(
        name for name in scope_names if name in constants and constants[name] not in DECLARED_ERROR_CODES
    ) + sorted(code for code in scope_literals if code not in DECLARED_ERROR_CODES)
    assert not bad_scope, f"a scope refusal returns an undeclared code: {bad_scope}"
    # the local `code` in dispatch() is that tuple's first element
    assert {"UNAUTHORIZED_SOURCE", "RESOURCE_NOT_FOUND"} <= scope_names, (
        "the scope-refusal codes are no longer the constants this test assumes"
    )

    # 2. every `_error(...)` call site's code argument
    offenders: list[str] = []
    sites = _error_calls(tree)
    assert len(sites) >= 10, f"only {len(sites)} _error call sites found; the scan is blind"
    for call in sites:
        argument = code_argument(call)
        if argument is None:
            offenders.append(f"line {call.lineno}: no code argument")
        elif isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if argument.value not in DECLARED_ERROR_CODES:
                offenders.append(f"line {call.lineno}: literal {argument.value!r} undeclared")
        elif isinstance(argument, ast.Name):
            if argument.id == "code":
                continue  # covered by the _scope_error check above
            if argument.id not in constants:
                offenders.append(f"line {call.lineno}: local {argument.id!r} is not a module constant")
            elif constants[argument.id] not in DECLARED_ERROR_CODES:
                offenders.append(f"line {call.lineno}: {argument.id} = {constants[argument.id]!r} undeclared")
        elif isinstance(argument, ast.Attribute) and argument.attr == "code":
            # `<something>.code` is a *foreign* code — a connector's `ConnectorError.code`, or
            # the `code` half of a scope refusal. It is exactly what `_error`'s runtime gate
            # exists for, so it is legitimate here and covered by
            # `test_i1_an_unknown_connector_code_is_replaced_not_persisted` instead. Note this
            # is a **spelling** exemption, not a provenance one: a module-local attribute that
            # merely happens to be called `code` is skipped too, which the runtime gate covers.
            continue
        else:
            offenders.append(f"line {call.lineno}: code argument is not a name or literal")
    assert not offenders, f"the harness would genericise its own classifications: {offenders}"

    # 3. the message table cannot name a code the row would never hold
    for code in sorted(CONNECTOR_ERROR_MESSAGES):
        assert code in DECLARED_ERROR_CODES, f"{code} has a message but is not declared"


@pytest.mark.parametrize("sentinel", [CONNECTOR_DSN, CONNECTOR_AUTH, UNFAMILIAR_CREDENTIAL])
def test_i1_restricted_diagnostics_are_available_only_on_the_debug_channel(sentinel, caplog):
    """The text is not discarded — it moves, and the channel is the restriction.

    `logger.debug` rather than `info`/`warning` on purpose: the payload is exactly what
    the persisted row may not hold, so a default-configured process must not produce it.
    An operator opts in deliberately.
    """

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _LeakyConnector(sentinel))

    with caplog.at_level(logging.DEBUG, logger="app.agent.tools"):
        outcome = dispatcher.dispatch(_call("i1-log"), job_id="job-i1-log", tool_calls_used=0)

    assert sentinel not in str(outcome.result.message)
    assert caplog.records, "the diagnostic was dropped instead of logged"

    # at the default level nothing carrying it is emitted at all
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.agent.tools"):
        dispatcher.dispatch(_call("i1-log-2"), job_id="job-i1-log-2", tool_calls_used=0)
    assert all(sentinel not in record.getMessage() for record in caplog.records), (
        "restricted text was emitted above DEBUG"
    )
    assert all(record.levelno < logging.INFO for record in caplog.records) or not caplog.records


def test_i1_the_harnesss_own_refusals_still_reach_the_model_verbatim():
    """The control for the other half of the boundary: our text is not genericised.

    Making every message generic would satisfy "no connector text is persisted" while
    destroying the evidence the model needs — the field path it got wrong, the budget
    that stopped it, the row cap it hit. Those messages are the harness's own strings.
    """

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, FakeConnector())

    bad_arguments = dispatcher.dispatch(
        ToolCallRequest(id="i1-args", name="sample_rows", arguments={"source_id": "source-orders-1"}),
        job_id="job-i1-harness",
        tool_calls_used=0,
    )
    assert bad_arguments.result.error_code == INVALID_ARGUMENTS
    assert "resource_id" in (bad_arguments.result.message or ""), "the offending field is named"

    out_of_scope = dispatcher.dispatch(
        ToolCallRequest(
            id="i1-scope",
            name="sample_rows",
            arguments={"source_id": "not-in-this-snapshot", "resource_id": "orders.lines[]"},
        ),
        job_id="job-i1-harness",
        tool_calls_used=0,
    )
    assert out_of_scope.result.error_code == UNAUTHORIZED_SOURCE
    assert "not-in-this-snapshot" in (out_of_scope.result.message or "")

    injected = dispatcher.dispatch(
        ToolCallRequest(
            id="i1-injection",
            name="sample_rows",
            arguments={
                "source_id": "source-orders-1",
                "resource_id": "orders.lines[]",
                "fields": ["x; DROP TABLE orders"],
            },
        ),
        job_id="job-i1-harness",
        tool_calls_used=0,
    )
    assert injected.result.error_code == INVALID_ARGUMENTS
    assert "x; DROP TABLE orders" in (injected.result.message or ""), (
        "a harness-authored refusal keeps its detail"
    )
    assert injected.charged is False, "a pre-dispatch refusal is still not charged"


def test_i1_a_typed_connector_timeout_keeps_its_structure():
    """`connector_timeout` stays a named bound, and its own text stays out of the row."""

    connector = _HangingConnector()
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
        budgets=AgentBudgets(tool_node_timeout_seconds=1),
    )
    try:
        outcome = dispatcher.dispatch(_call("i1-timeout"), job_id="job-i1-timeout", tool_calls_used=0)
    finally:
        connector.release.set()

    assert outcome.result.error_code == CONNECTOR_TIMEOUT
    assert outcome.result.message == CONNECTOR_TIMEOUT_MESSAGE
    assert "tool_node_timeout_seconds" in (outcome.result.message or ""), "the bound is named"
    stored = repository.get_tool_result("job-i1-timeout", "i1-timeout")
    assert stored is not None and stored.message == CONNECTOR_TIMEOUT_MESSAGE


#: A credential-shaped **field name** a connector invented. Distinct from
#: `UNFAMILIAR_CREDENTIAL`, which is a value: a result-validation report renders the
#: *location* of a failure, and for an undeclared field pydantic's location is the key the
#: connector chose — a second route for connector-authored text into a persisted row, found
#: by an independent review of the first fix and closed the same way.
UNFAMILIAR_FIELD_NAME = "X-Acme-Session-Zx9Qv2Lm7Rt4Wp1Kd8Nh5Bs3Gy6Jc0Fa"


def test_i1_a_connector_chosen_field_name_cannot_reach_the_persisted_result():
    """The validation-report route: whitelist the location, do not sanitise it.

    `extra="forbid"` makes a connector's invented key the *location* of a `ValidationError`,
    and `_brief` persisted that location — so a connector-authored name rode into a row
    through the one message the fail-safe boundary does not cover, contradicting the claim
    that a validation report "never renders a connector-supplied value". Sanitising it
    would put the blocklist back in charge; the location is now rendered only when it is a
    field the result model declares, and an integer (list index) which no connector authors.
    """

    class _InventedFieldConnector:
        def call(self, name, arguments, job_id):
            return {
                "resource_id": arguments.get("resource_id", ""),
                "fields": [],
                "field_count": 0,
                "declared_key": [],
                UNFAMILIAR_FIELD_NAME: "unused",
            }

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _InventedFieldConnector())
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="i1-field-name",
            name="describe_resource",
            arguments={"source_id": SOURCE_ID, "resource_id": "orders"},
        ),
        job_id="job-i1-field-name",
        tool_calls_used=0,
    )

    assert outcome.result.error_code == CONNECTOR_ERROR
    message = outcome.result.message or ""
    # the problem is still named, by pydantic's own message and by the marker
    assert "does not match its contract" in message
    assert "Extra inputs are not permitted" in message
    assert UNDECLARED_FIELD_MARKER in message
    # the connector's name is not
    assert UNFAMILIAR_FIELD_NAME not in message

    stored = repository.get_tool_result("job-i1-field-name", "i1-field-name")
    assert stored is not None
    assert UNFAMILIAR_FIELD_NAME not in stored.model_dump_json()
    assert UNFAMILIAR_FIELD_NAME not in project_tool_results([stored])


def test_i1_a_foreign_key_inside_a_declared_dict_field_cannot_reach_the_result():
    """The third location shape: a declared `dict[str, int]` whose *key* is foreign text.

    `ProfileResourceResult.nulls` is ours; the keys inside it are payload, echoed from the
    model's own `fields` request or from whatever the connector read. Pydantic reports a bad
    value there as `('nulls', '<the key>')`, so the key is a second connector-authored
    location part — the whitelist covers it because only *declared field names* pass, and a
    dict key is not one.
    """

    class _BadDictValueConnector:
        def call(self, name, arguments, job_id):
            return {
                "resource_id": arguments.get("resource_id", ""),
                "profiled_fields": [],
                "row_count": 1,
                "nulls": {UNFAMILIAR_FIELD_NAME: "not-an-integer"},
            }

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _BadDictValueConnector())
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="i1-dict-key",
            name="profile_resource",
            arguments={"source_id": SOURCE_ID, "resource_id": "orders"},
        ),
        job_id="job-i1-dict-key",
        tool_calls_used=0,
    )

    assert outcome.result.error_code == CONNECTOR_ERROR
    message = outcome.result.message or ""
    assert UNFAMILIAR_FIELD_NAME not in message
    assert "nulls" in message, "the declared dict field is still named"
    assert "valid integer" in message, "pydantic's own message survives"
    stored = repository.get_tool_result("job-i1-dict-key", "i1-dict-key")
    assert stored is not None
    assert UNFAMILIAR_FIELD_NAME not in stored.model_dump_json()


def test_i1_a_declared_field_in_a_validation_report_is_still_named():
    """The control: whitelisting must not blind the report to our own field names.

    A declared field that is missing, or whose type is wrong, is the evidence the model
    corrects itself from, and those names are this package's own vocabulary.
    """

    class _WrongShapeConnector:
        def call(self, name, arguments, job_id):
            return {"resource_id": 7, "fields": "not-a-list", "field_count": 0}

    repository = seeded_repository()
    dispatcher = _dispatcher(repository, _WrongShapeConnector())
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="i1-declared-field",
            name="describe_resource",
            arguments={"source_id": SOURCE_ID, "resource_id": "orders"},
        ),
        job_id="job-i1-declared-field",
        tool_calls_used=0,
    )
    assert outcome.result.error_code == CONNECTOR_ERROR
    message = outcome.result.message or ""
    assert "resource_id" in message or "fields" in message, "our own field is named"
    assert UNDECLARED_FIELD_MARKER not in message, "no non-existent field was blamed"

    # and the argument model's own fields survive the same whitelist
    bad_arguments = dispatcher.dispatch(
        ToolCallRequest(id="i1-declared-args", name="sample_rows", arguments={"source_id": SOURCE_ID}),
        job_id="job-i1-declared-field",
        tool_calls_used=0,
    )
    assert bad_arguments.result.error_code == INVALID_ARGUMENTS
    assert "resource_id" in (bad_arguments.result.message or ""), "the omitted field is named"


def test_i1_a_store_exception_cannot_write_a_credential_into_the_result():
    """The control store's exception travels the same route and gets the same rule.

    A failing driver quotes the connection string it could not open, and the
    `storage_failed` result is the one thing that path returns to the caller.
    """

    repository = _FailingRecordingRepository(CONNECTOR_DSN)
    dispatcher = _dispatcher(repository, FakeConnector())
    outcome = dispatcher.dispatch(_call("i1-store"), job_id="job-i1-store", tool_calls_used=0)

    assert outcome.result.error_code == STORAGE_FAILED
    assert CONNECTOR_DSN not in str(outcome.result.message)
    assert "sentinel-dsn-secret" not in str(outcome.result.message)
    # nothing was written, which is the point of the typed failure
    assert repository.get_tool_result("job-i1-store", "i1-store") is None


def test_i1_an_unfamiliar_credential_from_the_store_is_also_kept_out():
    """The storage path's blocklist is a blocklist, so its shape is pinned here too.

    This path is the one that still persists harness-authored text *around* foreign text
    (`the '<code>' result could not be persisted: <type>: <text>`), so it is the remaining
    place a driver's own string could travel. It is redacted, and — being a blocklist —
    that is defence in depth rather than a guarantee; the test records which of the two it
    is by asserting the familiar shape is caught and naming the unfamiliar one as a known
    limit of that path rather than of the connector path.
    """

    repository = _FailingRecordingRepository(f"could not connect: {CONNECTOR_DSN}")
    dispatcher = _dispatcher(repository, FakeConnector())
    outcome = dispatcher.dispatch(_call("i1-store-2"), job_id="job-i1-store-2", tool_calls_used=0)

    assert outcome.result.error_code == STORAGE_FAILED
    assert "sentinel-dsn-secret" not in str(outcome.result.message)
    assert CONNECTOR_DSN not in str(outcome.result.message)


def test_i1_a_connector_credential_still_reaches_the_node_as_a_typed_failure():
    """Safety must not cost the control flow: the node still ends the round typed."""

    runtime, _ = _node_runtime(_FailingRecordingRepository(CONNECTOR_DSN))
    update = tool_call_node(_tool_call_state("job-i1-node", _call()), runtime=runtime)

    assert update["failure"].code == REPOSITORY_UNAVAILABLE
    assert CONNECTOR_DSN not in update["failure"].message


# --- I3: the durable model-call record is not advisory ---------------------------


class _UnrecordableModelCalls(InMemoryRoutingRepository):
    """The store refuses `record_model_call`, the way an unhealthy one would."""

    def __init__(self) -> None:
        super().__init__(inventories=seeded_repository().inventories)
        self.write_attempts = 0

    def record_model_call(self, job_id: str, *, node: str, tokens: int) -> None:
        self.write_attempts += 1
        raise RuntimeError("the control store is down")


class _CountingScriptedModel(ScriptedModel):
    """`ScriptedModel` with a name, so a failure record can be attributed."""

    name = "counting-scripted"


def test_i3_a_model_call_whose_record_cannot_be_written_ends_the_run():
    """`max_model_calls` reads the durable count, so an unrecorded call is a free one.

    Swallowing this fault into a log line — which is what the runner used to do — meant
    the provider was called, no row charged it, and the next `propose` read the same
    unchanged count: the budget stopped bounding the loop exactly when the store was
    unhealthy. The run now ends, and it says which layer failed.
    """

    repository = _UnrecordableModelCalls()
    model = _CountingScriptedModel([build_fake_draft(inventory(), None, None).model_dump_json()])
    run = run_routing_job(
        job_id="job-i3",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == REPOSITORY_UNAVAILABLE
    assert run.failure.retryable is True
    assert run.status == "failed"
    assert run.model_draft is None, "the run did not continue on an unaccounted call"
    assert model.calls == 1, "no second model call is made once the record fails"
    assert repository.write_attempts == 1, "the write was attempted, not skipped"
    assert repository.get_model_call_count("job-i3") == 0, "the store really did not record it"


def test_i3_a_raising_adapter_whose_record_cannot_be_written_ends_the_run():
    """The adapter-raised path records too, so it fails closed the same way."""

    class _Raising:
        name = "raising"

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            raise RuntimeError("the provider is unreachable")

    repository = _UnrecordableModelCalls()
    model = _Raising()
    run = run_routing_job(
        job_id="job-i3-raise",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == REPOSITORY_UNAVAILABLE
    assert model.calls == 1


def test_i3_a_repair_call_whose_record_cannot_be_written_ends_the_run():
    """The single repair call is recorded too — and is never reported as un-attempted."""

    repository = _UnrecordableModelCalls()
    model = _CountingScriptedModel(["not json at all"])
    run = run_routing_job(
        job_id="job-i3-repair",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is not None
    assert run.failure.code == REPOSITORY_UNAVAILABLE
    assert run.failure.code != INVALID_MODEL_OUTPUT, "the repair was reported as un-attempted"
    assert model.repair_calls == 0, "the first call is the one whose record failed"
    assert model.calls == 1
    assert repository.write_attempts == 1


def test_i3_a_recorded_call_still_advances_the_durable_count():
    """The control: a healthy store records, and the count is what the budget reads."""

    repository = seeded_repository()
    model = _CountingScriptedModel([build_fake_draft(inventory(), None, None).model_dump_json()])
    run = run_routing_job(
        job_id="job-i3-ok",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.failure is None
    assert run.model_draft is not None
    assert repository.get_model_call_count("job-i3-ok") == 1
    assert run.final_state["model_calls_used"] == 1


# --- I2: the two node budgets are enforced, and honestly described ---------------


class _HangingConnector:
    """A connector that never answers, until the test releases it.

    A `threading.Event` rather than `sleep`: the wait ends the instant the assertion
    has run, so the worker thread cannot outlive the test and the block itself is a
    real block rather than a timing race.
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls: list[tuple[str, dict, str]] = []
        self.reached = threading.Event()

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        self.reached.set()
        self.release.wait(timeout=10)
        return {
            "resource_id": arguments.get("resource_id", ""),
            "sampling": "head",
            "rows": [{"sku": "SKU-1"}],
        }


def test_i2_a_hung_connector_fails_its_call_not_the_node():
    """`tool_node_timeout_seconds` is a real bound on one connector call.

    `plans/LANGGRAPH_HARNESS_PLAN.md` §6.5: "a hung connector fails its call, not the
    node". Before this, `tool_node_timeout_seconds` was declared on `AgentBudgets` and
    read nowhere, so a connector that never returned blocked the worker forever.
    """

    connector = _HangingConnector()
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
        budgets=AgentBudgets(tool_node_timeout_seconds=1),
    )

    started = monotonic()
    try:
        outcome = dispatcher.dispatch(_call("i2-hang"), job_id="job-i2", tool_calls_used=0)
    finally:
        connector.release.set()
    elapsed = monotonic() - started

    assert outcome.result.status == "error"
    assert outcome.result.error_code == CONNECTOR_TIMEOUT
    assert "tool_node_timeout_seconds" in (outcome.result.message or ""), "the bound is named"
    assert connector.reached.is_set(), "the call really did reach the connector"
    assert outcome.charged is True, "a call that reached the connector is charged"
    assert elapsed < 8, f"the dispatch waited {elapsed:.1f}s for a hung connector"
    # Persisted, so a retry of the same id replays this verdict instead of hanging again
    stored = repository.get_tool_result("job-i2", "i2-hang")
    assert stored is not None and stored.error_code == CONNECTOR_TIMEOUT
    replay = dispatcher.dispatch(_call("i2-hang"), job_id="job-i2", tool_calls_used=1)
    assert replay.replayed is True
    assert len(connector.calls) == 1, "the replay did not re-enter the connector"


def test_i2_a_zero_tool_budget_disables_the_bound_without_changing_behaviour():
    """`ge=0` means zero is legal, and it means "unbounded", not "fail immediately".

    Otherwise every default-constructed budget in a deployment that sets `0` would
    refuse every call — and the fix would be a behaviour change rather than an
    addition. The connector answers normally here, on the calling thread.
    """

    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=seeded_repository(),
        inventory=inventory(),
        budgets=AgentBudgets(tool_node_timeout_seconds=0),
    )
    outcome = dispatcher.dispatch(_call("i2-zero"), job_id="job-i2-zero", tool_calls_used=0)
    assert outcome.result.status == "ok"
    assert len(connector.calls) == 1


def test_i2_an_over_budget_model_answer_is_refused_and_charged():
    """`model_node_timeout_seconds` bounds the work the node will accept.

    A synchronous provider call cannot be preempted in-process, and
    `app/agent/deadlines.py` says so rather than claiming a deadline it cannot keep.
    What the node *can* guarantee is enforced here: an answer that overran the node
    budget is recorded durably, refused, and never becomes the run's draft.
    """

    class _SlowModel:
        name = "slow"

        def __init__(self, delay: float) -> None:
            self.delay = delay
            self.calls = 0

        def invoke(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            time.sleep(self.delay)
            return ModelResponse(text=build_fake_draft(inventory(), None, None).model_dump_json())

    repository = seeded_repository()
    model = _SlowModel(1.0)
    run = run_routing_job(
        job_id="job-i2-model",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        model=model,
        budgets=AgentBudgets(
            max_tool_calls=5,
            max_model_calls=5,
            model_node_timeout_seconds=1,
        ),
    )

    assert run.failure is not None
    assert run.failure.code == MODEL_UNAVAILABLE
    assert run.failure.retryable is True
    assert "model_node_timeout_seconds" in run.failure.message
    assert run.model_draft is None, "an over-budget answer became the draft"
    assert model.calls == 1
    assert repository.get_model_call_count("job-i2-model") == 1, "the call was still charged"
    # the over-budget response is not reported as an accepted one
    assert run.model_responses == []


def test_i2_an_on_time_model_answer_is_accepted():
    """The control: the deadline does not refuse a call that met it."""

    repository = seeded_repository()
    run = run_routing_job(
        job_id="job-i2-model-ok",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        budgets=AgentBudgets(
            max_tool_calls=5,
            max_model_calls=5,
            model_node_timeout_seconds=600,
        ),
    )
    assert run.failure is None
    assert run.model_draft is not None
    assert len(run.model_responses) == 2


def test_i2_the_two_declared_node_budgets_are_read_not_merely_stored():
    """A declared budget that nothing reads is documentation, not a bound.

    Both `AgentBudgets` fields are asserted here through the two functions that consume
    them, so a future edit that drops the consumption fails this test instead of
    silently reverting the guarantee.
    """

    assert tool_call_timeout_seconds(AgentBudgets()) == AgentBudgets().tool_node_timeout_seconds
    assert tool_call_timeout_seconds(AgentBudgets(tool_node_timeout_seconds=7)) == 7
    assert model_node_timeout_seconds(AgentBudgets()) == AgentBudgets().model_node_timeout_seconds
    assert model_node_timeout_seconds(AgentBudgets(model_node_timeout_seconds=11)) == 11


def test_i2_the_attempt_bound_is_the_plans_derivation():
    """The hard per-attempt bound is stated once, at the transport level.

    §6.5's row is `request × (1 + retries) + 60 s` = 960 s at the documented defaults,
    which is the same number the plan derives for `model_node_timeout_seconds`. The two
    are asserted together so the hierarchy cannot silently invert.
    """

    assert derived_model_timeout_seconds() == 300 * 3 + 60 == 960
    assert derived_model_timeout_seconds(100, max_retries=0) == 160
    assert AgentBudgets().model_node_timeout_seconds == derived_model_timeout_seconds()
