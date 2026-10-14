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
from typing import Annotated, Any, Protocol

from pydantic import Field, StringConstraints, ValidationError

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
INVALID_TOOL_REQUEST = "invalid_tool_request"
UNAUTHORIZED_SOURCE = "unauthorized_source"
RESOURCE_NOT_FOUND = "resource_not_found"
UNSUPPORTED = "unsupported"
BUDGET_EXHAUSTED = "budget_exhausted"
SNAPSHOT_DRIFTED = "snapshot_drifted"
CONNECTOR_ERROR = "connector_error"
REPLAY_MISMATCH = "replay_mismatch"
STORAGE_FAILED = "storage_failed"

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
#: A credential literal used *as a key* (`{"sk-live-...": ...}`) matches no field name
#: and, on its own, no credential word. The well-known vendor prefixes are what make it
#: recognisable.
_SECRET_SHAPED = re.compile(
    r"\b(?:sk|pk|rk|ak|ghp|gho|github_pat|xox[abprs])[-_][A-Za-z0-9_\-]{8,}"
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{12,}\b"
    r"|\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.",
)
#: Contact details and personal identifiers — `plans/us4-four-person-task-split.md`
#: line 184's "phone, address, identifiers" categories. Unanchored and
#: separator-tolerant, because a phone number inside a free-text sample is still one.
_IDENTIFIER = re.compile(
    # North-American style phone: 555-123-4567, (555) 123 4567, +1 555.123.4567
    r"(?:\+?\d{1,3}[ .\-]?)?(?:\(\d{3}\)|\d{3})[ .\-]\d{3}[ .\-]?\d{4}\b"
    # US SSN, with or without separators
    r"|\b\d{3}[ .\-]\d{2}[ .\-]\d{4}\b"
    # IBAN-like: two letters, two digits, then 11+ alphanumerics
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
    # A street-address line
    r"|\b\d{1,6}\s+[A-Za-z][A-Za-z'.\-]*(?:\s+[A-Za-z][A-Za-z'.\-]*){0,3}\s+"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|Ter)\.?\b",
    re.I,
)
#: Field names whose *values* are restricted whatever they contain. Kept next to the
#: content patterns so both halves of the policy are read together. `\b` on the short
#: words matters: an unanchored `card` also matched `declared_key`, which would have
#: redacted every `describe_resource` answer.
_SENSITIVE_FIELD = re.compile(
    r"(password|passwd|\bpass\b|\bpwd\b|passphrase|secret|token|api[_-]?key"
    r"|access[_-]?key|private[_-]?key|credential|ssn|social[_-]?security"
    r"|email|e[_-]?mail|phone|mobile|address|street|postcode|postal|zip|dob|birth"
    r"|passport|licen[cs]e|national[_-]?id|account[_-]?(?:number|no|id)"
    r"|authorization|bearer|\bjwt\b|\bpin\b|\biban\b|\bswift\b|routing|\bcvv\b"
    r"|card[_-]?(?:number|no|id)|\bcard\b)",
    re.I,
)


def canonical_arguments(name: str, arguments: dict[str, Any] | None) -> str:
    """A stable fingerprint of one tool request, used to prove a replay is a retry.

    A `tool_call_id` is model-authored, so a recorded result proves nothing about
    *what* was requested. The recorded tool name plus this digest is what makes a
    replay a re-execution of the same call rather than an answer to a different one.
    """

    return json.dumps({"name": name, "arguments": arguments or {}}, sort_keys=True, default=str)


def _restricted_text(haystack: str) -> bool:
    """True when a rendered scalar contains a restricted pattern."""

    return bool(
        _CREDENTIAL.search(haystack)
        or _EMAIL.search(haystack)
        or _PAYMENT_CARD.search(haystack)
        or _IDENTIFIER.search(haystack)
    )


def _restricted_name(name: str) -> bool:
    """True when a *key* names a restricted value, or is itself credential-shaped.

    Two different things, and the difference matters for keys: `credentials` and
    `password` are **field names** — a payload keeps them and redacts the value, because
    callers index and iterate the mapping. `sk-live-...` is a **credential literal** used
    as a name, which is not a field name at all and is replaced.
    """

    return bool(_SENSITIVE_FIELD.search(name) or _SECRET_SHAPED.search(name))


