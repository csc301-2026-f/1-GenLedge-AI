"""The single typed contract surface shared by the US4 workstreams."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

CONTRACT_VERSION = "1"
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.\[\]-]*$")]


def _major_version(value: str) -> str:
    if not isinstance(value, str) or not value or value.split(".", 1)[0] != CONTRACT_VERSION.split(".", 1)[0]:
        raise ValueError(f"unsupported contract version: {value!r}")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PersistedArtifact(StrictModel):
    contract_version: str = CONTRACT_VERSION

    _validate_contract_version = field_validator("contract_version")(_major_version)


class SourceType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    JSON = "json"


class Disposition(StrEnum):
    REPRESENTED = "represented"
    RAW_ONLY = "raw_only"
    EXCLUDED = "excluded"
    SENSITIVE = "sensitive"
    UNRESOLVED = "unresolved"


class Severity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVISING = "revising"
    AWAITING_REVIEW = "awaiting_review"
    EDIT_REQUESTED = "edit_requested"
    APPROVAL_REQUESTED = "approval_requested"
    CANCELLING = "cancelling"
    BLOCKED = "blocked"
    APPROVED = "approved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FindingCode(StrEnum):
    INVALID_SOURCE_REFERENCE = "invalid_source_reference"
    INVALID_TARGET_REFERENCE = "invalid_target_reference"
    INVALID_MERGE_KEY = "invalid_merge_key"
    MISSING_EVIDENCE = "missing_evidence"
    UNMAPPED_SOURCE_FIELD = "unmapped_source_field"
    UNMAPPED_TARGET_FIELD = "unmapped_target_field"
    AMBIGUOUS_DATE = "ambiguous_date"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    STALE_MAPPING_REVISION = "stale_mapping_revision"
    PARTIAL_TABLE_FAILURE = "partial_table_failure"


class TransformName(StrEnum):
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    TRIM = "trim"
    DATE_FORMAT = "date_format"
    CONCAT = "concat"
    DEFAULT_VALUE = "default_value"
    STRIP_CURRENCY = "strip_currency"
    NULL_IF = "null_if"
    REPLACE = "replace"
    SPLIT_TAKE = "split_take"
    MAP_VALUES = "map_values"
    ROUND_NUMBER = "round_number"


class FieldRef(StrictModel):
    source_id: str
    resource_id: str
    field_path: str


class ResourceSummary(StrictModel):
    resource_id: str
    name: str
    kind: Literal["collection", "table", "sheet", "file"]
    field_count: int = Field(ge=0)


class InventoryField(StrictModel):
    ref: FieldRef
    type: SourceType
    nullable: bool
    repeating: bool
    samples: list[str] = Field(default_factory=list, max_length=3)
    description: str | None = None
    ambiguity: str | None = None
    status: Literal["stable", "new", "unknown"]
    native_type: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def parse_type(cls, value):
        return value if isinstance(value, SourceType) else SourceType(value)


class InventoryView(StrictModel):
    snapshot_id: str
    resources: list[ResourceSummary]
    fields: list[InventoryField]


class EvidenceRef(StrictModel):
    resource_id: str
    field_path: str | None = None
    profile_ref: str | None = None


class Attribute(StrictModel):
    id: Identifier
    type: SourceType
    nullable: bool
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguity: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def parse_type(cls, value):
        return value if isinstance(value, SourceType) else SourceType(value)


class Relationship(StrictModel):
    from_ref: Identifier = Field(alias="from")
    to_ref: Identifier
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    evidence: list[EvidenceRef] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=True)


class Table(StrictModel):
    id: Identifier
    name: Identifier
    kind: Literal["entity", "event", "reference"]
    grain: str = Field(min_length=1, max_length=300)
    key: list[Identifier] = Field(min_length=1)
    attributes: list[Attribute]
    relationships: list[Relationship]
    rationale: str = Field(min_length=1, max_length=1000)


class SourceCoverage(StrictModel):
    field_path: str
    resource_id: str
    disposition: Disposition
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("disposition", mode="before")
    @classmethod
    def parse_disposition(cls, value):
        return value if isinstance(value, Disposition) else Disposition(value)


class ModelDraft(StrictModel):
    revision: int = Field(ge=0)
    tables: list[Table] = Field(min_length=1)
    source_coverage: list[SourceCoverage]
    unresolved: list[str] = Field(default_factory=list)
    notes: str | None = None


class TransformOp(StrictModel):
    name: TransformName
    args: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def parse_name(cls, value):
        return value if isinstance(value, TransformName) else TransformName(value)


class Mapping(StrictModel):
    target: Identifier
    sources: list[Identifier] = Field(min_length=1)
    operations: list[TransformOp] = Field(default_factory=list)
    join_path: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = None


class MappingDraft(StrictModel):
    revision: int = Field(ge=0)
    based_on_model_revision: int = Field(ge=0)
    mappings: list[Mapping]
    unmapped_targets: list[Identifier] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ValidationFinding(StrictModel):
    code: FindingCode
    severity: Severity
    target: Identifier | None = None
    message: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("code", mode="before")
    @classmethod
    def parse_code(cls, value):
        return value if isinstance(value, FindingCode) else FindingCode(value)

    @field_validator("severity", mode="before")
    @classmethod
    def parse_severity(cls, value):
        return value if isinstance(value, Severity) else Severity(value)


class CoverageRecord(StrictModel):
    resource_id: str
    field_path: str
    disposition: Disposition
    reason: str = Field(min_length=1)

    @field_validator("disposition", mode="before")
    @classmethod
    def parse_disposition(cls, value):
        return value if isinstance(value, Disposition) else Disposition(value)


class FailureInfo(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class AgentBudgets(StrictModel):
    max_revisions: int = Field(default=3, ge=0)
    max_tool_calls: int = Field(default=40, ge=0)
    max_model_calls: int = Field(default=20, ge=0)
    max_tokens: int = Field(default=400_000, ge=0)
    max_cost_usd: float = Field(default=5.0, ge=0)
    max_wall_clock_seconds: int = Field(default=3600, ge=0)
    max_tool_rows: int = Field(default=500, ge=0)
    max_tool_bytes: int = Field(default=2_000_000, ge=0)
    model_node_timeout_seconds: int = Field(default=960, ge=0)
    tool_node_timeout_seconds: int = Field(default=120, ge=0)
    recursion_limit: int = Field(default=200, ge=1)


class ToolCallRequest(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolResultRef(StrictModel):
    tool_call_id: str
    tool: str
    status: Literal["ok", "error"]
    result_ref: str
    replayed: bool = False
