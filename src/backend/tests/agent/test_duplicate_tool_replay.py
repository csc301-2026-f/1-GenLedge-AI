"""A repeated `(job_id, tool_call_id)` replays the recorded result once."""

from __future__ import annotations

from typing import cast

from app.agent.contracts import AgentBudgets, ToolCallRequest
from app.agent.graph import run_routing_job
from app.agent.models import FAKE_TOOL_CALL_ID
from app.agent.nodes import GraphRuntime, tool_call_node
from app.agent.repositories import SNAPSHOT_ID, seeded_repository
from app.agent.state import RoutingJobState
from app.agent.tools import (
    INVALID_ARGUMENTS,
    UNAUTHORIZED_SOURCE,
    FakeConnector,
    ToolDispatcher,
    redact_payload,
)

from .doubles import inventory

SOURCE_ID = "source-orders-1"


def _dispatcher(repository, connector, **budgets) -> ToolDispatcher:
    return ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
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
    """A replayed call is returned to the model without a second counter charge.

    Proven at the node, on a state that already carries the charged counter, because
    `model_calls_used` is deliberately **job-scoped and durable**: re-running the whole
    job under the same `job_id` is refused by the model budget once that budget is
    genuinely spent, which is a different guarantee from the one under test.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = _dispatcher(repository, connector, max_tool_calls=5)

    first = dispatcher.dispatch(_call(), job_id="job-replay-counter", tool_calls_used=0)
    assert first.replayed is False and first.charged is True
    assert len(connector.calls) == 1

    # A fresh state (as a resumed job has) replays the call: the recorded payload comes
    # back, so the node must not charge the budget again — and it *must* hand the ref to
    # the state, or the next prompt has no evidence and the model re-asks forever.
    replay_state = {
        "job_id": "job-replay-counter",
        "budgets": AgentBudgets(max_tool_calls=5, max_model_calls=5),
        "tool_calls_used": 1,
        "tool_results": [],
        "pending_tool_calls": [_call()],
    }
    runtime = GraphRuntime(repository=repository, connector=connector, dispatcher=dispatcher)
    update = tool_call_node(cast("RoutingJobState", replay_state), runtime=runtime)

    assert update["tool_calls_used"] == 1, "a replay must not re-charge the tool budget"
    assert len(update["tool_results"]) == 1, "the replayed ref must reach the state"
    assert update["tool_results"][0].replayed is True
    assert len(connector.calls) == 1, "a replay must not hit the connector again"

    # Within one run the ref is already on the state, so the reducer must not see it twice.
    already = dict(replay_state, tool_results=list(update["tool_results"]))
    runtime2 = GraphRuntime(repository=repository, connector=connector, dispatcher=dispatcher)
    second = tool_call_node(cast("RoutingJobState", already), runtime=runtime2)
    assert second["tool_results"] == [], "an already-recorded ref is not appended again"


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
    connector = _CredentialConnector()
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
    assert outcome.result.status == "ok"
    stored = repository.get_tool_result("job-6", "call-redact")
    assert stored is not None
    assert stored.redacted is True
    row = stored.payload["rows"][0]
    # A restricted *value* is replaced. A key that names a restricted field keeps its
    # place — the field name is not the secret, and callers index the payload by it —
    # while a key that is itself credential material (`sk-live-...`) is not a field name
    # and does not survive at all.
    assert row["password"] == "[redacted]"
    assert row["contact"] == "[redacted]"
    assert row["dsn"] == "[redacted]"
    assert stored.payload["resource_id"] == "orders.lines[]"
    for secret in ("hunter2", "ada@example.com", "postgresql://"):
        assert secret not in str(stored.payload)
    assert redact_payload({"sk-live-9f8a7b6c": "v"}) == {"[redacted]": "[redacted]"}


class _CredentialConnector:
    """A connector whose row values include credential-like and contact-like data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        return {
            "resource_id": arguments.get("resource_id"),
            "sampling": "head",
            "rows": [
                {
                    "password": "hunter2",
                    "contact": "ada@example.com",
                    "dsn": "postgresql://user:pw@host/db",
                }
            ],
        }
