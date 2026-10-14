"""The read-only tool catalog and the seven-step dispatch contract.

`plans/LANGGRAPH_HARNESS_PLAN.md` §8.4 and `plans/user-stories/US4.md` §4.2 define
what `tool_call` must do per requested call:

1. validate arguments against the tool's own Pydantic model;
2. check the job's scope covers the requested source and resource;
3. check the budget **before** dispatch;
4. replay a recorded result when this `(job_id, tool_call_id)` already ran;
5. dispatch through the connector seam;
6. validate the connector's answer against the tool's result model;
7. redact, persist, and return a compact `ToolResultRef`.

A failure at any step is *data*: the model receives a typed `error` result it must
adapt to. Nothing in this module raises for a model-authored problem, because a
malformed tool request is not a crash — it is a fact the model has to reason
about.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import Field, ValidationError

from app.agent.contracts import AgentBudgets, InventoryView, StrictModel, ToolCallRequest, ToolResultRef

TOOL_NAMES: tuple[str, ...] = (
    "list_resources",
    "describe_resource",
    "profile_resource",
    "sample_rows",
    "compare_fields",
    "get_changes",
)

#: Result envelope codes. Model-authored problems are errors the model reads;
#: `unauthorized_source` is additionally a security event.
INVALID_ARGUMENTS = "invalid_arguments"
UNAUTHORIZED_SOURCE = "unauthorized_source"
RESOURCE_NOT_FOUND = "resource_not_found"
UNSUPPORTED = "unsupported"
BUDGET_EXHAUSTED = "budget_exhausted"
SNAPSHOT_DRIFTED = "snapshot_drifted"
CONNECTOR_ERROR = "connector_error"

REDACTION_MARKER = "[redacted]"
_CREDENTIAL = re.compile(r"(password|passwd|secret|token|api[_-]?key|credential|dsn|postgres(ql)?://)", re.I)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
#: A card-like run of digits is never safe to project, whatever the field is called.
_PAYMENT_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_SENSITIVE_FIELD = re.compile(r"(password|passwd|secret|token|api[_-]?key|credential|ssn|email)", re.I)


def redact_value(value: Any, field_path: str = "") -> Any:
    """Replace credential-like and contact-like values with a stable marker.

    Applied at the tool layer *before* persistence, so a restricted value is not
    stored in a tool result at all — and therefore cannot be projected into a
    prompt later. Structure is preserved; only the offending scalar is replaced.
    """

    if isinstance(value, str) and (
        _CREDENTIAL.search(value)
        or _EMAIL.match(value.strip())
        or _PAYMENT_CARD.search(value)
    ):
        return REDACTION_MARKER
    if _SENSITIVE_FIELD.search(field_path or ""):
        if isinstance(value, (list, tuple)):
            return [REDACTION_MARKER for _ in value]
        return REDACTION_MARKER
    if isinstance(value, list):
        return [redact_value(item, field_path) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, field_path) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_value(item, str(key)) for key, item in value.items()}
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a whole tool payload. Keys are treated as field paths."""

    return {str(key): redact_value(value, str(key)) for key, value in payload.items()}


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))


class ToolArgumentModel(StrictModel):
    """Base for per-tool argument models; unknown fields are rejected."""


class ListResourcesArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    path: str | None = None
    page_token: str | None = None


class DescribeResourceArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)


class ProfileResourceArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)


class SampleRowsArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    limit: int = Field(default=3, ge=1, le=50)


class CompareFieldsArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    left_resource_id: str = Field(min_length=1)
    left_field_path: str = Field(min_length=1)
    right_resource_id: str = Field(min_length=1)
    right_field_path: str = Field(min_length=1)


class GetChangesArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    cursor: str | None = None


class ToolSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    arguments: type[ToolArgumentModel]

    model_config = {"extra": "forbid", "frozen": True, "strict": True, "arbitrary_types_allowed": True}


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(name="list_resources", description="List the resources available in a source.", arguments=ListResourcesArgs),
        ToolSpec(name="describe_resource", description="Describe one resource's fields, types and declared keys.", arguments=DescribeResourceArgs),
        ToolSpec(name="profile_resource", description="Return bounded counts, nulls and cardinality for selected fields.", arguments=ProfileResourceArgs),
        ToolSpec(name="sample_rows", description="Return a bounded number of redacted representative rows.", arguments=SampleRowsArgs),
        ToolSpec(name="compare_fields", description="Return overlap and cardinality evidence for two fields.", arguments=CompareFieldsArgs),
        ToolSpec(name="get_changes", description="Report source changes since a cursor, or an explicit unsupported result.", arguments=GetChangesArgs),
    )
}


