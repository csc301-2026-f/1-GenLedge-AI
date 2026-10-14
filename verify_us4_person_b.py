"""Independent verification of the US4 Person B deliverable.

This is deliberately NOT the test suite. The suite asserts implementation details;
this script asserts the **requirements as written in the task**, from the outside,
using only the public entrypoints. If the suite and the implementation were wrong in
the same way, this still fails.

Run:
    python verify_us4_person_b.py
Exit code 0 = every checkable requirement holds. Any FAIL block says which one does
not and why. It needs `pydantic`; it does not need `langgraph`, Flask, a network, a
provider key or a database.
"""
from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src" / "backend"))

RESULTS: list[tuple[str, str, str]] = []


def check(requirement: str):
    """Register a requirement; the function body is the check."""

    def decorator(func):
        try:
            func()
        except Exception:  # noqa: BLE001 - a failed check is a report, not a crash
            RESULTS.append((requirement, "FAIL", traceback.format_exc(limit=3)))
        else:
            RESULTS.append((requirement, "PASS", ""))
        return func

    return decorator


# --- requirements ---------------------------------------------------------------

@check("Exactly three graph nodes")
def _three_nodes():
    from app.agent.graph import graph_shape

    shape = graph_shape()
    assert shape.nodes == ("context", "propose", "tool_call"), shape.nodes
    assert len(shape.nodes) == 3


@check("Graph is context -> propose <-> tool_call -> END")
def _edges():
    from app.agent.graph import DECLARED_CONDITIONAL_EDGES, DECLARED_EDGES
    from app.agent.graphs import END, START

    assert (START, "context") in DECLARED_EDGES
    assert ("tool_call", "propose") in DECLARED_EDGES
    assert DECLARED_CONDITIONAL_EDGES["context"]["end"] == END
    assert DECLARED_CONDITIONAL_EDGES["propose"]["tool_call"] == "tool_call"
    assert DECLARED_CONDITIONAL_EDGES["propose"]["end"] == END


@check("The compiled graph is a real callable graph")
def _compiled():
    from app.agent.graph import build_graph
    from app.agent.graphs import graph_runtime

    graph = build_graph()
    assert hasattr(graph, "invoke")
    print(f"    (graph runtime in use: {graph_runtime()})")


@check("The whole loop runs: one tool call, then a schema-valid ModelDraft")
def _loop():
    from app.agent.contracts import ModelDraft
    from app.agent.graph import run_routing_job
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository
    from app.agent.tools import FakeConnector

    connector = FakeConnector()
    run = run_routing_job(
        job_id="verify-loop",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        connector=connector,
    )
    assert run.failure is None, run.failure
    assert len(connector.calls) == 1, connector.calls
    name, arguments, _ = connector.calls[0]
    assert name in {"sample_rows", "profile_resource"}, name
    assert arguments["resource_id"] == "orders.lines[]", arguments
    assert isinstance(run.model_draft, ModelDraft)
    assert run.final_state["tool_calls_used"] == 1


@check("The fake model requests exactly one call, for orders.lines[]")
def _fake_target():
    from app.agent.models import FAKE_TARGET_RESOURCE, FakeModel, ModelRequest
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository

    model = FakeModel(inventory=seeded_repository().get_inventory(SNAPSHOT_ID))
    response = model.invoke(ModelRequest(node="propose", system="s", user="u", prompt_ref="p"))
    assert len(response.tool_calls) == 1, response.tool_calls
    assert response.tool_calls[0].arguments["resource_id"] == FAKE_TARGET_RESOURCE == "orders.lines[]"


