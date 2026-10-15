"""Durable evidence and replay cache, independent of tools and graph code."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.agent.contracts import CONTRACT_VERSION, PersistedArtifact, ToolCallRequest, ToolResultRef
from app.common.database import NotFoundError, PersistenceConflict
from .repository import MappingRepository, validated_json


class ToolResultRepository(MappingRepository):
    def get_result(self, result_ref: str) -> dict:
        """Resolve a compact evidence reference in this organization's scope."""
        with self.database.transaction() as connection:
            row = connection.execute("""SELECT t.* FROM tool_results t JOIN proposal_jobs j ON j.id = t.job_id
                WHERE t.id = %s AND j.organization_id = %s""", (result_ref, self.organization_id)).fetchone()
            if not row:
                raise NotFoundError("Tool result not found")
            PersistedArtifact(contract_version=row["contract_version"])
            return {"ref": ToolResultRef(tool_call_id=row["tool_call_id"], tool=row["tool"],
                                         status=row["status"], result_ref=row["id"]), "payload": row["payload_json"]}

    def _result(self, connection, job_id: str, call: ToolCallRequest) -> dict | None:
        row = connection.execute("SELECT * FROM tool_results WHERE job_id = %s AND tool_call_id = %s",
                                 (job_id, call.id)).fetchone()
        if not row:
            return None
        PersistedArtifact(contract_version=row["contract_version"])
        if row["tool"] != call.name or row["arguments_json"] != call.arguments:
            raise PersistenceConflict("Tool call ID already identifies a different request")
        return {"ref": ToolResultRef(tool_call_id=call.id, tool=row["tool"], status=row["status"],
                                     result_ref=row["id"], replayed=True), "payload": row["payload_json"]}

    def replay(self, job_id: str, call: ToolCallRequest) -> dict | None:
        validated_json(call)
        with self.database.transaction() as connection:
            self._job(connection, job_id)
            return self._result(connection, job_id, call)

    def get_or_record(self, job_id: str, call: ToolCallRequest,
                      result_factory: Callable[[], tuple[Literal["ok", "error"], dict]], *, redacted: bool) -> dict:
        """Replay or invoke a caller-owned factory once for each committed call.

        The caller owns authorization, budgets, dispatch, and redaction. The lock
        serializes duplicate calls across processes. A crash before commit can
        require repeating the external read; committed results always replay.
        """
        arguments = validated_json(call)["arguments"]
        if redacted is not True:
            raise ValueError("Only caller-redacted tool payloads may be persisted")
        with self.database.transaction() as connection:
            self._job(connection, job_id)
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (job_id, call.id))
            existing = self._result(connection, job_id, call)
            if existing:
                return existing
            status, payload = result_factory()
            serialized = json.dumps(payload, allow_nan=False)
            result_ref = str(uuid4())
            ref = ToolResultRef(tool_call_id=call.id, tool=call.name, status=status, result_ref=result_ref)
            connection.execute("""INSERT INTO tool_results(id, job_id, tool_call_id, tool, arguments_json, status,
                payload_json, redacted, bytes_estimate, contract_version) VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s)""",
                               (result_ref, job_id, call.id, call.name, Jsonb(arguments), status,
                                Jsonb(payload), len(serialized.encode()), CONTRACT_VERSION))
            return {"ref": ref, "payload": json.loads(serialized)}

    def save_result(self, job_id: str, call: ToolCallRequest, *, status: Literal["ok", "error"],
                    payload: dict, redacted: bool) -> ToolResultRef:
        """Store an already dispatched/redacted result; first committed result wins."""
        return self.get_or_record(job_id, call, lambda: (status, payload), redacted=redacted)["ref"]
