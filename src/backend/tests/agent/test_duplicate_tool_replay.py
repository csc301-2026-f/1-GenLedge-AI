"""A repeated `(job_id, tool_call_id)` replays the recorded result once."""

from __future__ import annotations

from app.agent.contracts import AgentBudgets, ToolCallRequest
from app.agent.graph import run_routing_job
from app.agent.models import FAKE_TOOL_CALL_ID
from app.agent.repositories import SNAPSHOT_ID, seeded_repository
from app.agent.tools import (
    INVALID_ARGUMENTS,
    UNAUTHORIZED_SOURCE,
    FakeConnector,
    ToolDispatcher,
)

SOURCE_ID = "source-orders-1"


def _dispatcher(repository, connector, **budgets) -> ToolDispatcher:
    return ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=repository.get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(**budgets),
    )


def _call(tool_call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        id=tool_call_id,
        name="sample_rows",
        arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": 3},
    )


def test_repeated_tool_call_id_replays_without_a_second_connector_call():
    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector)

    first = dispatcher.dispatch(_call(), job_id="job-1", tool_calls_used=0)
    second = dispatcher.dispatch(_call(), job_id="job-1", tool_calls_used=1)

    assert first.replayed is False
    assert first.charged is True
    assert second.replayed is True
    assert second.charged is False
    assert second.result.payload == first.result.payload
    assert second.result.result_ref == first.result.result_ref
    assert len(connector.calls) == 1, "the connector must be called at most once"


def test_replay_does_not_increment_the_tool_counter_in_the_node():
    repository = seeded_repository()
    connector = FakeConnector()
    budgets = AgentBudgets(max_tool_calls=5, max_model_calls=5)

    run = run_routing_job(
        job_id="job-replay-counter",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )
    assert run.failure is None
    assert run.final_state["tool_calls_used"] == 1
    assert len(connector.calls) == 1

    replay = run_routing_job(
        job_id="job-replay-counter",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )
    assert replay.failure is None
    assert len(connector.calls) == 1
    assert replay.final_state["tool_results"][0].replayed is True
    assert replay.final_state["tool_results"][0].tool_call_id == FAKE_TOOL_CALL_ID


def test_a_budget_refusal_is_reported_again_rather_than_replayed():
    """A refusal is not persisted, so a retried id is refused again — never replayed."""

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=1)

    dispatched = dispatcher.dispatch(_call("call-a"), job_id="job-2", tool_calls_used=0)
    refused = dispatcher.dispatch(_call("call-b"), job_id="job-2", tool_calls_used=1)
    refused_again = dispatcher.dispatch(_call("call-b"), job_id="job-2", tool_calls_used=1)

    assert dispatched.result.status == "ok"
    for outcome in (refused, refused_again):
        assert outcome.result.status == "error"
        assert outcome.result.error_code == "budget_exhausted"
        assert outcome.replayed is False
        assert outcome.charged is False
    assert repository.get_tool_result("job-2", "call-b") is None
    assert len(connector.calls) == 1


def test_invalid_arguments_are_typed_data_and_never_dispatched():
    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector)

    outcome = dispatcher.dispatch(
        ToolCallRequest(id="call-bad", name="sample_rows", arguments={"limit": 3}),
        job_id="job-3",
        tool_calls_used=0,
    )
    assert outcome.result.status == "error"
    assert outcome.result.error_code == INVALID_ARGUMENTS
    assert outcome.charged is False
    assert connector.calls == []

    invented = dispatcher.dispatch(
        ToolCallRequest(id="call-invented", name="drop_table", arguments={}),
        job_id="job-3",
        tool_calls_used=0,
    )
    assert invented.result.error_code == "unsupported"
    assert connector.calls == []


def test_an_out_of_scope_source_is_refused_and_recorded_as_a_security_event():
    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector)

    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-foreign",
            name="sample_rows",
            arguments={"source_id": "source-other", "resource_id": "orders.lines[]"},
        ),
        job_id="job-4",
        tool_calls_used=0,
    )
    assert outcome.result.error_code == UNAUTHORIZED_SOURCE
    assert connector.calls == []
    assert dispatcher.security_events == [
        {"job_id": "job-4", "tool_call_id": "call-foreign", "tool": "sample_rows", "code": UNAUTHORIZED_SOURCE}
    ]


def test_a_resource_outside_the_snapshot_is_not_found():
    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector)
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-missing",
            name="describe_resource",
            arguments={"source_id": SOURCE_ID, "resource_id": "payroll"},
        ),
        job_id="job-5",
        tool_calls_used=0,
    )
    assert outcome.result.error_code == "resource_not_found"
    assert connector.calls == []


def test_recorded_results_are_redacted_before_persistence():
    repository = seeded_repository()
    connector = _SessionConnector()
    dispatcher = _dispatcher(repository, connector)
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-redact",
            name="sample_rows",
            arguments={"source_id": SOURCE_ID, "resource_id": "orders.lines[]", "limit": 3},
        ),
        job_id="job-6",
        tool_calls_used=0,
    )
    assert outcome.result.redacted is True
    stored = repository.get_tool_result("job-6", "call-redact")
    assert stored is not None
    assert stored.redacted is True
    assert stored.payload["password"] == "[redacted]"
    assert stored.payload["contact"] == "[redacted]"
    assert stored.payload["resource_id"] == "orders.lines[]"
    assert "hunter2" not in str(stored.payload)


class _SessionConnector:
    """A connector returning a credential-like and a contact-like value."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        return {
            "resource_id": arguments.get("resource_id"),
            "password": "hunter2",
            "contact": "ada@example.com",
            "dsn": "postgresql://user:pw@host/db",
        }
