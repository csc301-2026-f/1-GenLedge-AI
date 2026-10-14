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

Everything here is deterministic and offline: repositories are the in-memory doubles
of `app.agent.repositories`, models are local stubs, and no test touches a provider.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.agent.contracts import AgentBudgets, ToolCallRequest
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
from app.agent.models import ModelRequest, ModelResponse, build_fake_draft
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
    INVALID_ARGUMENTS,
    INVALID_TOOL_REQUEST,
    REDACTION_MARKER,
    REPLAY_MISMATCH,
    STORAGE_FAILED,
    UNAUTHORIZED_SOURCE,
    FakeConnector,
    ToolDispatcher,
    ToolResult,
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