def _credential_literal(name: str) -> bool:
    """True only for a key that is itself credential material, not a field name."""

    return bool(_SECRET_SHAPED.search(name))


def redact_value(value: Any, field_path: str = "") -> Any:
    """Replace credential-like, contact-like and identifier-like values with a marker.

    Applied at the tool layer *before persistence*, so a restricted value is not
    stored in a tool result at all — and therefore cannot be projected into a prompt
    later. Structure is preserved; only the offending scalar is replaced.

    Four rules, and the order matters:

    1. **Field name decides first, whatever the value is.** This check has to come
       before the container branches, not after them: a mapping under a key that names
       restricted data (`{"credentials": {"user": ..., "pass": ...}}`) is restricted as a
       whole subtree. Checking the name only when the value was a scalar meant the
       container branch matched first, the key was replaced, and the plaintext *values*
       inside it were projected into the prompt while the row was stamped `redacted`.
    2. **Content**, against the *string form* of any scalar — not only `str` values.
       A card number or phone number stored as an `int`/`float` is exactly as
       restricted as one stored as text, and gating on `isinstance(value, str)` let
       `{"card_number": 4111111111111111}` through untouched.
    3. **Keys are redacted too.** `{"sk-live-...": "value"}` previously reached the
       prompt verbatim, key included.
    4. **Recursion** into lists, tuples and dicts, where a nested key becomes the
       field path for the value beneath it.

    A false positive costs a `[redacted]` marker in a prompt; a false negative costs
    a credential.
    """

    if _restricted_name(field_path or ""):
        # Rule 1: the name decides, whatever the value is — scalar or subtree.
        return REDACTION_MARKER
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            safe_key = REDACTION_MARKER if _credential_literal(name) else name
            redacted[safe_key] = redact_value(item, name)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_value(item, field_path) for item in value]
    if isinstance(value, bool) or value is None:
        # `True`/`False` carry no restricted content; `None` is not a value.
        return value
    if isinstance(value, (int, float)):
        return REDACTION_MARKER if _restricted_text(str(value)) else value
    if isinstance(value, str):
        return REDACTION_MARKER if _restricted_text(value) else value
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a whole tool payload, preserving its shape.

    Keys are treated as field paths, and a key that *names* restricted data keeps its
    place in the mapping with a redacted value — it is not dropped and the mapping is not
    replaced by a scalar, because callers index and iterate the result
    (`payload["resource_id"]`, `_rows_of(redacted)`). `redact_value` describes the value's
    own subtree; this function describes the envelope around it.
    """

    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key)
        # A field-named key keeps its place so callers can still index the payload; a key
        # that *is* credential material is not a field name and does not survive.
        safe_key = REDACTION_MARKER if _credential_literal(name) else name
        redacted[safe_key] = (
            REDACTION_MARKER if _restricted_name(name) else redact_value(value, name)
        )
    return redacted


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


#: A free-form pass-through argument (a path, a cursor, a page token) is a place where
#: the model can put anything, and a connector will hand it to a backend. Constraining
#: it to a path-shaped token is what keeps `path="x; DROP TABLE orders"` from being a
#: legal argument — the same control the field-path check applies to `fields`.
SafeToken = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_./\[\]\-]*$")
]


def rejects_traversal(token: str | None) -> bool:
    """True when a token could name a location outside the source.

    The character class on `SafeToken` admits `.` and `/`, which is what a path-shaped
    token needs — and also what `../../etc/passwd` needs. The `..` segment is the obvious
    case, but not the only one a connector can be tricked by:

    * `....//....//etc/passwd` collapses to `../../…` under a normaliser that strips a
      single `../` per pass;
    * an absolute path wins outright, because `os.path.join(root, "/etc/passwd")` returns
      the absolute path and ignores `root`;
    * a drive letter or a UNC prefix does the same on Windows.

    All three are refused, and the token is normalised before the segment test so a
    doubled separator cannot hide one.
    """

    if token is None:
        return False
    text = str(token).strip()
    if not text:
        return False
    # Absolute, drive-qualified or UNC: joining this to a root escapes the root.
    if text.startswith(("/", "\\")) or (len(text) > 1 and text[1] == ":"):
        return True
    collapsed = text.replace("\\", "/")
    # Collapse the repetitions a normaliser folds, then look for the escape again: this
    # is what makes `....//....//etc/passwd` visible.
    while "//" in collapsed:
        collapsed = collapsed.replace("//", "/")
    segments = [segment for segment in collapsed.split("/") if segment not in ("", ".")]
    return any(segment == ".." or segment.endswith("..") for segment in segments)


class ToolResultModel(StrictModel):
    """Base for per-tool result models.

    Boundary 4 of `plans/LANGGRAPH_HARNESS_PLAN.md` §5.4: the connector's answer is
    validated before it is redacted and persisted. A shape the harness did not
    declare becomes a typed `connector_error` the model can read, rather than data
    that silently gains a field the row/byte caps do not know about.
    """


class ListResourcesArgs(ToolArgumentModel):
    source_id: str = Field(min_length=1)
    path: SafeToken | None = None
    page_token: SafeToken | None = None


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
    cursor: SafeToken | None = None


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
    #: The validated arguments this call actually ran with. `tool_call_id` is
    #: model-authored, so without this a recorded row cannot prove *what* was asked
    #: for, and a replay under a reused id would hand back another call's payload.
    arguments: dict[str, Any] = Field(default_factory=dict)
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

    def field_paths_for(self, resource_id: str) -> set[str]:
        """The field paths that belong to **one** resource, in both accepted forms.

        `allowed_field_paths()` is a union over every resource, so on its own it
        authorizes `sample_rows(resource_id="customers", fields=["lines[].sku"])` — a
        field of `orders.lines[]` read under another resource's name. Scope is
        per-resource, so the accepted set has to be too.
        """

        paths: set[str] = set()
        for field in self.inventory.fields:
            if field.ref.resource_id != resource_id:
                continue
            paths.add(field.ref.field_path)
            paths.add(merge_path(field.ref.resource_id, field.ref.field_path))
        return paths

    # -- dispatch --------------------------------------------------------------
    def dispatch(
        self,
        request: ToolCallRequest,
        *,
        job_id: str,
        tool_calls_used: int,
        seen_call_ids: set[str] | None = None,
    ) -> ToolOutcome:
        spec = TOOL_SPECS.get(request.name)
        if spec is None:
            return self._error(request, job_id, UNSUPPORTED, f"tool {request.name!r} is not supported")

        # The `tool_call_id` is model-authored and is the harness's replay key, so a
        # repeated id inside one batch would answer the second request with the
        # first's payload. The batch is refused whole: the model must re-ask with
        # distinct ids, and nothing partial is recorded.
        if seen_call_ids is not None:
            if request.id in seen_call_ids:
                return self._error(
                    request,
                    job_id,
                    INVALID_TOOL_REQUEST,
                    f"tool_call_id {request.id!r} appears more than once in one batch; "
                    "each requested call needs its own id",
                    persist=False,
                )
            seen_call_ids.add(request.id)

        try:
            arguments = spec.arguments.model_validate(request.arguments)
        except ValidationError as error:
            return self._error(
                request,
                job_id,
                INVALID_ARGUMENTS,
                f"arguments do not match {request.name}: {_brief(error)}",
                persist=False,
            )

        scope_error = self._scope_error(arguments)
        if scope_error is not None:
            code, message = scope_error
            if code in (UNAUTHORIZED_SOURCE, RESOURCE_NOT_FOUND):
                # A probe for a source or resource outside the job's snapshot is an
                # authorization event whether or not the id exists here.
                self.security_events.append(
                    {"job_id": job_id, "tool_call_id": request.id, "tool": request.name, "code": code}
                )
            return self._error(request, job_id, code, message, arguments=request.arguments, persist=False)

        recorded = self.repository.get_tool_result(job_id, request.id)
        if recorded is not None:
            # The id alone proves nothing — it is model-authored. A replay answers
            # the *same* call; a different tool or different arguments under the same
            # id is a stale or forged replay and must not receive the other payload.
            # Both sides are compared in validated form, so an omitted default is not a
            # difference.
            if recorded.tool != request.name or recorded.arguments != arguments.model_dump():
                return self._error(
                    request,
                    job_id,
                    REPLAY_MISMATCH,
                    f"tool_call_id {request.id!r} was already recorded for "
                    f"{recorded.tool!r} with different arguments; refusing the replay",
                    arguments=request.arguments,
                    persist=False,
                )
            return ToolOutcome(result=recorded, replayed=True, charged=False)

        if tool_calls_used >= self.budgets.max_tool_calls:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"tool call budget exhausted ({self.budgets.max_tool_calls})",
                arguments=request.arguments,
                persist=False,
            )

        payload = arguments.model_dump()
        try:
            raw = self.connector.call(request.name, payload, job_id)
        except ConnectorError as error:
            return self._error(request, job_id, error.code, error.message, arguments=payload, charge=True)
        except Exception as error:  # noqa: BLE001 - a connector fault is data, not a crash
            return self._error(
                request, job_id, CONNECTOR_ERROR, str(error), arguments=payload, charge=True
            )

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
                arguments=payload,
                charge=True,
            )
        except ConnectorError as error:
            return self._error(request, job_id, error.code, error.message, arguments=payload, charge=True)

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
                arguments=payload,
                charge=True,
            )

        rows = _rows_of(redacted)
        if rows is not None and len(rows) > self.budgets.max_tool_rows:
            return self._error(
                request,
                job_id,
                BUDGET_EXHAUSTED,
                f"result of {len(rows)} rows exceeds max_tool_rows ({self.budgets.max_tool_rows})",
                arguments=payload,
                charge=True,
            )

        result = ToolResult(
            result_ref=f"tool:{job_id}:{request.id}",
            job_id=job_id,
            tool_call_id=request.id,
            tool=request.name,
            arguments=payload,
            status="ok",
            payload=redacted,
            redacted=True,
            bytes_estimate=size,
        )
        try:
            self.repository.record_tool_result(result)
        except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
            # The read happened but could not be recorded, so there is no evidence row
            # and no replay key. Reporting `ok` here would publish an unpersisted
            # result as a successful tool execution.
            return self._error(
                request,
                job_id,
                STORAGE_FAILED,
                f"the tool result could not be persisted: {type(error).__name__}: {error}",
                charge=True,
            )
        return ToolOutcome(result=result, replayed=False, charged=True)

    # -- helpers ---------------------------------------------------------------
    def _scope_error(self, arguments: ToolArgumentModel) -> tuple[str, str] | None:
        """Authorization and field-path validation, before any connector call.

        Three controls, all of them master §7.6's:

        * the job's snapshot must cover the requested `source_id`;
        * a requested `resource_id` must exist in the snapshot;
        * a requested field path must be one the snapshot discovered **for that
          resource**. Without the third, `fields: ["x; DROP TABLE orders"]` was a
          legal argument — `contracts.Identifier`'s pattern does not apply to a
          free-form `list[str]` — and a field of one resource was readable under
          another resource's name.
        """

        source_id = getattr(arguments, "source_id", None)
        if source_id is not None and source_id not in self.allowed_sources():
            return UNAUTHORIZED_SOURCE, f"source {source_id!r} is not in this job's snapshot"
        dumped = arguments.model_dump()
        for key in ("path", "page_token", "cursor"):
            value = dumped.get(key)
            if value is not None and rejects_traversal(str(value)):
                return INVALID_ARGUMENTS, (
                    f"{key} contains a '..' path segment, which is not a path inside the source"
                )
        declared: set[str] = set()
        for key, value in dumped.items():
            if key == "resource_id" or key.endswith("_resource_id"):
                if not value:
                    continue
                if value not in self.allowed_resources():
                    return RESOURCE_NOT_FOUND, f"resource {value!r} is not in this job's snapshot"
                declared.add(str(value))
        requested = self._requested_field_paths(dumped)
        if not requested:
            return None
        if not declared:
            if len(self.allowed_resources()) > 1:
                # Several resources are in scope and the request named none of them, so
                # there is no per-resource set to check against. Refuse rather than fall
                # back to the union, which was the cross-resource hole.
                return INVALID_ARGUMENTS, (
                    "the request names field paths but no resource_id; a field path can "
                    "only be authorized against one resource"
                )
            if len(self.allowed_sources()) > 1:
                # One resource, but several sources, and the request named no source: the
                # resource id would have to be resolved against an unspecified source.
                return INVALID_ARGUMENTS, (
                    "the request names field paths but no source_id; a field path can "
                    "only be authorized against one source"
                )
        # `compare_fields` declares two resources (`left_resource_id` and
        # `right_resource_id`), so the accepted set is the union over the resources the
        # request itself named — still per-resource, never the whole snapshot.
        allowed = set().union(*(self.field_paths_for(item) for item in declared)) if declared else self.allowed_field_paths()
        unknown = [path for path in requested if path not in allowed]
        if unknown:
            where = (
                ", ".join(repr(item) for item in sorted(declared))
                if declared
                else "this job's snapshot"
            )
            return INVALID_ARGUMENTS, (
                f"field path(s) not in resource(s) {where}: {', '.join(sorted(set(unknown))[:5])}"
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
        arguments: dict[str, Any] | None = None,
        persist: bool = True,
        charge: bool = False,
    ) -> ToolOutcome:
        """Build a typed error result.

        `charge` decides whether the tool budget counts this attempt, and the rule is
        the budget's whole point: **a call that reached the connector is charged, even
        when it failed**. Otherwise a source that fails every read is free, and a model
        that keeps asking for it never exhausts `max_tool_calls` — the loop bound
        silently stops applying exactly when the loop is most likely to run away.

        `persist` decides whether the refusal becomes a replayable row. A refusal made
        *before* dispatch (unsupported tool, bad arguments, out-of-scope source or
        resource, no budget left — nothing ran) is not evidence about the source, so it
        is not persisted: caching it would make a later **corrected** call under the
        same `tool_call_id` replay the old refusal forever. A refusal made *after* a
        connector call is evidence and is persisted, so a retry replays it instead of
        re-reading a source that may have changed.
        """

        result = ToolResult(
            result_ref=f"tool:{job_id}:{request.id}",
            job_id=job_id,
            tool_call_id=request.id,
            tool=request.name,
            # Recorded in *validated* form so a later replay's integrity comparison sees
            # the same shape, defaults included.
            arguments=dict(arguments if arguments is not None else request.arguments),
            status="error",
            payload={},
            error_code=code,
            message=message,
        )
        if persist:
            try:
                self.repository.record_tool_result(result)
            except Exception as error:  # noqa: BLE001 - a store fault is data, not a crash
                return ToolOutcome(
                    result=ToolResult(
                        result_ref=result.result_ref,
                        job_id=job_id,
                        tool_call_id=request.id,
                        tool=request.name,
                        arguments=result.arguments,
                        status="error",
                        payload={},
                        error_code=STORAGE_FAILED,
                        message=(
                            f"the {code!r} result could not be persisted: "
                            f"{type(error).__name__}: {error}"
                        ),
                    ),
                    replayed=False,
                    charged=charge,
                )
        return ToolOutcome(result=result, replayed=False, charged=charge)


def _brief(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
    return f"{location}: {first.get('msg', 'invalid')}"


__all__ = [
    "BUDGET_EXHAUSTED",
    "CONNECTOR_ERROR",
    "INVALID_ARGUMENTS",
    "INVALID_TOOL_REQUEST",
    "REDACTION_MARKER",
    "REPLAY_MISMATCH",
    "RESOURCE_NOT_FOUND",
    "SNAPSHOT_DRIFTED",
    "STORAGE_FAILED",
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
    "canonical_arguments",
    "payload_bytes",
    "redact_payload",
    "redact_value",
    "tool_schemas",
]