def tool_schemas() -> list[dict[str, Any]]:
    """The JSON Schemas bound to a model call, generated from the argument models."""

    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.arguments.model_json_schema(),
        }
        for spec in TOOL_SPECS.values()
    ]


class ToolResult(StrictModel):
    """A recorded tool result: the replay cache and the evidence record."""

    result_ref: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None
    redacted: bool = False
    bytes_estimate: int = Field(default=0, ge=0)

    def to_ref(self, *, replayed: bool = False) -> ToolResultRef:
        return ToolResultRef(
            tool_call_id=self.tool_call_id,
            tool=self.tool,
            status="ok" if self.status == "ok" else "error",
            result_ref=self.result_ref,
            replayed=replayed,
        )


class ToolOutcome(StrictModel):
    """What the dispatcher returns: the persisted result plus replay provenance."""

    result: ToolResult
    replayed: bool = False
    charged: bool = True

    @property
    def ref(self) -> ToolResultRef:
        return self.result.to_ref(replayed=self.replayed)


class ToolConnector(Protocol):
    """The connector seam. Person A's real services and the fake share this shape."""

    def call(self, name: str, arguments: dict[str, Any], job_id: str) -> dict[str, Any]:
        """Execute one read-only tool. Raise `ConnectorError` for a typed failure."""


class ConnectorError(Exception):
    """A connector-side failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FakeConnector:
    """A deterministic in-memory connector over the seeded orders fixture."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def call(self, name: str, arguments: dict[str, Any], job_id: str) -> dict[str, Any]:
        self.calls.append((name, dict(arguments), job_id))
        resource_id = str(arguments.get("resource_id", ""))
        fields = [str(item) for item in arguments.get("fields", [])]
        if name == "list_resources":
            return {
                "resources": [
                    {"resource_id": "orders", "name": "orders", "kind": "collection"},
                    {"resource_id": "orders.lines[]", "name": "orders.lines[]", "kind": "collection"},
                    {"resource_id": "customers", "name": "customers", "kind": "collection"},
                ]
            }
        if name == "describe_resource":
            return {"resource_id": resource_id, "field_count": len(fields) or 4}
        if name == "profile_resource":
            return {
                "resource_id": resource_id,
                "profiled_fields": fields,
                "row_count": 42,
                "nulls": {field: 0 for field in fields},
                "cardinality": {field: 42 for field in fields},
                "evidence_ref": "profile-1",
            }
        if name == "sample_rows":
            return {
                "resource_id": resource_id,
                "sampling": "head",
                "rows": [
                    {"line_id": "1", "sku": "SKU-1", "quantity": 2, "unit_price": 10.25},
                    {"line_id": "2", "sku": "SKU-2", "quantity": 5, "unit_price": 6.0},
                ],
            }
        if name == "compare_fields":
            return {"overlap": 0.98, "left_unique": True, "cardinality": "many_to_one"}
        if name == "get_changes":
            return {"status": UNSUPPORTED, "reason": "source does not expose a change cursor"}
        raise ConnectorError(CONNECTOR_ERROR, f"unknown tool {name!r}")


