"""Mode resolution and fake/live adapter compatibility."""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from app.agent.contracts import AgentBudgets, InventoryView, ModelDraft
from app.agent.errors import MODEL_CONFIGURATION_ERROR, ModelConfigurationError
from app.agent.graph import log_resolved_mode, run_routing_job, startup_banner
from app.agent.models import (
    FAKE_MODEL_ID,
    FAKE_PROVIDER,
    FAKE_TOOL_CALL_ID,
    FakeModel,
    LiveModel,
    ModelRequest,
    ModelResponse,
    build_model_client,
    parse_model_draft,
    provider_configured,
    resolve_model_mode,
)
from app.agent.prompts import render_proposal_prompt
from app.agent.repositories import SNAPSHOT_ID, seeded_repository

from .doubles import inventory


def _inventory() -> InventoryView:
    return inventory()


def _proposal_request() -> ModelRequest:
    rendered = render_proposal_prompt(
        job_id="job-abcdef12345",
        inventory=_inventory(),
        catalogue=None,
        tool_results=[],
        budgets=AgentBudgets(),
    )
    return ModelRequest(
        node="propose",
        system=rendered.system,
        user=rendered.user,
        prompt_ref=rendered.ref,
        job_id="job-abcdef12345",
    )


# --- mode resolution -----------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "env", "expected"),
    [
        ("fake", {}, "fake"),
        ("fake", {"ANTHROPIC_API_KEY": "sk-live"}, "fake"),
        ("live", {"ANTHROPIC_API_KEY": "sk-live"}, "live"),
        ("auto", {"ANTHROPIC_API_KEY": "sk-live"}, "live"),
        ("auto", {}, "fake"),
        (None, {}, "fake"),
        (None, {"GENLEDGE_LLM_API_KEY": "sk"}, "live"),
        (None, {"OPENAI_API_KEY": "sk"}, "live"),
        # An endpoint is configuration even without a key: the gateway may inject one.
        (None, {"GENLEDGE_LLM_BASE_URL": "https://gw.example/v1"}, "live"),
        # A provider *name* is not: nothing can authenticate with it, so `auto` must
        # fall back rather than send every job into a configuration error.
        (None, {"GENLEDGE_LLM_PROVIDER": "anthropic"}, "fake"),
        ("auto", {"GENLEDGE_LLM_PROVIDER": "anthropic"}, "fake"),
    ],
)
def test_mode_resolution(requested, env, expected):
    assert resolve_model_mode(requested, env=env).mode == expected


def test_auto_does_not_choose_live_without_something_to_authenticate_with():
    """`auto` means "live only if it could work", not "live if a name is set".

    Treating a provider name as configuration sent every job down the live path and
    failed it with `model_configuration_error` — a fleet-wide outage from one harmless
    variable. `live` explicitly still refuses, which is the loud path.
    """

    assert provider_configured({"GENLEDGE_LLM_PROVIDER": "anthropic"}) is False
    assert resolve_model_mode("auto", env={"GENLEDGE_LLM_PROVIDER": "anthropic"}).mode == "fake"
    # explicit `live` is a deliberate instruction, so it fails loudly instead
    with pytest.raises(ModelConfigurationError):
        resolve_model_mode("live", env={"GENLEDGE_LLM_PROVIDER": "anthropic"})


def test_live_mode_without_provider_configuration_is_a_typed_error():
    with pytest.raises(ModelConfigurationError) as caught:
        resolve_model_mode("live", env={})
    assert caught.value.code == MODEL_CONFIGURATION_ERROR
    assert caught.value.retryable is False
    assert "GENLEDGE_MODEL_MODE=live" in caught.value.message


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ModelConfigurationError):
        resolve_model_mode("recorded", env={})


def test_auto_mode_uses_the_fake_model_when_provider_variables_are_absent():
    resolved = resolve_model_mode("auto", env={})
    assert resolved.mode == "fake"
    assert provider_configured({}) is False
    model = build_model_client(resolved, inventory=_inventory(), env={})
    assert isinstance(model, FakeModel)


def test_startup_banner_identifies_the_mode_and_exposes_no_secret():
    secret = "sk-ant-super-secret-value"
    fake = startup_banner(env={})
    assert "model_mode=fake" in fake
    assert FAKE_PROVIDER in fake and FAKE_MODEL_ID in fake

    live = startup_banner(env={"ANTHROPIC_API_KEY": secret, "GENLEDGE_LLM_MODEL": "claude-opus-5-5"})
    assert "model_mode=live" in live
    assert "claude-opus-5-5" in live
    assert secret not in live
    assert "sk-ant" not in live


