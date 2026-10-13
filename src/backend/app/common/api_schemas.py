"""Shared HTTP request and response contracts for mapping jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.agent.contracts import (
    CoverageRecord, FailureInfo, Identifier, JobStatus, MappingDraft, ModelDraft,
    PersistedArtifact, StrictModel, ValidationFinding,
)


class CreateMappingJobRequest(StrictModel):
    source_snapshot_id: str | None = None
    catalog_ref: str | None = None


class CreateMappingJobResponse(StrictModel):
    job_id: str
    status: JobStatus


class MappingJobResponse(StrictModel):
    job_id: str
    status: JobStatus
    source_snapshot_id: str
    model_mode: Literal["fake", "live"] | None = None
    failure: FailureInfo | None = None


class MappingPackageResponse(StrictModel):
    payload: dict[str, object] | None = None
    status: JobStatus | None = None
    failure: FailureInfo | None = None


class EditMappingRequest(StrictModel):
    edit_id: str = Field(min_length=1)
    target: Identifier
    decision: Literal["accept", "reject"]


class EditMappingResponse(StrictModel):
    payload: dict[str, object] | None = None
    replayed: bool = False


# HTTP package composition belongs to Person D; all domain values remain canonical.
class RoutingReviewPackage(PersistedArtifact):
    model_draft: ModelDraft
    mapping_draft: MappingDraft
    findings: list[ValidationFinding]
    coverage: list[CoverageRecord]
    is_new: dict[str, bool]
    decisions: dict[str, Literal['accept', 'reject']] = Field(default_factory=dict)
