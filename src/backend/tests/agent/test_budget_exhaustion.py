"""Budget exhaustion ends the job with its own typed code, never a framework error."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentBudgets
from app.agent.errors import (
    COST_BUDGET_EXHAUSTED,
    INVALID_MODEL_OUTPUT,
    MODEL_CALL_BUDGET_EXHAUSTED,
    TOKEN_BUDGET_EXHAUSTED,
    TOOL_BUDGET_EXHAUSTED,
    WALL_CLOCK_BUDGET_EXHAUSTED,
)
from app.agent.graph import derived_recursion_limit, run_routing_job
from app.agent.repositories import SNAPSHOT_ID, seeded_repository
from app.agent.state import budget_exhausted
from app.agent.tools import ConnectorError, FakeConnector, ToolCallRequest, ToolDispatcher

from .doubles import inventory, GreedyModel, ScriptedModel

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


def test_the_recursion_derivation_binds_above_the_floor():
    """The derivation must be the binding term for large budgets, not dead arithmetic.

    With the default budgets the floor wins (200 vs 184), so a mutation that reduced
    the derivation to the floor alone survived every test. Large budgets make the
    derivation the larger term, which is the configuration this function exists for.
    """

    huge = AgentBudgets(max_tool_calls=5_000, max_model_calls=5_000, recursion_limit=200)
    limit = derived_recursion_limit(huge)
    assert limit > huge.recursion_limit, "the derivation binds, not the floor"
    assert limit > 2 * huge.max_tool_calls + 2 * huge.max_model_calls

    # and the floor still wins when the derivation is smaller
    tiny = AgentBudgets(max_tool_calls=1, max_model_calls=1, recursion_limit=10_000)
    assert derived_recursion_limit(tiny) == 10_000


def test_the_local_runner_backstop_is_mapped_to_a_typed_failure():
    """The runtime's own recursion limit must not escape as a framework error."""

    from app.agent.graph import _recursion_failure
    from app.agent.repositories import SNAPSHOT_ID
    from app.agent.state import initial_state

    state = initial_state(
        job_id="job-backstop",
        source_snapshot_ids=[SNAPSHOT_ID],
        budgets=AgentBudgets(),
        model_mode="fake",
    )
    failed = _recursion_failure(state, "the runner stopped here")
    assert failed["status"] == "failed"
    assert failed["failure"] is not None
    assert failed["failure"].code == "recursion_limit_exceeded"
    assert failed["failure"].retryable is False


def test_the_local_runner_stops_at_its_own_recursion_limit():
    """`LocalGraphRunner`'s backstop is reachable and raises the mapped error."""

    from app.agent.graphs import LocalStateGraph, RecursionLimitExceeded
    from app.agent.state import RoutingJobState

    builder = LocalStateGraph(RoutingJobState)

    def loop(state, runtime=None):  # noqa: ARG001 - a node that never terminates
        return {"job_id": "spinning"}

    builder.add_node("spin", loop)
    builder.add_edge("__start__", "spin")
    builder.add_edge("spin", "spin")
    graph = builder.compile()

    with pytest.raises(RecursionLimitExceeded):
        graph.invoke({"job_id": "spinning"}, config={"recursion_limit": 3})


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


def test_every_semantic_budget_code_is_distinct():
    """Four budgets, four codes: a stop must name the budget that actually fired."""

    codes = {
        TOOL_BUDGET_EXHAUSTED,
        MODEL_CALL_BUDGET_EXHAUSTED,
        TOKEN_BUDGET_EXHAUSTED,
        COST_BUDGET_EXHAUSTED,
        WALL_CLOCK_BUDGET_EXHAUSTED,
    }
    assert len(codes) == 5
    assert TOOL_BUDGET_EXHAUSTED != MODEL_CALL_BUDGET_EXHAUSTED


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
    assert run.failure.code == TOKEN_BUDGET_EXHAUSTED
    assert "token budget" in run.failure.message
    assert run.final_state["tokens_used"] > 1, "the spent tokens are recorded"
    assert len(run.model_responses) == 1, "exactly one call was made before the stop"


def test_wall_clock_budget_stops_the_job_with_its_own_code():
    run = run_routing_job(
        job_id="job-budget-clock",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=5, max_wall_clock_seconds=0),
    )
    assert run.failure is not None
    assert run.failure.code == WALL_CLOCK_BUDGET_EXHAUSTED
    assert run.model_draft is None


def test_cost_budget_stops_the_job_when_a_price_is_configured():
    runtime_price = 1000.0  # $1000 per 1k tokens: the first call already exceeds $5
    run = run_routing_job(
        job_id="job-budget-cost",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=5, max_cost_usd=5.0),
        cost_per_1k_tokens_usd=runtime_price,
    )
    assert run.failure is not None
    assert run.failure.code == COST_BUDGET_EXHAUSTED
    assert len(run.model_responses) == 1


