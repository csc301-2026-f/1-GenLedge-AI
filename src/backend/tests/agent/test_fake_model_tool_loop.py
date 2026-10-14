"""The fake model completes a real tool loop and returns a valid `ModelDraft`."""

from __future__ import annotations

from app.agent.contracts import ModelDraft
from app.agent.graph import run_routing_job
from app.agent.models import FAKE_TARGET_RESOURCE, FAKE_TOOL_CALL_ID, FakeModel, provider_configured
from app.agent.repositories import ORDER_LINES, SNAPSHOT_ID, seeded_repository
from app.agent.tools import FakeConnector


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
    repository, connector, run = _run()

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
    repository = seeded_repository()
    connector = FakeConnector()
    first = run_routing_job(
        job_id="job-replay-1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
    )
    assert first.failure is None
    # the repository still holds the recorded result, so a second run replays it
    replay = run_routing_job(
        job_id="job-replay-1",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
    )
    assert replay.failure is None
    assert len(connector.calls) == 1, "a replayed call must not hit the connector again"
    assert replay.final_state["tool_results"][0].replayed is True


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


def test_no_live_provider_is_contacted_by_the_loop():
    # The fake adapter is the only model in this test module; nothing here opens a
    # socket, and no assertion depends on the host's provider configuration.
    model = FakeModel(inventory=seeded_repository().get_inventory(SNAPSHOT_ID))
    assert model.name == "deterministic-fake"
    assert provider_configured({"ANTHROPIC_API_KEY": ""}) is False
