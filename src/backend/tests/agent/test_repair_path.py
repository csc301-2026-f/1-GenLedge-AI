"""Invalid model output gets exactly one repair attempt, then a typed failure."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentBudgets
from app.agent.errors import INVALID_MODEL_OUTPUT
from app.agent.graph import run_routing_job
from app.agent.models import ModelResponse, build_fake_draft, parse_model_draft
from app.agent.repositories import SNAPSHOT_ID, seeded_repository
from app.agent.state import NODE_WRITES, validate_node_update

from .doubles import ScriptedModel

BUDGETS = AgentBudgets(max_tool_calls=5, max_model_calls=5)


def _valid_draft_json() -> str:
    repository = seeded_repository()
    inventory = repository.get_inventory(SNAPSHOT_ID)
    return build_fake_draft(inventory, None, None).model_dump_json()


def _run(model, *, budgets: AgentBudgets = BUDGETS):
    return run_routing_job(
        job_id="job-repair",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=model,
        budgets=budgets,
    )


def test_invalid_output_is_repaired_once_and_then_accepted():
    model = ScriptedModel(["not json at all", _valid_draft_json()])
    run = _run(model)

    assert run.failure is None
    assert run.model_draft is not None
    assert model.calls == 2
    assert model.repair_calls == 1
    assert model.requests[1].repair is True
    assert run.final_state["model_calls_used"] == 2
    assert run.final_state["model_draft"].revision == run.final_state["revision_count"]


def test_contract_violations_are_repaired_not_coerced():
    # `confidence` above 1.0 and an empty evidence list: both must be rejected.
    broken = (
        '{"revision": 0, "tables": [{"id": "orders", "name": "orders", "kind": "event", '
        '"grain": "one row per order", "key": ["order_id"], "attributes": '
        '[{"id": "order_id", "type": "text", "nullable": false, "evidence": [], '
        '"confidence": 1.4}], "relationships": [], "rationale": "ok"}], "source_coverage": []}'
    )
    model = ScriptedModel([broken, _valid_draft_json()])
    run = _run(model)

    assert run.failure is None
    assert model.calls == 2
    assert model.repair_calls == 1
    # the repair prompt carries the concrete validation errors, not a generic nudge
    assert "evidence" in model.requests[1].user or "confidence" in model.requests[1].user


def test_second_invalid_answer_fails_with_invalid_model_output():
    model = ScriptedModel(["still not json", "also not json"])
    run = _run(model)

    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert run.failure.retryable is False
    assert run.model_draft is None
    assert run.status == "failed"
    assert model.calls == 2, "exactly one repair attempt, never two"


def test_no_repair_is_attempted_twice_even_when_the_budget_allows_it():
    model = ScriptedModel(["{", "{", _valid_draft_json()])
    run = _run(model, budgets=AgentBudgets(max_tool_calls=5, max_model_calls=10))

    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert model.calls == 2
    assert model.repair_calls == 1
    assert model.queue, "the third scripted answer was never consumed"


def test_repair_is_skipped_when_the_model_budget_is_already_spent():
    model = ScriptedModel(["{"])
    run = _run(model, budgets=AgentBudgets(max_tool_calls=5, max_model_calls=1))

    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert model.calls == 1
    assert model.repair_calls == 0


def test_a_refusal_is_not_substituted_with_a_fabricated_draft():
    model = ScriptedModel([ModelResponse(error_code="model_refused", error_message="refused")])
    run = _run(model)

    assert run.failure is not None
    assert run.failure.code == "model_refused"
    assert run.model_draft is None


def test_no_tool_call_and_no_draft_enters_the_repair_path():
    model = ScriptedModel([ModelResponse(text="   ")])
    run = _run(model)

    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert model.repair_calls == 1


def test_parse_model_draft_reports_a_location_for_a_contract_breach():
    draft, error = parse_model_draft('{"revision": "3", "tables": []}')
    assert draft is None
    assert error is not None
    assert "revision" in error or "tables" in error


def test_a_node_cannot_write_a_field_it_does_not_own():
    validate_node_update("context", {"inventory_ref": "inventory:1"})
    with pytest.raises(ValueError, match="model_draft"):
        validate_node_update("context", {"model_draft": None})
    assert "model_draft" in NODE_WRITES["propose"]
    assert "model_draft" not in NODE_WRITES["context"]