@check("Invalid model output gets one repair attempt, then invalid_model_output")
def _repair():
    from app.agent.contracts import AgentBudgets
    from app.agent.graph import run_routing_job
    from app.agent.models import ModelRequest, ModelResponse
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository

    class Scripted:
        name = "scripted"

        def __init__(self):
            self.requests = []

        def invoke(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            return ModelResponse(text="definitely not json")

    model = Scripted()
    run = run_routing_job(
        job_id="verify-repair",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=model,
        budgets=AgentBudgets(max_tool_calls=5, max_model_calls=5),
    )
    assert run.failure is not None and run.failure.code == "invalid_model_output", run.failure
    assert run.model_draft is None, "a fabricated draft was produced"
    assert len(model.requests) == 2, [r.repair for r in model.requests]
    assert [r.repair for r in model.requests] == [False, True]


@check("A duplicate (job_id, tool_call_id) replays without a second connector call")
def _replay():
    from app.agent.contracts import AgentBudgets, ToolCallRequest
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository
    from app.agent.tools import FakeConnector, ToolDispatcher

    repository = seeded_repository()
    connector = FakeConnector()
    dispatcher = ToolDispatcher(
        connector=connector,
        repository=repository,
        inventory=repository.get_inventory(SNAPSHOT_ID),
        budgets=AgentBudgets(),
    )
    call = ToolCallRequest(
        id="verify-call",
        name="sample_rows",
        arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]", "limit": 3},
    )
    first = dispatcher.dispatch(call, job_id="verify-replay", tool_calls_used=0)
    second = dispatcher.dispatch(call, job_id="verify-replay", tool_calls_used=1)
    assert first.replayed is False and first.charged is True
    assert second.replayed is True and second.charged is False
    assert len(connector.calls) == 1, connector.calls


@check("Tool budget exhaustion is a typed failure, not a crash")
def _tool_budget():
    from app.agent.contracts import AgentBudgets, ToolCallRequest
    from app.agent.graph import run_routing_job
    from app.agent.models import ModelRequest, ModelResponse
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository
    from app.agent.tools import FakeConnector

    class Greedy:
        name = "greedy"

        def __init__(self):
            self.n = 0

        def invoke(self, request: ModelRequest) -> ModelResponse:
            self.n += 1
            return ModelResponse(
                tool_calls=[
                    ToolCallRequest(
                        id=f"greedy-{self.n}",
                        name="sample_rows",
                        arguments={"source_id": "source-orders-1", "resource_id": "orders.lines[]"},
                    )
                ],
                stop_reason="tool_use",
            )

    connector = FakeConnector()
    run = run_routing_job(
        job_id="verify-tool-budget",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        connector=connector,
        model=Greedy(),
        budgets=AgentBudgets(max_tool_calls=1, max_model_calls=10),
    )
    assert run.failure is not None and run.failure.code == "tool_budget_exhausted", run.failure
    assert len(connector.calls) == 1, connector.calls


@check("Model budget exhaustion is a typed failure, not a crash")
def _model_budget():
    from app.agent.contracts import AgentBudgets
    from app.agent.graph import run_routing_job
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository

    run = run_routing_job(
        job_id="verify-model-budget",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        budgets=AgentBudgets(max_tool_calls=10, max_model_calls=1),
    )
    assert run.failure is not None and run.failure.code == "model_call_budget_exhausted", run.failure


@check("GENLEDGE_MODEL_MODE=auto uses fake mode when provider variables are absent")
def _mode_auto():
    from app.agent.models import resolve_model_mode

    assert resolve_model_mode("auto", env={}).mode == "fake"
    assert resolve_model_mode(None, env={}).mode == "fake"
    assert resolve_model_mode("auto", env={"ANTHROPIC_API_KEY": "sk-x"}).mode == "live"


@check("GENLEDGE_MODEL_MODE=live without configuration is a typed error")
def _mode_live():
    from app.agent.errors import ModelConfigurationError
    from app.agent.models import resolve_model_mode

    try:
        resolve_model_mode("live", env={})
    except ModelConfigurationError as error:
        assert error.code == "model_configuration_error"
    else:
        raise AssertionError("live mode without provider configuration did not fail")


@check("Startup output identifies the resolved mode without exposing secrets")
def _banner():
    from app.agent.graph import startup_banner

    secret = "sk-ant-do-not-print-me"
    fake = startup_banner(env={})
    live = startup_banner(env={"ANTHROPIC_API_KEY": secret, "GENLEDGE_LLM_MODEL": "claude-opus-5-5"})
    assert "model_mode=fake" in fake, fake
    assert "model_mode=live" in live, live
    assert secret not in fake and secret not in live
    assert "sk-ant" not in fake + live


