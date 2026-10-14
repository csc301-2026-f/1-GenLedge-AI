"""Model adapters and model-mode resolution.

Two implementations share one interface:

* `FakeModel` — deterministic, no network, no key. It drives the **real** graph
  through a real tool call and then returns a schema-valid `ModelDraft`, which is
  what lets the harness gate at `doc/agent-harness-architecture.md` line 238 be
  demonstrated without a provider.
* `LiveModel` — the provider SDK, native tool binding and native structured
  output. It is the only module that knows a provider exists; a provider error is
  returned as a typed `ModelResponse.error_code`, never raised into the graph.

`GENLEDGE_MODEL_MODE=auto|live|fake` selects between them. `auto` uses the live
path only when provider configuration is present, and otherwise uses the fake
model. Startup output names the resolved mode and never a secret.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, TypedDict

from pydantic import ValidationError

from app.agent.contracts import (
    Attribute,
    Disposition,
    EvidenceRef,
    InventoryView,
    ModelDraft,
    Relationship,
    SourceCoverage,
    Table,
    ToolCallRequest,
)
from app.agent.errors import MODEL_REFUSED, MODEL_UNAVAILABLE, ModelConfigurationError
from app.agent.repositories import CatalogueView
from app.agent.tools import ToolResult

ModelMode = Literal["fake", "live"]

FAKE_PROVIDER = "deterministic-fake"
FAKE_MODEL_ID = "genledge-fake-routing-v1"

#: The one call the fake model makes. US4 §3 names `orders.lines[]` as the natural
#: single call, and this id makes the request stable across replays.
FAKE_TOOL_CALL_ID = "fake-tool-call-1"
FAKE_TARGET_RESOURCE = "orders.lines[]"

#: Variables that *name* a provider. Presence alone is not configuration: a deployment
#: that sets only `GENLEDGE_LLM_PROVIDER` has nothing to authenticate with, so treating
#: it as configured sent `auto` to the live path and made **every** job fail with
#: `model_configuration_error` instead of falling back to the fake model.
PROVIDER_NAME_ENV_VARS = ("GENLEDGE_LLM_PROVIDER",)

#: Variables that are configuration: something to authenticate with, or somewhere to
#: send the request. Either is enough for `auto` to choose the live path.
PROVIDER_CREDENTIAL_ENV_VARS = (
    "GENLEDGE_LLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GENLEDGE_LLM_BASE_URL",
    "ANTHROPIC_BASE_URL",
)

#: Every variable the mode resolver looks at, for diagnostics and error messages.
PROVIDER_ENV_VARS = PROVIDER_CREDENTIAL_ENV_VARS + PROVIDER_NAME_ENV_VARS


@dataclass(frozen=True)
class ModelRequest:
    """One model invocation. The client performs exactly one call per request."""

    node: str
    system: str
    user: str
    prompt_ref: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    job_id: str = ""
    repair: bool = False
    #: The recorded tool results the prompt projected. Supplied so a deterministic
    #: adapter can reason about the same evidence a provider would read, without
    #: re-parsing the rendered prompt.
    results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class ModelResponse:
    """Either tool calls, a raw structured answer, or a typed provider failure."""

    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelClient(Protocol):
    """The seam every node uses. Implementations never raise for provider trouble."""

    name: str

    def invoke(self, request: ModelRequest) -> ModelResponse:
        """Perform one structured call (with any bound tools) and return its result."""


# --- output parsing ------------------------------------------------------------


def parse_model_draft(text: str) -> tuple[ModelDraft | None, str | None]:
    """Validate a raw model answer against `ModelDraft`.

    Returns `(draft, None)` or `(None, message)`. Never raises: a contract breach
    is the repair path's input, not a crash.
    """

    candidate = (text or "").strip()
    if not candidate:
        return None, "empty response"
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        return None, f"response is not valid JSON: {error.msg} at position {error.pos}"
    try:
        return ModelDraft.model_validate(payload), None
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
        return None, f"{location}: {first.get('msg', 'invalid')}"


# --- fake model ----------------------------------------------------------------


#: Arguments for `Relationship`, keyed by its **wire aliases**. `Relationship.from_ref`
#: is aliased to `from`, a Python keyword, so the value can only be supplied by
#: unpacking a mapping; naming that mapping's type keeps the unpacking type-checked
#: instead of widening every field to `object`. The functional form is required
#: because the `class` syntax cannot express a keyword-named key.
_RelationshipArgs = TypedDict(
    "_RelationshipArgs",
    {
        "from": str,
        "to_ref": str,
        "cardinality": Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"],
        "evidence": list[EvidenceRef],
    },
)


def _evidence(result: ToolResult | None, resource_id: str, field_path: str) -> list[EvidenceRef]:
    profile_ref = None
    if result is not None:
        profile_ref = str(result.payload.get("evidence_ref") or result.result_ref)
    return [EvidenceRef(resource_id=resource_id, field_path=field_path, profile_ref=profile_ref)]


def build_fake_draft(inventory: InventoryView, catalogue: CatalogueView | None, result: ToolResult | None) -> ModelDraft:
    """The deterministic proposal the fake model returns.

    It is derived from the inventory, cites the recorded tool result as evidence,
    covers every discovered field exactly once, and reuses a catalogue table when
    one exists. `is_new` is deliberately absent: the application computes it from
    `catalog_ref`, the model does not author it (`plans/us4-four-person-task-split.md`).
    """

    by_path = {field.ref.field_path: field for field in inventory.fields}
    lines = [field for field in inventory.fields if field.ref.field_path.startswith("lines[].")]
    order_fields = [
        field
        for field in inventory.fields
        if field.ref.resource_id == "orders" and not field.ref.field_path.startswith("lines[]")
    ]
    customer_fields = [field for field in inventory.fields if field.ref.resource_id == "customers"]

    reused = {table.table_id for table in (catalogue.tables if catalogue else [])}
    order_table_id = "fact_orders" if "fact_orders" in reused else "orders"

    attributes = [
        Attribute(
            id=field.ref.field_path,
            type=field.type,
            nullable=field.nullable,
            evidence=_evidence(result, field.ref.resource_id, field.ref.field_path),
            confidence=0.9,
            ambiguity=field.ambiguity,
        )
        for field in order_fields
    ]
    line_attributes = [
        Attribute(
            id=field.ref.field_path.split("].", 1)[1] if "]." in field.ref.field_path else field.ref.field_path,
            type=field.type,
            nullable=field.nullable,
            evidence=_evidence(result, field.ref.resource_id, field.ref.field_path),
            confidence=0.88,
        )
        for field in lines
    ]
    customer_attributes = [
        Attribute(
            id=field.ref.field_path,
            type=field.type,
            nullable=field.nullable,
            evidence=_evidence(result, field.ref.resource_id, field.ref.field_path),
            confidence=0.9,
            ambiguity=field.ambiguity,
        )
        for field in customer_fields
    ]

    def key_of(items: list[Attribute]) -> list[str]:
        """A merge key for an attribute set.

        Callers only reach here with attributes, because the table that would have an
        empty set is not emitted at all — that was the actual B1-adjacent defect: the
        orders table used to be built unconditionally and indexed `items[0]`, so a
        snapshot scoped to just `orders.lines[]` raised `IndexError` out of
        `run_routing_job`. The precondition is asserted rather than silently patched,
        so a future caller that breaks it fails loudly here.
        """

        assert items, "a table is only emitted when it has attributes"

        identifiers = [item.id for item in items if item.id.endswith("_id")]
        return identifiers[:1] or [items[0].id]

    tables: list[Table] = []
    if attributes:
        tables.append(
            Table(
                id=order_table_id,
                name=order_table_id,
                kind="event",
                grain="one row per source order",
                key=key_of(attributes),
                attributes=attributes,
                relationships=[],
                rationale="Preserves the source order grain, its identifiers and its merge key.",
            )
        )
    if line_attributes:
        tables.append(
            Table(
                id="fact_order_lines",
                name="fact_order_lines",
                kind="event",
                grain="one row per order line",
                key=key_of(line_attributes),
                attributes=line_attributes,
                relationships=(
                    [
                        # `Relationship.from_ref` carries the wire alias `from`, a
                        # Python keyword, so the arguments go through a typed mapping
                        # and are unpacked. The wire shape is pinned by
                        # `test_the_fake_draft_serialises_the_from_alias`.
                        Relationship(
                            **_RelationshipArgs(
                                **{
                                    "from": f"fact_order_lines.{key_of(line_attributes)[0]}",
                                    "to_ref": f"{order_table_id}.{key_of(attributes)[0]}",
                                    "cardinality": "many_to_one",
                                    "evidence": _evidence(result, "orders.lines[]", "lines[].line_id"),
                                }
                            )
                        )
                    ]
                    if attributes
                    else []
                ),
                rationale="Expands the repeating lines[] structure into its own event table.",
            )
        )
    if customer_attributes:
        customer_table_id = "dim_customers" if "dim_customers" in reused else "customers"
        tables.append(
            Table(
                id=customer_table_id,
                name=customer_table_id,
                kind="entity",
                grain="one row per customer",
                key=key_of(customer_attributes),
                attributes=customer_attributes,
                relationships=[],
                rationale="Keeps customer attributes addressable for later joins.",
            )
        )

    line_keys = {item.id for item in line_attributes}

    def represented(field) -> bool:
        path = field.ref.field_path
        if path == "lines[]":
            return False
        if path.startswith("lines[]."):
            return path.split("].", 1)[-1] in line_keys
        return True

    coverage = [
        SourceCoverage(
            field_path=field.ref.field_path,
            resource_id=field.ref.resource_id,
            disposition=Disposition.REPRESENTED,
            reason=f"Represented in {_owning_table(field.ref.resource_id, order_table_id)}.",
        )
        for field in inventory.fields
        if represented(field)
    ]
    if by_path.get("lines[]") is not None:
        coverage.append(
            SourceCoverage(
                field_path="lines[]",
                resource_id="orders.lines[]",
                disposition=Disposition.REPRESENTED,
                reason="Expanded into fact_order_lines rather than flattened onto the order.",
            )
        )
    unresolved = []
    for field in inventory.fields:
        if field.ambiguity:
            unresolved.append(
                f"{field.ref.resource_id}.{field.ref.field_path}: {field.ambiguity} is unresolved; "
                "a reviewer must confirm the date format before it is used."
            )
    return ModelDraft(
        revision=0,
        tables=tables,
        source_coverage=coverage,
        unresolved=unresolved,
        notes="Deterministic fake proposal for the synthetic orders fixture.",
    )


def _owning_table(resource_id: str, order_table_id: str) -> str:
    return {
        "orders": order_table_id,
        "orders.lines[]": "fact_order_lines",
        "customers": "dim_customers" if order_table_id == "fact_orders" else "customers",
    }.get(resource_id, order_table_id)


class FakeModel:
    """Deterministic adapter: one tool call, then one valid `ModelDraft`."""

    name = FAKE_PROVIDER
    model_id = FAKE_MODEL_ID

    def __init__(
        self,
        *,
        inventory: InventoryView,
        catalogue: CatalogueView | None = None,
        scripted: list[ModelResponse] | None = None,
        tool_name: str = "sample_rows",
    ) -> None:
        self.inventory = inventory
        self.catalogue = catalogue
        self.scripted = list(scripted or [])
        self.tool_name = tool_name
        self.requests: list[ModelRequest] = []
        self.tool_results_seen: list[list[ToolResult]] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.scripted:
            return self.scripted.pop(0)
        results = list(request.results)
        self.tool_results_seen.append(results)
        if not results:
            return ModelResponse(
                tool_calls=[self._tool_request()],
                input_tokens=128,
                output_tokens=32,
                stop_reason="tool_use",
            )
        draft = build_fake_draft(self.inventory, self.catalogue, results[0])
        return ModelResponse(
            text=draft.model_dump_json(),
            input_tokens=256,
            output_tokens=512,
            stop_reason="end_turn",
        )

    def _tool_request(self) -> ToolCallRequest:
        arguments: dict[str, Any] = {
            "source_id": _source_id(self.inventory),
            "resource_id": FAKE_TARGET_RESOURCE,
            "fields": [
                field.ref.field_path
                for field in self.inventory.fields
                if field.ref.resource_id == FAKE_TARGET_RESOURCE
            ],
        }
        if self.tool_name == "sample_rows":
            arguments["limit"] = 3
        return ToolCallRequest(id=FAKE_TOOL_CALL_ID, name=self.tool_name, arguments=arguments)


def _source_id(inventory: InventoryView) -> str:
    for field_ in inventory.fields:
        if field_.ref.resource_id == FAKE_TARGET_RESOURCE:
            return field_.ref.source_id
    return inventory.fields[0].ref.source_id if inventory.fields else ""


# --- live model ----------------------------------------------------------------


class LiveModel:
    """The provider SDK path. Native tools and native structured output only."""

    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        max_output_tokens: int = 16000,
        timeout_seconds: float = 300.0,
        max_retries: int = 2,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.name = provider
        self.model_id = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._api_key = api_key
        #: Optional endpoint override. Anything that speaks the Anthropic Messages
        #: API can be used — including a gateway that fronts another vendor's model —
        #: which is what makes "the live path" testable without a specific vendor key.
        self._base_url = base_url
        self._client: Any = None

    def _build_client(self) -> Any:
        try:
            import anthropic  # type: ignore[import-not-found]  # noqa: PLC0415 - optional dependency
        except ImportError as error:
            raise ModelConfigurationError(
                "the anthropic SDK is not installed; install it or set GENLEDGE_MODEL_MODE=fake"
            ) from error
        if not self._api_key:
            raise ModelConfigurationError("no provider API key is configured")
        options: dict[str, Any] = {
            "api_key": self._api_key,
            "timeout": self.timeout_seconds,
            "max_retries": self.max_retries,
        }
        if self._base_url:
            options["base_url"] = self._base_url
        return anthropic.Anthropic(**options)

    def invoke(self, request: ModelRequest) -> ModelResponse:
        try:
            client = self._client or self._build_client()
        except ModelConfigurationError as error:
            return ModelResponse(error_code=error.code, error_message=error.message)
        self._client = client

        payload: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = {"type": "auto"}
        # Structured output is requested natively; the same contract validates it.
        payload["output_format"] = {
            "type": "json_schema",
            "schema": ModelDraft.model_json_schema(),
        }
        try:
            response = client.messages.create(**payload)
        except Exception as error:  # noqa: BLE001 - the taxonomy maps provider errors to codes
            return ModelResponse(
                error_code=_provider_error_code(error),
                error_message=f"{type(error).__name__}: {error}",
            )

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
        usage = getattr(response, "usage", None)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            return ModelResponse(
                error_code=MODEL_REFUSED,
                error_message="the provider refused to answer",
                stop_reason=stop_reason,
            )
        return ModelResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            stop_reason=stop_reason,
        )


def _provider_error_code(error: Exception) -> str:
    """Map a provider exception onto the harness taxonomy.

    Transport trouble (rate limit, timeout, connection, 5xx) and non-retryable
    trouble (authentication, permission, unknown model, bad request) both surface as
    `model_unavailable` today. The distinction is not yet carried on `ModelResponse`,
    so the exception class is preserved in the message; adding a retry flag is a
    change to one dataclass field and one node branch.
    """

    del error
    return MODEL_UNAVAILABLE


# --- mode resolution -----------------------------------------------------------


@dataclass(frozen=True)
class ResolvedModelMode:
    """The resolved runtime mode plus the safe facts startup is allowed to print."""

    mode: ModelMode
    requested: str
    provider: str
    model: str
    reason: str

    @property
    def banner(self) -> str:
        """A startup line that identifies the mode and never a secret."""

        if self.mode == "fake":
            return f"model_mode=fake provider={FAKE_PROVIDER} model={FAKE_MODEL_ID}"
        return f"model_mode=live provider={self.provider} model={self.model}"


def provider_configured(env: Mapping[str, str] | None = None) -> bool:
    """True when there is something to call the provider *with*. Presence only.

    A provider *name* is not configuration — see `PROVIDER_NAME_ENV_VARS`. Requiring a
    credential or an endpoint is what makes `auto` mean "use live only if it could
    actually work", instead of routing every job into a guaranteed configuration error.
    """

    source = os.environ if env is None else env
    return any(str(source.get(name, "")).strip() for name in PROVIDER_CREDENTIAL_ENV_VARS)


def resolve_model_mode(
    requested: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> ResolvedModelMode:
    """Resolve `GENLEDGE_MODEL_MODE` to `fake` or `live`.

    * `fake` always uses the fake model;
    * `live` requires provider configuration and otherwise raises a typed
      configuration error;
    * `auto` (the default) uses the live path only when provider configuration
      exists.
    """

    source = os.environ if env is None else env
    raw = (requested if requested is not None else source.get("GENLEDGE_MODEL_MODE", "auto")) or "auto"
    mode = raw.strip().lower()
    resolved_provider = provider or source.get("GENLEDGE_LLM_PROVIDER", "anthropic")
    resolved_model = model or source.get("GENLEDGE_LLM_MODEL", "claude-opus-5-5")
    configured = provider_configured(source)

    if mode == "fake":
        return ResolvedModelMode("fake", mode, resolved_provider, resolved_model, "explicit fake mode")
    if mode == "live":
        if not configured:
            raise ModelConfigurationError(
                "GENLEDGE_MODEL_MODE=live requires provider configuration "
                f"({', '.join(PROVIDER_ENV_VARS)}); none was present"
            )
        return ResolvedModelMode("live", mode, resolved_provider, resolved_model, "explicit live mode")
    if mode == "auto":
        if configured:
            return ResolvedModelMode("live", mode, resolved_provider, resolved_model, "provider configuration present")
        return ResolvedModelMode("fake", mode, resolved_provider, resolved_model, "no provider configuration present")
    raise ModelConfigurationError(
        f"GENLEDGE_MODEL_MODE={raw!r} is not one of auto, live, fake"
    )


def build_model_client(
    resolved: ResolvedModelMode,
    *,
    inventory: InventoryView,
    catalogue: CatalogueView | None = None,
    env: Mapping[str, str] | None = None,
) -> ModelClient:
    """Instantiate the adapter the resolved mode names."""

    if resolved.mode == "fake":
        return FakeModel(inventory=inventory, catalogue=catalogue)
    source = os.environ if env is None else env
    api_key: str | None = None
    for name in PROVIDER_CREDENTIAL_ENV_VARS:
        value = str(source.get(name, "")).strip()
        if value and (name.endswith("_API_KEY")):
            api_key = value
            break
    return LiveModel(
        provider=resolved.provider,
        model=resolved.model,
        effort=source.get("GENLEDGE_LLM_EFFORT", "medium"),
        max_output_tokens=int(source.get("GENLEDGE_LLM_MAX_OUTPUT_TOKENS", "16000")),
        timeout_seconds=float(source.get("GENLEDGE_LLM_TIMEOUT_SECONDS", "300")),
        max_retries=int(source.get("GENLEDGE_LLM_MAX_RETRIES", "2")),
        api_key=api_key,
        base_url=_base_url(source),
    )


def _base_url(env: Mapping[str, str]) -> str | None:
    """An explicit endpoint override, if the deployment sets one."""

    for name in ("GENLEDGE_LLM_BASE_URL", "ANTHROPIC_BASE_URL"):
        value = str(env.get(name, "")).strip()
        if value:
            return value
    return None


__all__ = [
    "FAKE_MODEL_ID",
    "FAKE_PROVIDER",
    "FAKE_TARGET_RESOURCE",
    "FAKE_TOOL_CALL_ID",
    "PROVIDER_ENV_VARS",
    "FakeModel",
    "LiveModel",
    "ModelClient",
    "ModelMode",
    "ModelRequest",
    "ModelResponse",
    "ResolvedModelMode",
    "build_fake_draft",
    "build_model_client",
    "parse_model_draft",
    "provider_configured",
    "resolve_model_mode",
]