def test_cost_budget_is_not_evaluated_without_a_configured_price():
    """No price means the ceiling cannot be evaluated — it must not be guessed."""

    run = run_routing_job(
        job_id="job-budget-cost-unpriced",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=5, max_cost_usd=0.0),
    )
    assert run.failure is None
    assert run.model_draft is not None


def test_the_byte_cap_is_enforced_with_its_own_typed_result():
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=FakeConnector(),
        repository=repository,
        inventory=inventory(),
        budgets=AgentBudgets(max_tool_bytes=40),
    )
    outcome = dispatcher.dispatch(
        ToolCallRequest(
            id="call-bytes",
            name="sample_rows",
            arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
        ),
        job_id="job-bytes",
        tool_calls_used=0,
    )
    assert outcome.result.status == "error"
    assert outcome.result.error_code == "budget_exhausted"
    assert "max_tool_bytes" in (outcome.result.message or "")
    assert outcome.charged is True, "the read happened, so it counts against the budget"
    # persisted, so a retry of the same id replays this verdict instead of re-reading a
    # source that may have changed -- the read is evidence about the source either way
    assert repository.get_tool_result("job-bytes", "call-bytes") is not None
    replay = dispatcher.dispatch(
        ToolCallRequest(
            id="call-bytes",
            name="sample_rows",
            arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
        ),
        job_id="job-bytes",
        tool_calls_used=1,
    )
    assert replay.replayed is True and replay.charged is False
    connector = dispatcher.connector
    assert isinstance(connector, FakeConnector)
    assert len(connector.calls) == 1, "a capped result is not re-read"


def test_tool_row_and_byte_caps_are_typed_results_not_crashes():
    repository = seeded_repository()
    dispatcher = ToolDispatcher(
        connector=FakeConnector(),
        repository=repository,
        inventory=inventory(),
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
    assert outcome.charged is True, "the read happened, so it counts against the budget"


def test_repeatedly_failing_tool_calls_still_exhaust_the_tool_budget():
    """A source that fails every read must not make the loop bound free.

    If a failed call were not charged, a model that keeps asking for an unreachable
    tool would never exhaust `max_tool_calls`, and the graph's only bound on that loop
    would stop applying exactly when the loop is most likely to run away.
    """

    connector = _AlwaysFailingConnector()
    repository = seeded_repository()
    budgets = AgentBudgets(max_tool_calls=2, max_model_calls=10)
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=inventory(),
        budgets=budgets,
    )

    charged = 0
    for index in range(5):
        outcome = dispatcher.dispatch(
            ToolCallRequest(
                id=f"failing-{index}",
                name="sample_rows",
                arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
            ),
            job_id="job-failing",
            tool_calls_used=charged,
        )
        assert outcome.result.status == "error"
        if outcome.charged:
            charged += 1

    assert charged == budgets.max_tool_calls, "the failing loop was bounded by the budget"
    assert len(connector.calls) == budgets.max_tool_calls, "no call beyond the budget reached the source"
    # the third attempt onward is refused before dispatch, and says why
    refused = dispatcher.dispatch(
        ToolCallRequest(id="failing-late", name="sample_rows", arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]"}),
        job_id="job-failing",
        tool_calls_used=charged,
    )
    assert refused.result.error_code == "budget_exhausted"
    assert refused.charged is False


class _AlwaysFailingConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, name: str, arguments: dict, job_id: str) -> dict:
        self.calls.append((name, dict(arguments), job_id))
        raise ConnectorError("connector_error", "this source never answers")


def test_recursion_limit_is_not_the_stopping_condition():
    """Each budget stops through its own typed code; the derivation sits above them."""

    budgets = AgentBudgets(max_tool_calls=40, max_model_calls=20)
    limit = derived_recursion_limit(budgets)
    assert limit > 2 * budgets.max_tool_calls + 2 * budgets.max_model_calls
    cases = [
        (AgentBudgets(max_tool_calls=1, max_model_calls=10), GreedyModel(), "job-derived-1", TOOL_BUDGET_EXHAUSTED),
        (AgentBudgets(max_tool_calls=10, max_model_calls=1), None, "job-derived-2", MODEL_CALL_BUDGET_EXHAUSTED),
    ]
    for run_budgets, model, job_id, expected in cases:
        run = run_routing_job(
            job_id=job_id,
            source_snapshot_ids=[SNAPSHOT_ID],
            repository=seeded_repository(),
            budgets=run_budgets,
            model=model,
        )
        assert run.failure is not None
        assert run.failure.code == expected
        # The framework's own limit never fired; the semantic budget did.
        assert run.failure.code != "recursion_limit_exceeded"


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
