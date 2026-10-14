"""Fault-injection matrix for the tool boundary and the graph.

The contract says a tool failure is **data the model reads**, not an exception and not
a crash (`plans/user-stories/US4.md` §5.4, `plans/LANGGRAPH_HARNESS_PLAN.md` §8.4). A
single hand-written failing connector cannot show that: each fault mode reaches a
different branch — argument validation, scope, budget, the connector call, the result
contract, the byte cap, the row cap.

Every cell here asserts the same three things:

1. no exception escapes `dispatch` or `run_routing_job`;
2. the run ends with a typed `error_code` (or a typed `FailureInfo`);
3. the budget is not charged for work that did not happen.
"""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentBudgets, ToolCallRequest
from app.agent.graph import run_routing_job
from app.agent.models import ModelRequest, ModelResponse
from app.agent.repositories import SNAPSHOT_ID, InMemoryRoutingRepository, seeded_repository
from app.agent.tools import REDACTION_MARKER, ConnectorError, ToolDispatcher

from .doubles import inventory

SOURCE_ID = "source-orders-1"


class FaultConnector:
    """A connector that fails a chosen way. Records whether it was reached."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        if self.mode == "raise_connector_error":
            raise ConnectorError("connector_error", "the source rejected the read")
        if self.mode == "raise_unexpected":
            raise RuntimeError("a bug in the connector, not a source fault")
        if self.mode == "timeout":
            raise ConnectorError("connector_timeout", "no answer within the tool budget")
        if self.mode == "not_a_dict":
            return ["not", "an", "object"]  # type: ignore[return-value]
        if self.mode == "missing_required":
            return {"sampling": "head"}  # no resource_id
        if self.mode == "wrong_types":
            return {"resource_id": 7, "sampling": "head", "rows": "not-a-list"}
        if self.mode == "oversize":
            return {
                "resource_id": arguments.get("resource_id", ""),
                "sampling": "head",
                "rows": [{"sku": "X" * 500} for _ in range(200)],
            }
        if self.mode == "too_many_rows":
            return {
                "resource_id": arguments.get("resource_id", ""),
                "sampling": "head",
                "rows": [{"sku": f"SKU-{index}"} for index in range(50)],
            }
        if self.mode == "credentials_in_rows":
            return {
                "resource_id": arguments.get("resource_id", ""),
                "sampling": "head",
                "rows": [{"password": "hunter2", "contact": "a@b.co", "note": "keep me"}],
            }
        if self.mode == "unsupported":
            return {"status": "unsupported", "reason": "no cursor on this source"}
        if self.mode == "extra_field":
            # A connector that grows a field the harness never declared. Strict
            # result models make that a typed `connector_error` rather than data the
            # row/byte caps know nothing about -- see
            # `test_an_undeclared_connector_field_is_rejected_not_absorbed`.
            return {
                "resource_id": arguments.get("resource_id", ""),
                "sampling": "head",
                "rows": [{"sku": "SKU-1"}],
                "confidence": 0.99,
            }
        raise AssertionError(f"unhandled fault mode {self.mode!r}")


def _dispatcher(
    connector, **budget_overrides
) -> tuple[ToolDispatcher, InMemoryRoutingRepository]:
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
        budgets=AgentBudgets(**budget_overrides),
    )
    return dispatcher, repository


def _call(tool_call_id: str = "fault-1") -> ToolCallRequest:
    return ToolCallRequest(
        id=tool_call_id,
        name="sample_rows",
        arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": 3},
    )


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("raise_connector_error", "connector_error"),
        ("raise_unexpected", "connector_error"),
        ("timeout", "connector_timeout"),
        ("not_a_dict", "connector_error"),
        ("missing_required", "connector_error"),
        ("wrong_types", "connector_error"),
        ("extra_field", "connector_error"),
        ("credentials_in_rows", "ok"),
    ],
)
def test_every_connector_fault_becomes_a_typed_result(mode, expected_code):
    connector = FaultConnector(mode)
    dispatcher, repository = _dispatcher(connector)

    outcome = dispatcher.dispatch(_call(), job_id="job-fault", tool_calls_used=0)

    # 1. it did not raise, and it did reach the connector
    assert connector.calls, f"{mode} never reached the connector"
    # 2. the outcome is typed data with a non-empty code
    if expected_code == "ok":
        assert outcome.result.status == "ok"
    else:
        assert outcome.result.status == "error"
        assert outcome.result.error_code == expected_code
        assert outcome.result.message, "an error result must explain itself"
    # 3. a call that reached the connector is charged; that is what bounds the loop
    assert outcome.charged is True
    assert repository.get_tool_result("job-fault", "fault-1") is not None


def test_a_get_changes_unsupported_answer_is_a_normal_result_not_an_error():
    """`unsupported` is a capability report, not a failure: capabilities differ by source."""

    connector = FaultConnector("unsupported")
    dispatcher, _ = _dispatcher(connector)
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="capability-1",
            name="get_changes",
            arguments={"source_id": SOURCE_ID},
        ),
        job_id="job-capability",
        tool_calls_used=0,
    )
    assert outcome.result.status == "ok"
    assert outcome.result.payload["status"] == "unsupported"
    assert outcome.result.payload["reason"]


def test_an_undeclared_connector_field_is_rejected_not_absorbed():
    """Result models are `extra="forbid"`, so a connector cannot invent a field.

    This is a deliberate friction point: strictness catches exactly the drift that
    would otherwise appear on the review screen as data nobody validated. The cost is
    that adding a field to a connector requires adding it to the result model first,
    which is the intended direction.
    """

    connector = FaultConnector("extra_field")
    dispatcher, repository = _dispatcher(connector)
    outcome = dispatcher.dispatch(_call("extra-1"), job_id="job-extra", tool_calls_used=0)

    assert outcome.result.status == "error"
    assert outcome.result.error_code == "connector_error"
    assert "does not match its contract" in (outcome.result.message or "")
    assert "confidence" in (outcome.result.message or ""), "the offending field is named"
    assert repository.get_tool_result("job-extra", "extra-1") is not None


@pytest.mark.parametrize(
    "mode",
    ["raise_connector_error", "raise_unexpected", "timeout", "not_a_dict", "missing_required", "wrong_types"],
)
def test_a_connector_fault_replays_instead_of_re_reading_the_source(mode):
    """A failed call is persisted, so a retried id does not hit the source again.

    This is the point of the replay cache: a resumed job must observe the same
    failure rather than a second read that might succeed and silently change the
    proposal.
    """

    connector = FaultConnector(mode)
    dispatcher, repository = _dispatcher(connector)

    first = dispatcher.dispatch(_call(), job_id="job-replay-fault", tool_calls_used=0)
    second = dispatcher.dispatch(_call(), job_id="job-replay-fault", tool_calls_used=1)

    assert first.result.status == "error"
    assert second.replayed is True
    assert second.charged is False
    assert second.result.error_code == first.result.error_code
    assert len(connector.calls) == 1, "a replay must not re-read the source"
    assert repository.get_tool_result("job-replay-fault", "fault-1") is not None


def test_a_budget_refusal_is_not_persisted_because_nothing_ran():
    """The opposite case: a refusal before dispatch is not evidence, so it is not cached."""

    connector = FaultConnector("raise_connector_error")
    dispatcher, repository = _dispatcher(connector, max_tool_calls=0)

    outcome = dispatcher.dispatch(_call(), job_id="job-refused", tool_calls_used=0)

    assert outcome.result.error_code == "budget_exhausted"
    assert outcome.charged is False
    assert connector.calls == [], "a refused call must not reach the connector"
    assert repository.get_tool_result("job-refused", "fault-1") is None


def test_an_oversize_result_is_a_budget_error_not_a_crash():
    connector = FaultConnector("oversize")
    dispatcher, _ = _dispatcher(connector, max_tool_bytes=500)
    outcome = dispatcher.dispatch(_call(), job_id="job-bytes", tool_calls_used=0)
    assert outcome.result.status == "error"
    assert outcome.result.error_code == "budget_exhausted"
    assert "max_tool_bytes" in (outcome.result.message or "")
    # the read happened and produced the oversize payload, so the attempt is charged
    assert outcome.charged is True
    assert connector.calls, "the connector was reached"


def test_too_many_rows_is_a_budget_error_naming_the_row_cap():
    connector = FaultConnector("too_many_rows")
    dispatcher, _ = _dispatcher(connector, max_tool_rows=5)
    outcome = dispatcher.dispatch(_call(), job_id="job-rows", tool_calls_used=0)
    assert outcome.result.status == "error"
    assert outcome.result.error_code == "budget_exhausted"
    assert "max_tool_rows" in (outcome.result.message or "")


def test_a_faulty_connector_still_redacts_before_persisting():
    connector = FaultConnector("credentials_in_rows")
    dispatcher, _ = _dispatcher(connector)
    outcome = dispatcher.dispatch(_call(), job_id="job-redact", tool_calls_used=0)
    assert outcome.result.status == "ok"
    row = outcome.result.payload["rows"][0]
    assert row["password"] == REDACTION_MARKER
    assert row["contact"] == REDACTION_MARKER
    assert row["note"] == "keep me", "ordinary values must survive redaction"
    assert "hunter2" not in str(outcome.result.payload)


# --- the same faults through the whole graph ------------------------------------


class _ToolLoopModel:
    """A model that keeps asking for the same tool, so the fault reaches the graph."""

    name = "fault-loop"

    def __init__(self, *, limit: int = 6) -> None:
        self.limit = limit
        self.requests: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) > self.limit:
            return ModelResponse(text="give up")
        return ModelResponse(
            tool_calls=[
                ToolCallRequest(
                    id=f"fault-call-{len(self.requests)}",
                    name="sample_rows",
                    arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": 3},
                )
            ],
            input_tokens=10,
            output_tokens=5,
            stop_reason="tool_use",
        )


@pytest.mark.parametrize(
    "mode",
    [
        "raise_connector_error",
        "raise_unexpected",
        "timeout",
        "not_a_dict",
        "missing_required",
        "wrong_types",
        "credentials_in_rows",
    ],
)
def test_the_graph_survives_every_connector_fault(mode):
    """No fault mode may escape the graph, and the loop must still be bounded."""

    connector = FaultConnector(mode)
    model = _ToolLoopModel()
    run = run_routing_job(
        job_id=f"job-graph-{mode}",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        connector=connector,
        model=model,
        budgets=AgentBudgets(max_tool_calls=3, max_model_calls=8),
    )

    # a typed terminal state, never an exception
    assert run.status in {"failed", "awaiting_review", "incomplete"}
    # the loop stayed inside its budgets
    assert run.final_state["tool_calls_used"] <= 3
    assert run.final_state["model_calls_used"] <= 8
    # a fault is either recovered into a draft or ends the run with a typed failure
    assert run.model_draft is not None or run.failure is not None
    # every fault reaches the model as data, never as a lost call
    assert all(
        request.results or index == 0 for index, request in enumerate(model.requests)
    ), "a recorded error was not projected back to the model"
