"""The fake model completes a real tool loop and returns a valid `ModelDraft`."""

from __future__ import annotations

import json

from app.agent.contracts import AgentBudgets, ModelDraft, ToolCallRequest
from app.agent.graph import run_routing_job
from app.agent.models import (
    FAKE_TARGET_RESOURCE,
    FAKE_TOOL_CALL_ID,
    FakeModel,
    ModelRequest,
    ModelResponse,
    provider_configured,
)
from app.agent.repositories import ORDER_LINES, SNAPSHOT_ID, seeded_repository
from app.agent.tools import TOOL_NAMES, FakeConnector, ToolDispatcher

from .doubles import inventory

SOURCE_ID = "source-orders-1"


def _run(**kwargs):
    repository = kwargs.pop("repository", None) or seeded_repository()
    connector = kwargs.pop("connector", None) or FakeConnector()
    result = run_routing_job(
        job_id="job-loop-1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        **kwargs,
    )
    return repository, connector, result


def test_fake_model_requests_exactly_one_tool_call_then_returns_a_draft():
    _, connector, run = _run()

    assert run.mode.mode == "fake"
    assert run.failure is None
    assert run.status == "awaiting_review"
    assert run.model_draft is not None
    assert isinstance(run.model_draft, ModelDraft)

    # one tool call, for the repeating array, through the real connector
    assert len(connector.calls) == 1
    name, arguments, job_id = connector.calls[0]
    assert name in {"sample_rows", "profile_resource"}
    assert arguments["resource_id"] == FAKE_TARGET_RESOURCE == ORDER_LINES
    assert job_id == "job-loop-1"

    assert run.final_state["tool_calls_used"] == 1
    assert [ref.tool_call_id for ref in run.final_state["tool_results"]] == [FAKE_TOOL_CALL_ID]
    assert run.final_state["tool_results"][0].status == "ok"


def test_tool_result_is_recorded_once_and_referenced_not_inlined():
    repository, _, run = _run()

    recorded = repository.get_tool_result("job-loop-1", FAKE_TOOL_CALL_ID)
    assert recorded is not None
    assert recorded.redacted is True
    assert recorded.bytes_estimate > 0

    # state holds refs, never payloads
    for ref in run.final_state["tool_results"]:
        assert ref.result_ref == recorded.result_ref
        assert not hasattr(ref, "payload")
    assert "rows" not in run.final_state


def _lines_only_inventory():
    from app.agent.contracts import FieldRef, InventoryField, InventoryView, ResourceSummary, SourceType

    return InventoryView(
        snapshot_id=SNAPSHOT_ID,
        resources=[
            ResourceSummary(resource_id=ORDER_LINES, name="orders.lines[]", kind="collection", field_count=2)
        ],
        fields=[
            InventoryField(
                ref=FieldRef(source_id=SOURCE_ID, resource_id=ORDER_LINES, field_path=path),
                type=SourceType.TEXT if path.endswith("line_id") else SourceType.NUMBER,
                nullable=False,
                repeating=True,
                samples=["1"],
                description=None,
                ambiguity=None,
                status="stable",
            )
            for path in ("lines[].line_id", "lines[].quantity")
        ],
    )


def test_build_fake_draft_survives_an_empty_attribute_set():
    """The draft builder must not raise on a snapshot scoped to one repeating resource.

    `orders.lines[]` is the very resource the fake model samples, so a lines-only
    snapshot is the most natural narrow inventory there is. The orders table used to be
    built unconditionally and its merge key took `items[0]`, so an empty attribute list
    raised `IndexError` — an untyped crash where the contract promises a typed outcome.
    Called directly, because through the graph the failure would be masked by an earlier
    check and the mutation would survive.
    """

    from app.agent.models import build_fake_draft

    draft = build_fake_draft(_lines_only_inventory(), None, None)

    assert draft.tables, "a draft needs at least one table"
    for table in draft.tables:
        assert table.key, "every table has a merge key"
        assert table.attributes
    assert {table.id for table in draft.tables} == {"fact_order_lines"}


def test_a_lines_only_inventory_runs_end_to_end_without_an_exception():
    """The same inventory through the runner: a typed outcome either way."""

    from app.agent.repositories import InMemoryRoutingRepository

    repository = InMemoryRoutingRepository(inventories={SNAPSHOT_ID: _lines_only_inventory()})
    run = run_routing_job(
        job_id="job-lines-only",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )

    assert run.status in {"awaiting_review", "failed", "incomplete"}
    if run.failure is not None:
        assert run.failure.code


