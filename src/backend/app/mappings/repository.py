"""Organization-scoped persistence; proposal rules and lifecycle live in services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.agent.contracts import (
    CONTRACT_VERSION, AgentBudgets, CoverageRecord, FailureInfo, JobStatus,
    MappingDraft, ModelDraft, PersistedArtifact, SourceType, ValidationFinding,
)
from app.common.database import Database, NotFoundError, PersistenceConflict


def validated_json(model: BaseModel) -> dict:
    """Frozen models contain mutable collections: validate again on write."""
    return type(model).model_validate_json(model.model_dump_json()).model_dump(mode="json", by_alias=True)


def from_json(model_type, payload):
    return model_type.model_validate_json(json.dumps(payload))


class MappingRepository:
    def __init__(self, database: Database, *, organization_id: str):
        self.database = database
        self.organization_id = organization_id

    def _job(self, connection, job_id: str, *, lock: bool = False) -> dict:
        row = connection.execute("SELECT * FROM proposal_jobs WHERE id = %s AND organization_id = %s"
                                 + (" FOR UPDATE" if lock else ""), (job_id, self.organization_id)).fetchone()
        if not row:
            raise NotFoundError("Job not found")
        PersistedArtifact(contract_version=row["contract_version"])
        row["status"] = JobStatus(row["status"])
        row["budgets"] = from_json(AgentBudgets, row.pop("budgets_json"))
        failure = row.pop("failure_json")
        row["failure"] = from_json(FailureInfo, failure) if failure is not None else None
        row["source_snapshot_ids"] = [item["snapshot_id"] for item in connection.execute(
            "SELECT snapshot_id FROM proposal_job_snapshots WHERE job_id = %s ORDER BY position", (job_id,))]
        return row

    def create_job(self, *, source_snapshot_ids: list[str], idempotency_key: str,
                   created_by: str, catalog_ref: str | None = None,
                   budgets: AgentBudgets | None = None, model_mode: str = "auto") -> tuple[dict, bool]:
        if not idempotency_key or not source_snapshot_ids or len(set(source_snapshot_ids)) != len(source_snapshot_ids):
            raise ValueError("A nonempty idempotency key and unique snapshot IDs are required")
        if model_mode not in {"auto", "fake", "live"}:
            raise ValueError("Invalid model mode")
        budgets_json = validated_json(budgets or AgentBudgets())
        request = {"snapshots": source_snapshot_ids, "catalog_ref": catalog_ref, "budgets": budgets_json,
                   "model_mode": model_mode, "created_by": created_by}
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()
        job_id = str(uuid4())
        with self.database.transaction() as connection:
            for snapshot_id in source_snapshot_ids:
                if not connection.execute("""SELECT ss.id FROM source_snapshots ss JOIN sources s ON s.id = ss.source_id
                    WHERE ss.id = %s AND s.organization_id = %s AND ss.sealed""",
                                          (snapshot_id, self.organization_id)).fetchone():
                    raise NotFoundError("Source snapshot not found")
            if catalog_ref is not None:
                self._catalogue(connection, catalog_ref)
            inserted = connection.execute("""INSERT INTO proposal_jobs(id, organization_id, idempotency_key,
                request_hash, catalog_ref, created_by, active_thread_id, model_mode, budgets_json, contract_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (organization_id, idempotency_key) DO NOTHING RETURNING id""",
                (job_id, self.organization_id, idempotency_key, request_hash, catalog_ref, created_by,
                 job_id, model_mode, Jsonb(budgets_json), CONTRACT_VERSION)).fetchone()
            if inserted:
                for position, snapshot_id in enumerate(source_snapshot_ids):
                    connection.execute("INSERT INTO proposal_job_snapshots(job_id, snapshot_id, position) VALUES (%s, %s, %s)",
                                       (job_id, snapshot_id, position))
            else:
                existing = connection.execute("""SELECT id, request_hash FROM proposal_jobs
                    WHERE organization_id = %s AND idempotency_key = %s""", (self.organization_id, idempotency_key)).fetchone()
                if existing["request_hash"] != request_hash:
                    raise PersistenceConflict("Idempotency key already identifies a different job request")
                job_id = existing["id"]
            return self._job(connection, job_id), inserted is not None

    def get_job(self, job_id: str) -> dict:
        with self.database.transaction() as connection:
            return self._job(connection, job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT id FROM proposal_jobs WHERE organization_id = %s AND idempotency_key = %s",
                                     (self.organization_id, idempotency_key)).fetchone()
            return self._job(connection, row["id"]) if row else None

    def update_status(self, job_id: str, status: JobStatus, *, expected_status: JobStatus | None = None,
                      failure: FailureInfo | None = None) -> dict:
        status = JobStatus(status)
        with self.database.transaction() as connection:
            job = self._job(connection, job_id, lock=True)
            if expected_status is not None and job["status"] != JobStatus(expected_status):
                raise PersistenceConflict("Job status changed concurrently")
            connection.execute("UPDATE proposal_jobs SET status = %s, failure_json = %s, updated_at = now() WHERE id = %s",
                               (status.value, Jsonb(validated_json(failure)) if failure is not None else None, job_id))
            return self._job(connection, job_id)

    def save_revision(self, job_id: str, model_draft: ModelDraft, *, mapping_draft: MappingDraft | None = None,
                      findings: Sequence[ValidationFinding] = (), coverage: Sequence[CoverageRecord] = (),
                      table_is_new: dict[str, bool] | None = None) -> dict:
        model_json = validated_json(model_draft)
        mapping_json = validated_json(mapping_draft) if mapping_draft is not None else None
        findings_json = [validated_json(item) for item in findings]
        coverage_json = [validated_json(item) for item in coverage]
        flags = dict(table_is_new or {})
        if any(not isinstance(key, str) or type(value) is not bool for key, value in flags.items()):
            raise ValueError("table_is_new must map table IDs to booleans")
        with self.database.transaction() as connection:
            self._job(connection, job_id, lock=True)
            existing = connection.execute("SELECT id FROM proposal_revisions WHERE job_id = %s AND revision = %s",
                                          (job_id, model_json["revision"])).fetchone()
            if existing:
                package = self._revision(connection, existing["id"])
                if (validated_json(package["model_draft"]) != model_json
                        or (validated_json(package["mapping_draft"]) if package["mapping_draft"] else None) != mapping_json
                        or [validated_json(item) for item in package["findings"]] != findings_json
                        or [validated_json(item) for item in package["coverage"]] != coverage_json
                        or package["table_is_new"] != flags):
                    raise PersistenceConflict("Revision already identifies different immutable content")
                return package
            revision_id = str(uuid4())
            connection.execute("""INSERT INTO proposal_revisions(id, job_id, revision, model_draft_json,
                mapping_draft_json, table_is_new_json, contract_version) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                               (revision_id, job_id, model_json["revision"], Jsonb(model_json),
                                Jsonb(mapping_json) if mapping_json is not None else None, Jsonb(flags), CONTRACT_VERSION))
            for position, item in enumerate(findings_json):
                connection.execute("INSERT INTO proposal_findings(revision_id, position, payload_json) VALUES (%s, %s, %s)",
                                   (revision_id, position, Jsonb(item)))
            for position, item in enumerate(coverage_json):
                connection.execute("""INSERT INTO source_coverage_records(revision_id, resource_id, field_path, position, payload_json)
                    VALUES (%s, %s, %s, %s, %s)""", (revision_id, item["resource_id"], item["field_path"], position, Jsonb(item)))
            return self._revision(connection, revision_id)

    def _revision(self, connection, revision_id: str) -> dict:
        row = connection.execute("SELECT * FROM proposal_revisions WHERE id = %s", (revision_id,)).fetchone()
        PersistedArtifact(contract_version=row["contract_version"])
        row["model_draft"] = from_json(ModelDraft, row.pop("model_draft_json"))
        mapping = row.pop("mapping_draft_json")
        row["mapping_draft"] = from_json(MappingDraft, mapping) if mapping is not None else None
        row["table_is_new"] = row.pop("table_is_new_json")
        row["findings"] = [from_json(ValidationFinding, item["payload_json"]) for item in connection.execute(
            "SELECT payload_json FROM proposal_findings WHERE revision_id = %s ORDER BY position", (revision_id,))]
        row["coverage"] = [from_json(CoverageRecord, item["payload_json"]) for item in connection.execute(
            "SELECT payload_json FROM source_coverage_records WHERE revision_id = %s ORDER BY position", (revision_id,))]
        return row

    def get_revision(self, job_id: str, revision: int | None = None) -> dict:
        with self.database.transaction() as connection:
            self._job(connection, job_id)
            query = "SELECT id FROM proposal_revisions WHERE job_id = %s"
            params = [job_id]
            if revision is not None:
                query += " AND revision = %s"
                params.append(revision)
            row = connection.execute(query + " ORDER BY revision DESC LIMIT 1", params).fetchone()
            if not row:
                raise NotFoundError("Revision not found")
            return self._revision(connection, row["id"])

    def _catalogue(self, connection, catalog_ref: str) -> dict:
        row = connection.execute("SELECT * FROM target_catalogues WHERE id = %s AND organization_id = %s",
                                 (catalog_ref, self.organization_id)).fetchone()
        if not row:
            raise NotFoundError("Catalogue not found")
        PersistedArtifact(contract_version=row["contract_version"])
        return row["payload_json"]

    def save_catalogue(self, catalog_ref: str, payload: dict) -> dict:
        # No catalogue model exists in contracts.py yet. Store names/types only.
        if set(payload) != {"tables"} or not isinstance(payload["tables"], list):
            raise ValueError("Catalogue must contain a tables list")
        for table in payload["tables"]:
            if set(table) != {"name", "columns"} or not isinstance(table["name"], str) or not isinstance(table["columns"], list):
                raise ValueError("Catalogue tables contain name and columns only")
            for column in table["columns"]:
                if set(column) != {"name", "type"} or not isinstance(column["name"], str):
                    raise ValueError("Catalogue columns contain name and type only")
                SourceType(column["type"])
        with self.database.transaction() as connection:
            inserted = connection.execute("""INSERT INTO target_catalogues(id, organization_id, payload_json, contract_version)
                VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
                                          (catalog_ref, self.organization_id, Jsonb(payload), CONTRACT_VERSION)).fetchone()
            if not inserted and self._catalogue(connection, catalog_ref) != payload:
                raise PersistenceConflict("Catalogue already identifies different immutable content")
            return self._catalogue(connection, catalog_ref)

    def get_catalogue(self, catalog_ref: str) -> dict:
        with self.database.transaction() as connection:
            return self._catalogue(connection, catalog_ref)

    def save_edit(self, job_id: str, *, edit_id: str, revision_id: str, reviewer: str,
                  reviewer_role: str, target: str, decision: str, idempotency_key: str) -> tuple[dict, bool]:
        if decision not in {"accept", "reject"} or not edit_id or not idempotency_key or not target:
            raise ValueError("A table decision, edit ID, target, and idempotency key are required")
        values = {"id": edit_id, "job_id": job_id, "revision_id": revision_id, "reviewer": reviewer,
                  "reviewer_role": reviewer_role, "target": target, "decision": decision, "idempotency_key": idempotency_key}
        with self.database.transaction() as connection:
            self._job(connection, job_id, lock=True)
            # IDs and request keys must both identify the same edit, including on replay.
            existing = connection.execute("SELECT * FROM proposal_edits WHERE id = %s OR (job_id = %s AND idempotency_key = %s)",
                                          (edit_id, job_id, idempotency_key)).fetchall()
            if existing:
                PersistedArtifact(contract_version=existing[0]["contract_version"])
                if len(existing) != 1 or any(existing[0][key] != value for key, value in values.items()):
                    raise PersistenceConflict("Edit ID or idempotency key already identifies a different decision")
                return existing[0], False
            row = connection.execute("""INSERT INTO proposal_edits(id, job_id, revision_id, reviewer, reviewer_role,
                target, decision, idempotency_key, contract_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                                     (*values.values(), CONTRACT_VERSION)).fetchone()
            return row, True

    def list_edits(self, job_id: str, *, pending_only: bool = False) -> list[dict]:
        with self.database.transaction() as connection:
            self._job(connection, job_id)
            rows = connection.execute("SELECT * FROM proposal_edits WHERE job_id = %s"
                                      + (" AND applied_at IS NULL" if pending_only else "")
                                      + " ORDER BY created_at, id", (job_id,)).fetchall()
            for row in rows:
                PersistedArtifact(contract_version=row["contract_version"])
            return rows

    def mark_edit_applied(self, job_id: str, edit_id: str) -> dict:
        with self.database.transaction() as connection:
            self._job(connection, job_id, lock=True)
            row = connection.execute("""UPDATE proposal_edits SET applied_at = COALESCE(applied_at, now())
                WHERE job_id = %s AND id = %s RETURNING *""", (job_id, edit_id)).fetchone()
            if not row:
                raise NotFoundError("Edit not found")
            PersistedArtifact(contract_version=row["contract_version"])
            return row
