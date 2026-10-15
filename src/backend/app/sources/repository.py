"""Atomic publication and loading of immutable discovered metadata."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from app.agent.contracts import CONTRACT_VERSION, InventoryView, PersistedArtifact
from app.common.database import Database, NotFoundError, PersistenceConflict


class InventoryRepository:
    def __init__(self, database: Database):
        self.database = database

    def save_snapshot(self, inventory: InventoryView, *, source_id: str,
                      organization_id: str, source_name: str) -> InventoryView:
        # Frozen models still contain mutable lists: revalidate before persistence.
        inventory = InventoryView.model_validate_json(inventory.model_dump_json())
        resources = {resource.resource_id for resource in inventory.resources}
        refs = {(field.ref.resource_id, field.ref.field_path) for field in inventory.fields}
        if len(resources) != len(inventory.resources) or len(refs) != len(inventory.fields):
            raise ValueError("Resource and field references must be unique within a snapshot")
        counts = Counter(field.ref.resource_id for field in inventory.fields)
        if any(field.ref.source_id != source_id or field.ref.resource_id not in resources for field in inventory.fields):
            raise ValueError("Fields must belong to this source and a snapshot resource")
        if any(resource.field_count != counts[resource.resource_id] for resource in inventory.resources):
            raise ValueError("Resource field_count must match its fields")
        payload = inventory.model_dump(mode="json", exclude={"snapshot_id"})
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.database.transaction() as connection:
            connection.execute("""INSERT INTO sources(id, organization_id, name) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING""", (source_id, organization_id, source_name))
            source = connection.execute("SELECT organization_id FROM sources WHERE id = %s FOR UPDATE", (source_id,)).fetchone()
            if source["organization_id"] != organization_id:
                raise PersistenceConflict("Source belongs to a different organization")
            # The source lock serializes publication and fingerprint deduplication.
            existing = connection.execute("SELECT id FROM source_snapshots WHERE source_id = %s AND fingerprint = %s",
                                          (source_id, fingerprint)).fetchone()
            occupied = connection.execute("SELECT id, source_id, fingerprint FROM source_snapshots WHERE id = %s",
                                          (inventory.snapshot_id,)).fetchone()
            if occupied and (occupied["source_id"] != source_id or occupied["fingerprint"] != fingerprint):
                raise PersistenceConflict("Snapshot ID already identifies different immutable content")
            if existing:
                snapshot_id = existing["id"]
            else:
                snapshot_id = inventory.snapshot_id
                connection.execute("""INSERT INTO source_snapshots(id, source_id, fingerprint, contract_version)
                    VALUES (%s, %s, %s, %s)""", (snapshot_id, source_id, fingerprint, CONTRACT_VERSION))
                for position, resource in enumerate(inventory.resources):
                    connection.execute("""INSERT INTO source_resources(snapshot_id, resource_id, name, kind, position)
                        VALUES (%s, %s, %s, %s, %s)""", (snapshot_id, resource.resource_id, resource.name, resource.kind, position))
                for position, field in enumerate(inventory.fields):
                    connection.execute("""INSERT INTO source_fields(snapshot_id, resource_id, field_path, type,
                        nullable, repeating, samples, description, native_type, ambiguity, status, position)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                       (snapshot_id, field.ref.resource_id, field.ref.field_path, field.type.value,
                                        field.nullable, field.repeating, field.samples, field.description,
                                        field.native_type, field.ambiguity, field.status, position))
                connection.execute("UPDATE source_snapshots SET sealed = true WHERE id = %s", (snapshot_id,))
        return self.get_inventory(snapshot_id, organization_id=organization_id)

    def get_inventory(self, snapshot_id: str, *, organization_id: str | None = None) -> InventoryView:
        with self.database.transaction() as connection:
            snapshot = connection.execute("""SELECT ss.source_id, ss.contract_version, s.organization_id
                FROM source_snapshots ss JOIN sources s ON s.id = ss.source_id
                WHERE ss.id = %s AND ss.sealed""", (snapshot_id,)).fetchone()
            if not snapshot or (organization_id is not None and snapshot["organization_id"] != organization_id):
                raise NotFoundError("Source snapshot not found")
            PersistedArtifact(contract_version=snapshot["contract_version"])
            resources = connection.execute("""SELECT r.resource_id, r.name, r.kind,
                (SELECT count(*) FROM source_fields f WHERE f.snapshot_id = r.snapshot_id
                 AND f.resource_id = r.resource_id)::integer AS field_count
                FROM source_resources r WHERE r.snapshot_id = %s ORDER BY r.position""", (snapshot_id,)).fetchall()
            fields = connection.execute("""SELECT resource_id, field_path, type, nullable, repeating,
                samples, description, native_type, ambiguity, status FROM source_fields
                WHERE snapshot_id = %s ORDER BY position""", (snapshot_id,)).fetchall()
        for field in fields:
            field["ref"] = {"source_id": snapshot["source_id"], "resource_id": field.pop("resource_id"),
                            "field_path": field.pop("field_path")}
        return InventoryView.model_validate({"snapshot_id": snapshot_id, "resources": resources, "fields": fields})