def test_startup_banner_for_an_explicit_live_mode_carries_no_secret():
    """A resolved live mode prints provider and model only — never the key."""

    secret = "sk-ant-live-secret"
    resolved = resolve_model_mode("live", env={"ANTHROPIC_API_KEY": secret})
    banner = startup_banner(mode=resolved)
    assert "model_mode=live" in banner
    assert secret not in banner
    assert "ANTHROPIC_API_KEY" not in banner


def test_log_resolved_mode_reports_rather_than_crashes_on_missing_configuration(monkeypatch):
    """Importing the package must never fail because a deployment is half-configured."""

    monkeypatch.setenv("GENLEDGE_MODEL_MODE", "live")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GENLEDGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GENLEDGE_LLM_PROVIDER", raising=False)
    assert log_resolved_mode() is None

    monkeypatch.setenv("GENLEDGE_MODEL_MODE", "fake")
    assert "model_mode=fake" in (log_resolved_mode() or "")


# --- fake adapter --------------------------------------------------------------


def test_fake_adapter_requests_one_tool_call_then_a_valid_draft():
    model = FakeModel(inventory=_inventory())
    request = _proposal_request()

    first = model.invoke(request)
    assert len(first.tool_calls) == 1
    call = first.tool_calls[0]
    assert call.id == FAKE_TOOL_CALL_ID
    assert call.name in {"sample_rows", "profile_resource"}
    assert call.arguments["resource_id"] == "orders.lines[]"
    assert call.arguments["fields"], "the repeating array's fields are requested"

    # once the loop has recorded a result, the same adapter answers with a draft
    from app.agent.tools import ToolResult

    recorded = ToolResult(
        result_ref="tool:job:1",
        job_id="job-abcdef12345",
        tool_call_id=FAKE_TOOL_CALL_ID,
        tool=call.name,
        status="ok",
        payload={"resource_id": "orders.lines[]", "evidence_ref": "profile-1", "row_count": 42},
        redacted=True,
    )
    second_request = ModelRequest(
        node=request.node,
        system=request.system,
        user=request.user,
        prompt_ref=request.prompt_ref,
        job_id=request.job_id,
        results=(recorded,),
    )
    second = model.invoke(second_request)
    draft, error = parse_model_draft(second.text)
    assert error is None
    assert isinstance(draft, ModelDraft)
    assert draft.tables


# --- live adapter --------------------------------------------------------------


class _StubBlock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _StubUsage:
    input_tokens = 11
    output_tokens = 7


class _StubResponse:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.usage = _StubUsage()
        self.stop_reason = stop_reason


class _StubMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads: list[dict] = []

    def create(self, **payload):
        self.payloads.append(payload)
        return self.responses.pop(0)


class _StubAnthropic:
    """A stand-in for the provider SDK, installed only for the duration of a test."""

    last: "_StubAnthropic | None" = None

    def __init__(self, responses, **kwargs):
        self.kwargs = kwargs
        self.messages = _StubMessages(responses)
        _StubAnthropic.last = self


@pytest.fixture
def stub_anthropic(monkeypatch):
    def install(responses):
        module = types.ModuleType("anthropic")

        def factory(**kwargs):
            return _StubAnthropic(responses, **kwargs)

        module.Anthropic = factory  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "anthropic", module)
        return module

    return install


def test_live_adapter_sends_the_sdk_payload_and_returns_a_validated_draft(stub_anthropic):
    draft_text = _fake_draft_json()
    stub_anthropic([_StubResponse([_StubBlock(type="text", text=draft_text)])])
    model = LiveModel(api_key="sk-test", model="claude-opus-5-5")
    response = model.invoke(_proposal_request())

    assert response.error_code is None
    assert response.input_tokens == 11 and response.output_tokens == 7
    parsed, error = parse_model_draft(response.text)
    assert error is None and parsed is not None

    assert _StubAnthropic.last is not None
    payload = _StubAnthropic.last.messages.payloads[0]
    assert payload["model"] == "claude-opus-5-5"
    assert payload["system"]
    assert payload["messages"][0]["role"] == "user"
    assert payload["output_format"]["schema"]["title"] == "ModelDraft"