@check("Restricted values never reach the prompt (sentinel test)")
def _sentinels():
    from app.agent.contracts import AgentBudgets, FieldRef, InventoryField, InventoryView, ResourceSummary
    from app.agent.prompts import render_proposal_prompt

    org = "org-sentinel-9f3a"
    password = "hunter2-sentinel-password"
    dsn = "postgresql://user:pw@db.internal:5432/warehouse"
    reviewer = "reviewer-sentinel@example.com"
    client = "Sentinel Logistics Pty Ltd"
    card = "4111111111111111"
    inventory = InventoryView(
        snapshot_id="snapshot-sentinel",
        resources=[ResourceSummary(resource_id="orders", name=f"orders {client}", kind="collection", field_count=3)],
        fields=[
            InventoryField(
                ref=FieldRef(source_id="s", resource_id="orders", field_path="note"),
                type="text",
                nullable=True,
                repeating=False,
                samples=[f"dsn={dsn}", card],
                description=f"contact {reviewer}, password {password}",
                ambiguity=None,
                status="stable",
            )
        ],
    )
    rendered = render_proposal_prompt(
        job_id=org + "-job-1",
        inventory=inventory,
        catalogue=None,
        tool_results=[],
        budgets=AgentBudgets(),
    )
    # A resource *name* is deliberately projectable (US4-AC6 wants names), so the
    # restricted categories are asserted individually rather than by blocking every
    # field of the inventory.
    for label, value in (
        ("organization id", org),
        ("password", password),
        ("dsn", dsn),
        ("reviewer identity", reviewer),
        ("card number", card),
        ("field description", "contact"),
    ):
        assert value not in rendered.user, f"{label} leaked into the prompt"
    assert f"orders {client}" in rendered.user, "the resource name is a projection target"
    assert client not in rendered.user.replace(f"orders {client}", ""), "the name appears once"
    assert rendered.user.startswith("Job reference: org-sent"), rendered.user[:40]


@check("At most three samples per field reach the prompt")
def _sample_cap():
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository
    from app.agent.prompts import project_inventory

    projection = project_inventory(seeded_repository().get_inventory(SNAPSHOT_ID))
    for line in projection.splitlines():
        if "samples=" in line:
            values = [item for item in line.split("samples=", 1)[1].split(", ")]
            assert len(values) <= 3, line


@check("Source data containing {{...}} cannot crash or splice the prompt")
def _splice():
    from app.agent.contracts import AgentBudgets, FieldRef, InventoryField, InventoryView, ResourceSummary
    from app.agent.prompts import render_proposal_prompt

    injected = "a {{budgets}} b {{output_schema}} c {{"
    inventory = InventoryView(
        snapshot_id="snapshot-splice",
        resources=[ResourceSummary(resource_id="orders", name="orders", kind="collection", field_count=1)],
        fields=[
            InventoryField(
                ref=FieldRef(source_id="s", resource_id="orders", field_path="note"),
                type="text",
                nullable=True,
                repeating=False,
                samples=[injected],
                description=None,
                ambiguity=None,
                status="stable",
            )
        ],
    )
    rendered = render_proposal_prompt(
        job_id="job-splice",
        inventory=inventory,
        catalogue=None,
        tool_results=[],
        budgets=AgentBudgets(),
    )
    assert injected in rendered.user, "the value was mangled"
    source_block = rendered.user.split("<untrusted_source_data>")[1].split("</untrusted_source_data>")[0]
    assert "max_model_calls=" not in source_block, "another prompt block was spliced in"


@check("A typed tool error reaches the next prompt as data")
def _tool_error_projected():
    from app.agent.contracts import AgentBudgets
    from app.agent.prompts import render_proposal_prompt
    from app.agent.repositories import SNAPSHOT_ID, seeded_repository
    from app.agent.tools import ToolResult

    result = ToolResult(
        result_ref="tool:j:1",
        job_id="j",
        tool_call_id="call-err",
        tool="sample_rows",
        status="error",
        payload={},
        error_code="connector_timeout",
        message="the source did not answer",
    )
    rendered = render_proposal_prompt(
        job_id="j",
        inventory=seeded_repository().get_inventory(SNAPSHOT_ID),
        catalogue=None,
        tool_results=[result],
        budgets=AgentBudgets(),
    )
    assert "connector_timeout" in rendered.user, "the typed error was dropped"
    assert "call-err" in rendered.user


