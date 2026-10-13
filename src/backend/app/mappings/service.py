"""US4 lifecycle orchestration. Storage, graph and validation are injected owners' ports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol
from uuid import uuid4

from app.agent.contracts import FailureInfo, InventoryView, JobStatus, ModelDraft, Severity
from app.common.api_schemas import (
    CreateMappingJobRequest, EditMappingRequest, MappingJobResponse, RoutingReviewPackage,
)


class MappingError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class JobRecord:
    """Internal ownership and request metadata around the canonical HTTP job contract."""
    view: MappingJobResponse
    owner: str
    idempotency_key: str
    request: CreateMappingJobRequest


class RoutingRepository(Protocol):
    """Person A adapter. Every returned value is detached from mutable DB state.

    create_job is atomic by (owner, idempotency_key), comparing request bodies
    and raising idempotency_conflict on reuse with different inputs. claim_job
    atomically transitions queued -> running. publish atomically commits package,
    mappings, findings, coverage and status. save_decision locks the job, checks
    reviewability and table membership, and atomically stores the decision and
    edit receipt by (job_id, edit_id). Exact replay returns the original receipt;
    conflicting payloads raise edit_conflict. No transaction spans a model call.
    """
    def find_job(self, owner: str, key: str) -> JobRecord | None: ...
    def create_job(self, job: JobRecord) -> tuple[JobRecord, bool]: ...
    def get_job(self, owner: str, job_id: str) -> JobRecord | None: ...
    def claim_job(self, owner: str, job_id: str) -> bool: ...
    def save_model_draft(self, owner: str, job_id: str, draft: ModelDraft) -> None: ...
    def publish(self, owner: str, job_id: str, package: RoutingReviewPackage, status: JobStatus) -> None: ...
    def fail(self, owner: str, job_id: str, failure: FailureInfo) -> None: ...
    def get_package(self, owner: str, job_id: str) -> RoutingReviewPackage | None: ...
    def save_decision(self, owner: str, job_id: str, edit: EditMappingRequest) -> tuple[RoutingReviewPackage, bool]: ...


class InventoryReader(Protocol):
    def __call__(self, owner: str, snapshot_id: str) -> InventoryView | None: ...


class GraphRunner(Protocol):
    def __call__(self, job_id: str, snapshot_id: str, catalog_ref: str | None) -> ModelDraft | FailureInfo: ...


class Projector(Protocol):
    """Person C adapter returns a redacted, validated review package, no raw rows."""
    def __call__(self, draft: ModelDraft, inventory: InventoryView, catalog_ref: str | None) -> RoutingReviewPackage: ...


class MappingService:
    def __init__(self, repository: RoutingRepository, inventory: InventoryReader,
                 run_graph: GraphRunner, project: Projector,
                 model_mode: Literal['fake', 'live'], default_snapshot_id: str | None = None):
        if model_mode not in ('fake', 'live'):
            raise ValueError('Use the model mode resolved by Person B.')
        self.repository = repository
        self.inventory = inventory
        self.run_graph = run_graph
        self.project = project
        self.model_mode = model_mode
        self.default_snapshot_id = default_snapshot_id

    def create(self, owner: str, key: str, request: CreateMappingJobRequest,
               dispatch: Callable[[str, str], None]) -> MappingJobResponse:
        existing = self.repository.find_job(owner, key)
        if existing:
            if existing.request != request:
                raise MappingError('idempotency_conflict', 'This key was already used for another request.')
            return existing.view
        if request.source_snapshot_id is not None and not request.source_snapshot_id.strip():
            raise MappingError('snapshot_required', 'Enter a non-empty source snapshot ID.', 400)
        snapshot_id = request.source_snapshot_id if request.source_snapshot_id is not None else self.default_snapshot_id
        if not snapshot_id:
            raise MappingError('snapshot_required', 'Enter a source snapshot ID.', 400)
        inventory = self.inventory(owner, snapshot_id)
        if inventory is None or inventory.snapshot_id != snapshot_id:
            raise MappingError('snapshot_not_found', 'Source snapshot not found.', 404)
        if not inventory.fields:
            raise MappingError('empty_inventory', 'The source snapshot has no fields.', 422)
        job = JobRecord(
            view=MappingJobResponse(job_id=str(uuid4()), status=JobStatus.QUEUED,
                                    source_snapshot_id=snapshot_id, model_mode=self.model_mode),
            owner=owner, idempotency_key=key, request=request,
        )
        persisted, created = self.repository.create_job(job)
        if created:
            try:
                dispatch(owner, persisted.view.job_id)
            except Exception:
                self.repository.fail(owner, persisted.view.job_id, FailureInfo(
                    code='dispatch_failed', message='Unable to start routing. Create a new job to retry.', retryable=True))
                return self.get(owner, persisted.view.job_id).view
        return persisted.view

    def get(self, owner: str, job_id: str) -> JobRecord:
        job = self.repository.get_job(owner, job_id)
        if job is None:
            raise MappingError('job_not_found', 'Routing job not found.', 404)
        return job

    def package(self, owner: str, job_id: str) -> tuple[MappingJobResponse, RoutingReviewPackage | None]:
        job = self.get(owner, job_id)
        return job.view, self.repository.get_package(owner, job_id)

    def decide(self, owner: str, job_id: str, edit: EditMappingRequest) -> tuple[RoutingReviewPackage, bool]:
        self.get(owner, job_id)
        # Atomic reviewability/target/replay checks belong with the repository write.
        return self.repository.save_decision(owner, job_id, edit)

    def execute(self, owner: str, job_id: str) -> None:
        """Worker entrypoint. Never call from an HTTP request thread."""
        if not self.repository.claim_job(owner, job_id):
            return
        try:
            job = self.get(owner, job_id)
            inventory = self.inventory(owner, job.view.source_snapshot_id)
            if inventory is None:
                raise MappingError('snapshot_not_found', 'Source snapshot not found.', 404)
            result = self.run_graph(job_id, inventory.snapshot_id, job.request.catalog_ref)
            if isinstance(result, FailureInfo):
                self.repository.fail(owner, job_id, result)
                return
            # Store the canonical model revision before invoking deterministic projection.
            draft = ModelDraft.model_validate(result)
            self.repository.save_model_draft(owner, job_id, draft)
            package = RoutingReviewPackage.model_validate(self.project(draft, inventory, job.request.catalog_ref))
            status = JobStatus.BLOCKED if any(f.severity == Severity.BLOCKER for f in package.findings) else JobStatus.AWAITING_REVIEW
            self.repository.publish(owner, job_id, package, status)
        except Exception:
            # Exceptions can contain provider requests, credentials or raw data.
            self.repository.fail(owner, job_id, FailureInfo(
                code='routing_failed', message='Routing could not complete. Create a new job to retry.', retryable=True))