def test_the_fake_draft_serialises_the_from_alias():
    """The relationship's `from` alias must survive the round trip.

    `Relationship.from_ref` is aliased to `from`, which is a Python keyword, so the
    fake draft builds the relationship through a typed mapping and unpacks it. Pydantic
    refuses a positional call and mypy refuses an untyped unpack, so this pins the one
    place those two constraints meet: the wire key must be `from`, and the model must
    read it back.
    """

    from app.agent.contracts import Relationship
    from app.agent.models import _RelationshipArgs, build_fake_draft

    draft = build_fake_draft(inventory(), None, None)
    relationships = [rel for table in draft.tables for rel in table.relationships]
    assert relationships, "the repeating structure produces at least one relationship"

    payload = relationships[0].model_dump(by_alias=True)
    assert "from" in payload, payload
    assert "from_ref" not in payload, payload
    assert Relationship.model_validate(payload).from_ref == payload["from"]

    # the typed mapping binds the alias key, not the field name
    assert set(_RelationshipArgs.__annotations__) == {"from", "to_ref", "cardinality", "evidence"}
    serialised = json.loads(draft.model_dump_json(by_alias=True))
    assert serialised["tables"], serialised


def test_the_draft_is_schema_valid_and_harness_owned_fields_are_assigned():
    _, _, run = _run()
    draft = run.model_draft
    assert draft is not None
    assert draft.revision == 1 == run.final_state["revision_count"]
    assert draft.tables, "a proposal must contain at least one table"
    for table in draft.tables:
        assert table.key, "the merge key is required"
        assert table.rationale
        assert table.grain
        for attribute in table.attributes:
            assert attribute.evidence, "every attribute cites evidence"


def test_the_loop_is_exactly_context_propose_tool_call_propose():
    _, _, run = _run()
    # two model calls: the tool request and the final draft
    assert run.final_state["model_calls_used"] == 2
    assert [response.stop_reason for response in run.model_responses] == ["tool_use", "end_turn"]
    assert run.runtime.repairs_used == 0


def test_replaying_the_same_job_reuses_the_recorded_result_with_one_connector_call():
    """A re-run against a warm store replays the recorded evidence *and uses it*.

    The point of the replay cache is that a resumed job does not re-read the source. The
    recorded result therefore has to reach the prompt as well as the connector count: a
    replayed call that is dropped from the state leaves the prompt saying "No tool results
    recorded yet", the model re-asks, and the job dies on the model budget instead of
    finishing with the evidence it already had.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    budgets = AgentBudgets(max_tool_calls=4, max_model_calls=4)

    first = run_routing_job(
        job_id="job-replay-1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )
    assert first.failure is None
    assert len(connector.calls) == 1

    replay = run_routing_job(
        job_id="job-replay-1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
    )

    assert replay.failure is None, f"the replayed run failed: {replay.failure}"
    assert replay.status == "awaiting_review"
    assert replay.model_draft is not None
    assert len(connector.calls) == 1, "a replayed call must not hit the connector again"
    assert replay.final_state["tool_results"], "the replayed result must reach the state"
    assert replay.final_state["tool_results"][0].replayed is True
    assert replay.final_state["tool_results"][0].tool_call_id == FAKE_TOOL_CALL_ID
    # the model saw the recorded evidence rather than being told there was none
    assert len(replay.model_responses) == 2, "one tool round, then the draft"


def test_cold_start_proposes_new_tables():
    _, _, cold = _run()
    assert cold.runtime.catalogue is None
    assert "fact_order_lines" in {table.id for table in cold.model_draft.tables}


def test_catalogue_reuse_path_keeps_catalogue_table_ids():
    repository = seeded_repository(with_catalogue=True)
    _, _, reuse = _run(repository=repository, catalogue_ref="catalog-warehouse-1")
    table_ids = {table.id for table in reuse.model_draft.tables}
    assert {"fact_orders", "dim_customers"} <= table_ids
    assert reuse.runtime.catalogue is not None


def test_the_loop_binds_tools_so_a_provider_can_request_one():
    """The proposal call carries the tool schemas; without them no provider can loop.

    The fake adapter ignores `tools`, so the request is recorded from a spy subclass.
    """

    repository = seeded_repository()
    connector = FakeConnector()
    spy = _RecordingFake(inventory=repository.get_inventory(SNAPSHOT_ID))
    run_routing_job(
        job_id="job-tool-binding",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        model=spy,
    )
    assert spy.requests_seen, "the propose node made a call"
    names = {schema["name"] for schema in spy.requests_seen[0].tools}
    assert names == set(TOOL_NAMES)
    assert all(schema["input_schema"]["type"] == "object" for schema in spy.requests_seen[0].tools)


class _RecordingFake(FakeModel):
    """A fake adapter that keeps the requests it was handed."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.requests_seen: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests_seen.append(request)
        return super().invoke(request)


def test_provider_configured_is_presence_only():
    assert provider_configured({"ANTHROPIC_API_KEY": "sk-live"}) is True
    assert provider_configured({"ANTHROPIC_API_KEY": "   "}) is False
    assert provider_configured({}) is False