def _added_files() -> list[str]:
    return _git_diff(["--diff-filter=A"])


def _changed_files() -> list[str]:
    return _git_diff([])


#: The commit that froze the shared contracts (`plans/us4-four-person-task-split.md`
#: "Gate 0"). `contracts.py` came from the shared base here, not from this branch.
FROZEN_CONTRACT_COMMIT = "ca87e2a"
FROZEN_CONTRACT_PATH = "src/backend/app/agent/contracts.py"

#: `contracts.py` is frozen. The decision is that this branch does **not** modify it, so
#: there is no delta to declare: the file must equal the frozen blob exactly. An earlier
#: revision of this script accepted one declared delta (a `StrEnum` import swap); the team
#: decided against modifying the frozen contract, and the import was restored.
#:
#: The comparison is line-ending tolerant because `core.autocrlf=true` checks the file out
#: with CRLF on Windows while the committed blob is LF; the content is what is frozen. The
#: same normalisation is what makes the check meaningful pre-commit: it compares against
#: the *working tree*, so an uncommitted edit is caught.
FROZEN_CONTRACT_DELTAS: list[tuple[str, str]] = []


def _blob_at(commit: str, path: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.replace("\r\n", "\n")


def _normalised(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@check("The frozen contract is byte-identical to the frozen baseline")
def _frozen_contract():
    """`contracts.py` is frozen at Gate 0, and this is the check that can see it.

    The scope gate below filters on `startswith("src/backend/app/agent/")`, so
    `contracts.py` — which lives inside that prefix — was invisible to it by
    construction. This check compares the working-tree file against the frozen blob
    directly, so an uncommitted edit is caught as well as a committed one.

    `FROZEN_CONTRACT_DELTAS` is empty and is meant to stay empty: the decision on this
    branch is that the frozen contract is not modified. A non-empty list would be a
    declaration, not an approval, so the second check below fails if it ever grows.
    """

    frozen = _blob_at(FROZEN_CONTRACT_COMMIT, FROZEN_CONTRACT_PATH)
    assert frozen, (
        f"could not read {FROZEN_CONTRACT_PATH} at {FROZEN_CONTRACT_COMMIT}; "
        "the frozen baseline is missing, so this check cannot run"
    )
    current = _normalised(ROOT / FROZEN_CONTRACT_PATH)
    if current == frozen:
        return

    expected = frozen
    for old, new in FROZEN_CONTRACT_DELTAS:
        assert old in expected, (
            f"the declared delta {old!r} is no longer present in the frozen blob; "
            "the declaration is stale"
        )
        expected = expected.replace(old, new, 1)

    if current != expected:
        raise AssertionError(
            f"{FROZEN_CONTRACT_PATH} differs from the frozen baseline at "
            f"{FROZEN_CONTRACT_COMMIT}. A contract change needs team review and a "
            "version bump (plans/us4-four-person-task-split.md, Gate 0); this branch "
            "was told not to modify it."
        )


@check("No contracts.py delta is declared, and CONTRACT_VERSION is unchanged")
def _contract_delta_is_declared():
    """The frozen contract is unmodified, and no future edit can slip in as a "delta".

    A declaration list would let a later editor accept their own contract change by
    appending to it. There is nothing to declare here, so the list must stay empty, and
    `CONTRACT_VERSION` must still read `"1"` — a version bump is a team decision.
    """

    from app.agent.contracts import CONTRACT_VERSION

    assert CONTRACT_VERSION == "1", (
        f"CONTRACT_VERSION changed to {CONTRACT_VERSION!r}; a version bump is a team "
        "decision, not a local edit"
    )
    assert FROZEN_CONTRACT_DELTAS == [], (
        "a contracts.py delta was declared; this branch does not modify the frozen "
        "contract, and declaring a delta is not the same as the team approving one"
    )
    current = _normalised(ROOT / FROZEN_CONTRACT_PATH)
    assert "from enum import StrEnum" in current, (
        "the frozen import was changed; contracts.py must match the baseline verbatim"
    )
    assert "app.agent.compat" not in current, (
        "contracts.py must not import from the agent package; it is frozen"
    )


def _git_diff(extra: list[str]) -> list[str]:
    # Two-dot (`A B`), deliberately: this asks "what does the working tree differ by,
    # relative to the frozen base", so a file the *base* added is not reported as
    # branch work. `A...B` would answer the different question "what did this branch
    # change since the merge base".
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-only", *extra, FROZEN_CONTRACT_COMMIT, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


@check("Nothing on the 'do not implement' list was implemented")
def _scope():
    added = _added_files()
    changed = _changed_files()
    backend_added = [path for path in added if path.startswith("src/backend/")]
    # Person B owns `app/agent/models.py` (the model *adapters*). Everything else
    # named `models.py` would be a persistence model, which is Person A's.
    mine = [path for path in changed if path.startswith("src/backend/app/agent/")]
    others = [path for path in backend_added if path not in mine]

    # Person A's database schema and migrations.
    schema = [path for path in others if "migrations" in path or path.endswith("/models.py")]
    assert not schema, f"database schema files were added: {schema}"
    # Person D's Flask routes, HTTP request/response models and React components.
    routes = [path for path in others if path.endswith("routes.py") or path.endswith("api_schemas.py")]
    assert not routes, f"Flask routes or API schemas were added: {routes}"
    assert not [path for path in added if path.startswith("src/frontend/")], "frontend files were added"
    # Person C's deterministic validation rules.
    assert not [path for path in others if path.endswith("validation.py")], "validation rules were added"
    # A second contract definition anywhere outside app/agent.
    duplicates = [
        path for path in backend_added if path.endswith("contracts.py") and "app/agent" not in path
    ]
    assert not duplicates, f"a duplicate contract definition was added: {duplicates}"
    # The only files touched under app/ outside the agent package are the app factory
    # (to keep the harness importable without Flask) and nothing else.
    outside_agent = sorted(
        path
        for path in changed
        if path.startswith("src/backend/app/") and path not in mine
    )
    assert outside_agent == ["src/backend/app/__init__.py"], (
        f"unexpected files changed outside app/agent: {outside_agent}"
    )


# --- what this script cannot check, reported honestly ---------------------------


def _unverified() -> list[tuple[str, str]]:
    from app.agent.graphs import GRAPH_RUNTIME_AVAILABLE, graph_runtime

    items: list[tuple[str, str]] = []
    if GRAPH_RUNTIME_AVAILABLE:
        items.append(
            (
                "the graph was only exercised on one runtime",
                "langgraph is importable AND the local fallback exists; run on a "
                "checkout without langgraph to exercise the fallback",
            )
        )
    else:
        items.append(
            (
                "the graph does not run on the real langgraph.StateGraph",
                f"langgraph is not installed; `graph_runtime()` reports {graph_runtime()!r}. "
                "Install it and re-run: the node signature convention it injects "
                "(`runtime` by keyword) is then enforced by the suite",
            )
        )
    items.append(
        (
            "the live adapter has not talked to a real provider",
            "no API key and no network; the request shape is asserted against an SDK stub only",
        )
    )
    items.append(
        (
            "a job does not resume from a checkpoint",
            "no checkpointer: that half of the harness gate needs Person A's persistence",
        )
    )
    return items


def main() -> int:
    print("US4 Person B — requirement-level verification")
    print("=" * 64)
    failed = 0
    for requirement, status, detail in RESULTS:
        print(f"[{status}] {requirement}")
        if status == "FAIL":
            failed += 1
            print(detail.rstrip())
    print("=" * 64)
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} checkable requirements hold")
    print()
    print("NOT verified by this script (stated plainly):")
    for requirement, why in _unverified():
        print(f"  - {requirement}\n      {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