class ToolDispatcher:
    """Authorizes, budgets, replays, validates, redacts and persists tool calls."""

    def __init__(
        self,
        *,
        connector: ToolConnector,
        repository: Any,
        inventory: InventoryView,
        budgets: AgentBudgets,
    ) -> None:
        self.connector = connector
        self.repository = repository
        self.inventory = inventory
        self.budgets = budgets
        self.security_events: list[dict[str, Any]] = []

    # -- scope -----------------------------------------------------------------
    def allowed_sources(self) -> set[str]:
        return {field.ref.source_id for field in self.inventory.fields}

    def allowed_resources(self) -> set[str]:
        return {field.ref.resource_id for field in self.inventory.fields}

    # -- dispatch --------------------------------------------------------------
    def dispatch(self, request: ToolCallRequest, *, job_id: str, tool_calls_used: int) -> ToolOutcome:
        spec = TOOL_SPECS.get(request.name)
        if spec is None:
            return self._error(request, job_id, UNSUPPORTED, f"tool {request.name!r} is not supported")

        try:
            arguments = spec.arguments.model_validate(request.arguments)
        except ValidationError as error:
            return self._error(
                request,
                job_id,
                INVALID_ARGUMENTS,
                f"arguments do not match {request.name}: {_brief(error)}",
            )

        scope_error = self._scope_error(arguments)
        if scope_error is not None:
            code, message = scope_error
            if code == UNAUTHORIZED_SOURCE:
                self.security_events.append(
                    {"job_id": job_id, "tool_call_id": request.id, "tool": request.name, "code": code}
                )
            return self._error(request, job_id, code, message)

        # Replay before the budget check: a replayed call must not double-count.
        recorded = self.repository.get_tool_result(job_id, request.id)
        if recorded is not None:
            return ToolOutcome(result=recorded, replayed=True, charged=False)

        if tool_calls_used >= self.budgets.max_tool_calls:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"tool call budget exhausted ({self.budgets.max_tool_calls})",
                persist=False,
            )

        payload = arguments.model_dump()
        try:
            raw = self.connector.call(request.name, payload, job_id)
        except ConnectorError as error:
            return self._error(request, job_id, error.code, error.message)
        except Exception as error:  # noqa: BLE001 - a connector fault is data, not a crash
            return self._error(request, job_id, CONNECTOR_ERROR, str(error))

        redacted = redact_payload(dict(raw))
        size = payload_bytes(redacted)
        if size > self.budgets.max_tool_bytes:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"result of {size} bytes exceeds max_tool_bytes ({self.budgets.max_tool_bytes})",
                persist=False,
            )

        rows = redacted.get("rows")
        if isinstance(rows, list) and len(rows) > self.budgets.max_tool_rows:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"result of {len(rows)} rows exceeds max_tool_rows ({self.budgets.max_tool_rows})",
                persist=False,
            )

        result = ToolResult(
            result_ref=f"tool:{job_id}:{request.id}",
            job_id=job_id,
            tool_call_id=request.id,
            tool=request.name,
            status="ok",
            payload=redacted,
            redacted=True,
            bytes_estimate=size,
        )
        self.repository.record_tool_result(result)
        return ToolOutcome(result=result, replayed=False, charged=True)

    # -- helpers ---------------------------------------------------------------
    def _scope_error(self, arguments: ToolArgumentModel) -> tuple[str, str] | None:
        source_id = getattr(arguments, "source_id", None)
        if source_id is not None and source_id not in self.allowed_sources():
            return UNAUTHORIZED_SOURCE, f"source {source_id!r} is not in this job's snapshot"
        resources = [
            value
            for key, value in arguments.model_dump().items()
            if key == "resource_id" or key.endswith("_resource_id")
        ]
        for resource_id in resources:
            if resource_id and resource_id not in self.allowed_resources():
                return RESOURCE_NOT_FOUND, f"resource {resource_id!r} is not in this job's snapshot"
        return None

    def _error(
        self,
        request: ToolCallRequest,
        job_id: str,
        code: str,
        message: str,
        *,
        persist: bool = True,
    ) -> ToolOutcome:
        result = ToolResult(
            result_ref=f"tool:{job_id}:{request.id}",
            job_id=job_id,
            tool_call_id=request.id,
            tool=request.name,
            status="error",
            payload={},
            error_code=code,
            message=message,
        )
        if persist:
            self.repository.record_tool_result(result)
        return ToolOutcome(result=result, replayed=False, charged=False)


def _brief(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
    return f"{location}: {first.get('msg', 'invalid')}"


__all__ = [
    "BUDGET_EXHAUSTED",
    "CONNECTOR_ERROR",
    "INVALID_ARGUMENTS",
    "REDACTION_MARKER",
    "RESOURCE_NOT_FOUND",
    "SNAPSHOT_DRIFTED",
    "TOOL_NAMES",
    "TOOL_SPECS",
    "UNAUTHORIZED_SOURCE",
    "UNSUPPORTED",
    "ConnectorError",
    "FakeConnector",
    "ToolArgumentModel",
    "ToolCallRequest",
    "ToolDispatcher",
    "ToolOutcome",
    "ToolResult",
    "ToolSpec",
    "payload_bytes",
    "redact_payload",
    "redact_value",
    "tool_schemas",
]
