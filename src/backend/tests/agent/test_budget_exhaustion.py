"""Budget exhaustion ends the job with its own typed code, never a framework error."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentBudgets
from app.agent.errors import (
    INVALID_MODEL_OUTPUT,
    MODEL_CALL_BUDGET_EXHAUSTED,
    TOOL_BUDGET_EXHAUSTED,
)
from app.agent.graph import derived_recursion_limit, run_routing_job
from app.agent.repositories import SNAPSHOT_ID, seeded_repository
from app.agent.state import budget_exhausted
from app.agent.tools import FakeConnector, ToolCallRequest, ToolDispatcher

from .doubles import GreedyModel, ScriptedModel

ALL_BUDGETS_EXHAUSTED = {
    "tool_calls": TOOL_BUDGET_EXHAUSTED,
    "model_calls": MODEL_CALL_BUDGET_EXHAUSTED,
}


def test_tool_budget_exhaustion_is_typed_and_does_not_raise():
    repository = seeded_repository()
    connector = FakeConnector()
    budgets = AgentBudgets(max_tool_calls=1, max_model_calls=10)
    model = GreedyModel()
    run = run_routing_job(
        job_id="job-budget-tool",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=budgets,
        model=model,
    )
    assert run.failure is not None
    assert run.failure.code == TOOL_BUDGET_EXHAUSTED
    assert run.failure.retryable is False
    assert run.status == "failed"
    assert run.model_draft is None
    # the allowed call ran exactly once; the loop did not spend past the budget
    assert run.final_state["tool_calls_used"] == 1
    assert len(connector.calls) == 1
    assert run.final_state["model_calls_used"] <= budgets.max_model_calls


def test_a_cooperating_model_needs_less_than_its_budget():
    """One tool round finishes the fixture, so a small budget still succeeds."""

    run = run_routing_job(
        job_id="job-small-budget",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=1, max_model_calls=2),
    )
    assert run.failure is None
    assert run.final_state["tool_calls_used"] == 1
    assert run.final_state["model_calls_used"] == 2


def test_tool_budget_of_zero_fails_before_any_dispatch():
    repository = seeded_repository()
    connector = FakeConnector()
    run = run_routing_job(
        job_id="job-budget-tool-zero",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        connector=connector,
        budgets=AgentBudgets(max_tool_calls=0, max_model_calls=10),
    )
    assert run.failure is not None
    assert run.failure.code == TOOL_BUDGET_EXHAUSTED
    assert connector.calls == []
    assert run.final_state["tool_calls_used"] == 0


def test_model_budget_exhaustion_is_typed_and_does_not_raise():
    run = run_routing_job(
        job_id="job-budget-model",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=1),
    )
    assert run.failure is not None
    assert run.failure.code == MODEL_CALL_BUDGET_EXHAUSTED
    assert run.status == "failed"
    assert run.final_state["model_calls_used"] == 1


def test_durable_model_call_count_governs_the_budget():
    """The persisted count is the authority, so a crash loop cannot re-spend."""

    repository = seeded_repository(model_call_counts={"job-durable": 5})
    run = run_routing_job(
        job_id="job-durable",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=repository,
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=5),
    )
    assert run.failure is not None
    assert run.failure.code == MODEL_CALL_BUDGET_EXHAUSTED
    assert run.final_state["model_calls_used"] == 0, "no call was made"


def test_every_semantic_budget_has_its_own_code():
    assert set(ALL_BUDGETS_EXHAUSTED.values()) == {
        TOOL_BUDGET_EXHAUSTED,
        MODEL_CALL_BUDGET_EXHAUSTED,
    }
    assert len(ALL_BUDGETS_EXHAUSTED) == len(set(ALL_BUDGETS_EXHAUSTED.values()))


@pytest.mark.parametrize(
    ("budgets", "state", "expected"),
    [
        (AgentBudgets(max_tool_calls=2), {"tool_calls_used": 2}, "tool_calls"),
        (AgentBudgets(max_tool_calls=2), {"tool_calls_used": 1}, None),
        (AgentBudgets(max_tool_calls=9, max_model_calls=3), {"tool_calls_used": 0, "model_calls_used": 3}, "model_calls"),
        (AgentBudgets(max_tool_calls=9, max_model_calls=3, max_tokens=10), {"tokens_used": 10}, "tokens"),
    ],
)
def test_budget_predicate_is_checked_before_work(budgets, state, expected):
    assert budget_exhausted(budgets, state) == expected


def test_token_budget_stops_the_job_before_the_next_model_call():
    run = run_routing_job(
        job_id="job-budget-tokens",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=5, max_tokens=1),
    )
    assert run.failure is not None
    assert run.failure.code == MODEL_CALL_BUDGET_EXHAUSTED
    assert "token budget" in run.failure.message
    assert run.final_state["tokens_used"] > 1, "the spent tokens are recorded"
    assert len(run.model_responses) == 1, "exactly one call was made before the stop"


def test_tool_row_and_byte_caps_are_typed_results_not_crashes():
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=FakeConnector(),
        repository=repository,
        inventory=repository.get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(max_tool_rows=1),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-rows",
            name="sample_rows",
            arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
        ),
        job_id="job-rows",
        tool_calls_used=0,
    )
    assert outcome.result.status == "error"
    assert outcome.result.error_code == "budget_exhausted"
    assert outcome.charged is False


def test_recursion_limit_is_not_the_stopping_condition():
    """Every budget above stops through a typed code; the derivation sits above it."""

    budgets = AgentBudgets(max_tool_calls=40, max_model_calls=20)
    limit = derived_recursion_limit(budgets)
    assert limit > 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls
    cases = [
        (AgentBudgets(max_tool_calls=1, max_model_calls=10), GreedyModel(), "job-derived-1"),
        (AgentBudgets(max_tool_calls=10, max_model_calls=1), None, "job-derived-2"),
    ]
    for run_budgets, model, job_id in cases:
        run = run_routing_job(
            job_id=job_id,
            source_snapshot_ids=[SNAPSHOT_ID],
            repository=seeded_repository(),
            budgets=run_budgets,
            model=model,
        )
        assert run.failure is not None
        assert run.failure.code in set(ALL_BUDGETS_EXHAUSTED.values())


def test_a_scripted_model_still_respects_the_model_budget():
    scripted = ScriptedModel(["", ""])
    run = run_routing_job(
        job_id="job-budget-scripted",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=scripted,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=2),
    )
    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert len(scripted.requests) == 2, "the first call plus exactly one repair"
    assert run.final_state["model_calls_used"] == 2
    assert run.model_draft is None


def test_the_model_budget_is_checked_before_a_repair_call():
    scripted = ScriptedModel([""])
    run = run_routing_job(
        job_id="job-budget-repair",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=scripted,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=1),
    )
    assert run.failure is not None
    assert run.failure.code == INVALID_MODEL_OUTPUT
    assert scripted.calls == 1, "no budget was available for the repair call"