def test_live_adapter_returns_provider_tool_calls_as_typed_requests(stub_anthropic):
    stub_anthropic(
        [
            _StubResponse(
                [
                    _StubBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="sample_rows",
                        input={"source_id": "source-orders-1", "resource_id": "orders.lines[]"},
                    )
                ],
                stop_reason="tool_use",
            )
        ]
    )
    response = LiveModel(api_key="sk-test").invoke(_proposal_request())
    assert response.error_code is None
    assert [call.name for call in response.tool_calls] == ["sample_rows"]
    assert response.tool_calls[0].arguments["resource_id"] == "orders.lines[]"


def test_live_adapter_reports_a_refusal_without_substituting_output(stub_anthropic):
    stub_anthropic([_StubResponse([], stop_reason="refusal")])
    response = LiveModel(api_key="sk-test").invoke(_proposal_request())
    assert response.error_code == "model_refused"
    assert response.text == ""


def test_live_adapter_maps_a_provider_exception_to_a_typed_code(stub_anthropic, monkeypatch):
    module = stub_anthropic([])

    class _Boom:
        def __init__(self, **kwargs):
            self.messages = self

        def create(self, **payload):
            raise RuntimeError("connection reset")

    module.Anthropic = lambda **kwargs: _Boom()  # type: ignore[attr-defined]
    response = LiveModel(api_key="sk-test").invoke(_proposal_request())
    assert response.error_code == "model_unavailable"
    assert response.error_message is not None
    assert "connection reset" in response.error_message


def test_live_adapter_without_the_sdk_is_a_typed_configuration_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    response = LiveModel(api_key="sk-test").invoke(_proposal_request())
    assert response.error_code == MODEL_CONFIGURATION_ERROR
    assert response.error_message is not None
    assert "anthropic" in response.error_message


def test_live_adapter_without_a_key_is_a_typed_configuration_error(stub_anthropic):
    stub_anthropic([])
    response = LiveModel(api_key=None).invoke(_proposal_request())
    assert response.error_code == MODEL_CONFIGURATION_ERROR


# --- adapter compatibility -----------------------------------------------------


def test_both_adapters_satisfy_the_same_client_contract(stub_anthropic):
    """One interface, two adapters: same call shape, same return type."""

    stub_anthropic([_StubResponse([_StubBlock(type="text", text=_fake_draft_json())])])
    request = _proposal_request()
    for client in (FakeModel(inventory=_inventory()), LiveModel(api_key="sk-test")):
        assert isinstance(client.name, str) and client.name
        assert list(inspect.signature(client.invoke).parameters) == ["request"]
        assert isinstance(client.invoke(request), ModelResponse)


def test_both_adapters_produce_a_graph_that_ends_with_a_schema_valid_draft(stub_anthropic):
    draft_text = _fake_draft_json()

    # (a) fake adapter, no provider at all
    fake_run = run_routing_job(
        job_id="job-adapters-fake",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=FakeModel(inventory=_inventory()),
    )
    assert fake_run.failure is None
    assert isinstance(fake_run.model_draft, ModelDraft)

    # (b) live adapter driven by the SDK stub through the same nodes
    stub_anthropic(
        [
            _StubResponse(
                [
                    _StubBlock(
                        type="tool_use",
                        id=FAKE_TOOL_CALL_ID,
                        name="sample_rows",
                        input={
                            "source_id": "source-orders-1",
                            "resource_id": "orders.lines[]",
                            "limit": 3,
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            _StubResponse([_StubBlock(type="text", text=draft_text)]),
        ]
    )
    live_run = run_routing_job(
        job_id="job-adapters-live",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=LiveModel(api_key="sk-test"),
    )
    assert live_run.failure is None
    assert isinstance(live_run.model_draft, ModelDraft)
    assert live_run.final_state["tool_calls_used"] == 1
    assert live_run.final_state["model_calls_used"] == 2
    # the two adapters reach the same proposal shape from the same inventory
    assert {table.id for table in live_run.model_draft.tables} == {
        table.id for table in fake_run.model_draft.tables
    }


def _fake_draft_json() -> str:
    from app.agent.models import build_fake_draft

    return build_fake_draft(_inventory(), None, None).model_dump_json()


def test_a_typed_error_response_ends_the_graph_as_failed_not_as_a_draft():
    run = run_routing_job(
        job_id="job-adapter-error",
        source_snapshot_ids=[SNAPSHOT_ID],
        repository=seeded_repository(),
        model=_FailingModel(),
    )
    assert run.failure is not None
    assert run.failure.code == "model_unavailable"
    assert run.model_draft is None


class _FailingModel:
    name = "failing"

    def invoke(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(error_code="model_unavailable", error_message="provider down")
