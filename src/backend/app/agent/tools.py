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
#: Credential *words*, and any connection string. The scheme list is open-ended on
#: purpose: `scheme://user:pass@host` is a DSN whoever makes it, and enumerating
#: vendors meant `mysql://` and `mongodb+srv://` reached prompts unredacted.
_CREDENTIAL = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|dsn)"
    r"|([a-z][a-z0-9+.\-]{1,20}://[^\s]*:[^\s]*@)"
    r"|((?:mongodb(?:\+srv)?|redis|amqp|jdbc):[^\s]*@)",
    re.I,
)
#: Unanchored: an address embedded in a sentence is still a contact detail, which is
#: what the docstring below always claimed and the anchored pattern did not do.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
#: A card-like run of digits is never safe to project, whatever the field is called.
_PAYMENT_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_SENSITIVE_FIELD = re.compile(r"(password|passwd|secret|token|api[_-]?key|credential|ssn|email)", re.I)


def redact_value(value: Any, field_path: str = "") -> Any:
    """Replace credential-like and contact-like values with a stable marker.

    Applied at the tool layer *before* persistence, so a restricted value is not
    stored in a tool result at all — and therefore cannot be projected into a prompt
    later. Structure is preserved; only the offending scalar is replaced.

    Detection is deliberately broad and `search`-based: any `scheme://user:pass@host`
    connection string, any e-mail address anywhere in a longer string, any card-like
    run of digits, and any value under a field whose name says it is sensitive. A
    false positive costs a `[redacted]` marker in a prompt; a false negative costs a
    credential.
    """

    if isinstance(value, str) and (
        _CREDENTIAL.search(value)
        or _EMAIL.search(value)
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


def merge_path(resource_id: str, field_path: str) -> str:
    """Join a resource and field path without repeating an overlapping segment.

    `orders.lines[]` + `lines[].sku` is `orders.lines[].sku`, not
    `orders.lines[].lines[].sku`. The projection and the argument validator must agree
    on this or a legal request is refused for naming a path the prompt itself shows.
    """

    if field_path == resource_id or field_path.startswith(resource_id + "."):
        return field_path
    resource_parts = resource_id.split(".")
    field_parts = field_path.split(".")
    for size in range(min(len(resource_parts), len(field_parts)), 0, -1):
        if resource_parts[-size:] == field_parts[:size]:
            return ".".join(resource_parts + field_parts[size:])
    return f"{resource_id}.{field_path}"


def _rows_of(payload: dict[str, Any]) -> list[Any] | None:
    """The top-level row list of a result model, whatever the tool calls it.

    `max_tool_rows` is enforced against the one row collection the *declared* result
    model actually has, so the cap cannot be bypassed by nesting the rows under a
    different key.
    """

    for key in ("rows", "resources", "changed_resources"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return None


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))


class ToolArgumentModel(StrictModel):
    """Base for per-tool argument models; unknown fields are rejected."""


class ToolResultModel(StrictModel):
    """Base for per-tool result models.

    Boundary 4 of `plans/LANGGRAPH_HARNESS_PLAN.md` §5.4: the connector's answer is
    validated before it is redacted and persisted. A shape the harness did not
    declare becomes a typed `connector_error` the model can read, rather than data
    that silently gains a field the row/byte caps do not know about.
    """


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


class ResourceSummaryResult(StrictModel):
    resource_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class ListResourcesResult(ToolResultModel):
    resources: list[ResourceSummaryResult] = Field(default_factory=list)
    next_page_token: str | None = None


class DescribeResourceResult(ToolResultModel):
    resource_id: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    field_count: int = Field(default=0, ge=0)
    declared_key: list[str] = Field(default_factory=list)


class ProfileResourceResult(ToolResultModel):
    resource_id: str = Field(min_length=1)
    profiled_fields: list[str] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    nulls: dict[str, int] = Field(default_factory=dict)
    cardinality: dict[str, int] = Field(default_factory=dict)
    evidence_ref: str | None = None


class SampleRowsResult(ToolResultModel):
    resource_id: str = Field(min_length=1)
    sampling: str = Field(default="head", min_length=1)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ref: str | None = None


class CompareFieldsResult(ToolResultModel):
    overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    left_unique: bool = False
    cardinality: str = Field(default="unknown", min_length=1)
    evidence_ref: str | None = None


class GetChangesResult(ToolResultModel):
    status: str = Field(default="ok", min_length=1)
    reason: str | None = None
    changed_resources: list[str] = Field(default_factory=list)


class ToolSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    arguments: type[ToolArgumentModel]
    result: type[ToolResultModel]

    model_config = {"extra": "forbid", "frozen": True, "strict": True, "arbitrary_types_allowed": True}


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="list_resources",
            description="List the resources available in a source.",
            arguments=ListResourcesArgs,
            result=ListResourcesResult,
        ),
        ToolSpec(
            name="describe_resource",
            description="Describe one resource's fields, types and declared keys.",
            arguments=DescribeResourceArgs,
            result=DescribeResourceResult,
        ),
        ToolSpec(
            name="profile_resource",
            description="Return bounded counts, nulls and cardinality for selected fields.",
            arguments=ProfileResourceArgs,
            result=ProfileResourceResult,
        ),
        ToolSpec(
            name="sample_rows",
            description="Return a bounded number of redacted representative rows.",
            arguments=SampleRowsArgs,
            result=SampleRowsResult,
        ),
        ToolSpec(
            name="compare_fields",
            description="Return overlap and cardinality evidence for two fields.",
            arguments=CompareFieldsArgs,
            result=CompareFieldsResult,
        ),
        ToolSpec(
            name="get_changes",
            description="Report source changes since a cursor, or an explicit unsupported result.",
            arguments=GetChangesArgs,
            result=GetChangesResult,
        ),
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
            return {
                "resource_id": resource_id,
                "fields": fields,
                "field_count": len(fields) or 4,
                "declared_key": ["order_id"] if resource_id == "orders" else [],
            }
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

    def allowed_field_paths(self) -> set[str]:
        """Every field path the snapshot discovered, in both forms a caller may use.

        Both spellings are accepted because both are natural: the bare discovered path
        (`lines[].sku`) and the resource-qualified one (`orders.lines[].sku`). The
        qualified form is built with the same merge the projection uses — a naive
        `resource.field` concatenation produced `orders.lines[].lines[].sku`, which
        matched neither what a caller sends nor what the prompt shows.
        """

        paths: set[str] = set()
        for field in self.inventory.fields:
            paths.add(field.ref.field_path)
            paths.add(merge_path(field.ref.resource_id, field.ref.field_path))
        return paths

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
            return self._error(request, job_id, error.code, error.message, charge=True)
        except Exception as error:  # noqa: BLE001 - a connector fault is data, not a crash
            return self._error(request, job_id, CONNECTOR_ERROR, str(error), charge=True)

        # Boundary 4: validate the connector's answer *inside* the guarded block, so
        # a shape the harness did not declare is data rather than an exception.
        try:
            if not isinstance(raw, dict):
                raise ConnectorError(CONNECTOR_ERROR, f"connector returned {type(raw).__name__}, not an object")
            validated = spec.result.model_validate(raw)
        except ValidationError as error:
            return self._error(
                request,
                job_id,
                CONNECTOR_ERROR,
                f"{request.name} result does not match its contract: {_brief(error)}",
                charge=True,
            )
        except ConnectorError as error:
            return self._error(request, job_id, error.code, error.message, charge=True)

        redacted = {key: redact_value(value, key) for key, value in validated.model_dump().items()}
        size = payload_bytes(redacted)
        if size > self.budgets.max_tool_bytes:
            # Persisted: the read happened and this *is* evidence about the source, so a
            # retry of the same `tool_call_id` must replay it rather than re-read a
            # source that may have changed. The payload is empty, so the cap still holds.
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"result of {size} bytes exceeds max_tool_bytes ({self.budgets.max_tool_bytes})",
                charge=True,
            )

        rows = _rows_of(redacted)
        if rows is not None and len(rows) > self.budgets.max_tool_rows:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"result of {len(rows)} rows exceeds max_tool_rows ({self.budgets.max_tool_rows})",
                charge=True,
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
        """Authorization and field-path validation, before any connector call.

        Two controls, and both are master §7.6's: the job's snapshot must cover the
        requested source and resource, **and** a requested field path must be one the
        snapshot discovered. Without the second, `fields: ["x; DROP TABLE orders"]` was
        a legal argument — the pattern check that would have caught it lives in
        `contracts.Identifier`, which a free-form `list[str]` argument does not apply.
        """

        source_id = getattr(arguments, "source_id", None)
        if source_id is not None and source_id not in self.allowed_sources():
            return UNAUTHORIZED_SOURCE, f"source {source_id!r} is not in this job's snapshot"
        dumped = arguments.model_dump()
        resources = [
            value for key, value in dumped.items() if key == "resource_id" or key.endswith("_resource_id")
        ]
        for resource_id in resources:
            if resource_id and resource_id not in self.allowed_resources():
                return RESOURCE_NOT_FOUND, f"resource {resource_id!r} is not in this job's snapshot"
        unknown = [path for path in self._requested_field_paths(dumped) if path not in self.allowed_field_paths()]
        if unknown:
            return INVALID_ARGUMENTS, (
                f"field path(s) not in this job's snapshot: {', '.join(sorted(set(unknown))[:5])}"
            )
        return None

    @staticmethod
    def _requested_field_paths(dumped: dict[str, Any]) -> list[str]:
        """Every field path an argument names, from `fields` lists and `*_field_path`."""

        paths: list[str] = []
        for key, value in dumped.items():
            if key == "fields" and isinstance(value, list):
                paths.extend(str(item) for item in value)
            elif key.endswith("_field_path") and value:
                paths.append(str(value))
        return paths

    def _error(
        self,
        request: ToolCallRequest,
        job_id: str,
        code: str,
        message: str,
        *,
        persist: bool = True,
        charge: bool = False,
    ) -> ToolOutcome:
        """Build a typed error result.

        `charge` decides whether the tool budget counts this attempt, and the rule is
        the budget's whole point: **a call that reached the connector is charged, even
        when it failed**. Otherwise a source that fails every read is free, and a model
        that keeps asking for it never exhausts `max_tool_calls` — the loop bound
        silently stops applying exactly when the loop is most likely to run away.

        A refusal made *before* dispatch (bad arguments, out-of-scope source, no budget
        left, nothing ran) is not charged, and is not persisted either: it is not
        evidence about the source.
        """

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
        return ToolOutcome(result=result, replayed=False, charged=charge)


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
    "CompareFieldsResult",
    "ConnectorError",
    "DescribeResourceResult",
    "FakeConnector",
    "GetChangesResult",
    "ListResourcesResult",
    "ProfileResourceResult",
    "SampleRowsResult",
    "ToolArgumentModel",
    "ToolCallRequest",
    "ToolDispatcher",
    "ToolOutcome",
    "ToolResult",
    "ToolResultModel",
    "ToolSpec",
    "payload_bytes",
    "redact_payload",
    "redact_value",
    "tool_schemas",
]
