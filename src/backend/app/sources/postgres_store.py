"""Database intake adapter. PostgreSQL provides transactional row locking.

SQLite is supported only for isolated tests, not concurrent production intake.
"""
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .metadata import SnapshotMetadata, stable_id, decode_snapshot
from .writer import IntakeNotFoundError, PublicationConflict
from .fields import field_metadata
from .mapping_store import fields, mappings, reconcile, public_mapping

sources = sa.table('intake_sources', sa.column('scope_id'), sa.column('source_id'), sa.column('active_batch_id'))
batches = sa.table('intake_batches', sa.column('scope_id'), sa.column('batch_id'),
                   sa.column('source_id'), sa.column('status'), sa.column('manifest'),
                   sa.column('retired_at', sa.DateTime(timezone=True)), sa.column('purged', sa.Boolean))
pins = sa.table('intake_pins', sa.column('scope_id'), sa.column('batch_id'), sa.column('pin_id'))
collections = sa.table('intake_collections', sa.column('scope_id'), sa.column('batch_id'),
                       sa.column('collection_id'), sa.column('row_count', sa.Integer), sa.column('complete', sa.Boolean))
rows = sa.table('intake_records', sa.column('scope_id'), sa.column('batch_id'),
                sa.column('collection_id'), sa.column('ordinal', sa.Integer), sa.column('payload', sa.JSON))


def encode(snapshot):
    data = asdict(snapshot)
    data['uploaded_at'] = snapshot.uploaded_at.isoformat()
    # ASCII escaping also preserves surrogate escapes accepted by the file parser.
    return json.dumps(data, ensure_ascii=True, allow_nan=False)


class SnapshotExpiredError(LookupError):
    """Publication metadata exists, but retention has removed the record payloads."""


class PostgresIntakeStore:
    def __init__(self, engine, *, organization_id: str, environment: str):
        if not isinstance(organization_id, str) or not organization_id.strip() or not isinstance(environment, str) or not environment.strip():
            raise ValueError('Organization and environment must be nonempty strings.')
        if engine.dialect.name not in {'postgresql', 'sqlite'}:
            raise ValueError('Unsupported intake database.')
        self.engine = engine
        self.organization_id = organization_id
        self.environment = environment
        self.scope_id = stable_id('scope', organization_id, environment)

    def _where(self, table, batch_id):
        return sa.and_(table.c.scope_id == self.scope_id, table.c.batch_id == batch_id)

    def _insert_once(self, connection, table, values, keys):
        insert = pg_insert if self.engine.dialect.name == 'postgresql' else sqlite_insert
        connection.execute(insert(table).values(**values).on_conflict_do_nothing(index_elements=keys))

    def _batch(self, connection, batch_id):
        batch = connection.execute(sa.select(batches).where(self._where(batches, batch_id)).with_for_update()).mappings().first()
        if batch is None or batch['status'] == 'discarded':
            raise IntakeNotFoundError('Batch not found.')
        return batch

    def active_snapshot(self, source_id):
        with self.engine.connect() as connection:
            value = connection.execute(sa.select(batches.c.manifest).select_from(sources.join(batches,
                sa.and_(sources.c.scope_id == batches.c.scope_id, sources.c.active_batch_id == batches.c.batch_id)))
                .where(sources.c.scope_id == self.scope_id, sources.c.source_id == source_id,
                       batches.c.status == 'published')).scalar_one_or_none()
        return decode_snapshot(value) if value is not None else None

    def list_sources(self):
        with self.engine.connect() as connection:
            values = connection.execute(sa.select(batches.c.manifest).select_from(sources.join(batches,
                sa.and_(sources.c.scope_id == batches.c.scope_id, sources.c.active_batch_id == batches.c.batch_id)))
                .where(sources.c.scope_id == self.scope_id, batches.c.status == 'published')).scalars().all()
        return sorted((decode_snapshot(value) for value in values), key=lambda item: item.uploaded_at, reverse=True)

    def stage(self, snapshot: SnapshotMetadata):
        if (snapshot.source.organization_id, snapshot.source.environment) != (self.organization_id, self.environment):
            raise PermissionError('Snapshot does not belong to this storage scope.')
        with self.engine.begin() as connection:
            self._insert_once(connection, sources, dict(scope_id=self.scope_id, source_id=snapshot.source_id), ['scope_id', 'source_id'])
            # Batch IDs remain reserved even after discard. Duplicate staging fails.
            connection.execute(batches.insert().values(scope_id=self.scope_id, batch_id=snapshot.batch_id,
                source_id=snapshot.source_id, status='staged', manifest=encode(snapshot)))
            if snapshot.collections:
                connection.execute(collections.insert(), [dict(scope_id=self.scope_id, batch_id=snapshot.batch_id,
                    collection_id=item.collection_id, row_count=item.row_count, complete=False) for item in snapshot.collections])

    def write_collection(self, batch_id: str, collection_id: str, records: Sequence[Mapping[str, object]]):
        with self.engine.begin() as connection:
            batch = self._batch(connection, batch_id)
            if batch['status'] != 'staged':
                raise ValueError('Published batches are immutable.')
            where = sa.and_(self._where(collections, batch_id), collections.c.collection_id == collection_id)
            collection = connection.execute(sa.select(collections).where(where)).mappings().first()
            if collection is None:
                raise IntakeNotFoundError('Collection not found.')
            if collection['complete']:
                raise ValueError('Collection has already been written.')
            if len(records) != collection['row_count']:
                raise ValueError('Collection row count does not match its manifest.')
            for start in range(0, len(records), 500):
                chunk = []
                for ordinal in range(start, min(start + 500, len(records))):
                    record = dict(records[ordinal])
                    json.dumps(record, ensure_ascii=True, allow_nan=False)
                    chunk.append(dict(scope_id=self.scope_id, batch_id=batch_id, collection_id=collection_id,
                                      ordinal=ordinal, payload=record))
                connection.execute(rows.insert(), chunk)
            metadata = next(c for c in decode_snapshot(batch['manifest']).collections if c.collection_id == collection_id)
            self._write_fields(connection, batch_id, metadata, records)
            connection.execute(collections.update().where(where).values(complete=True))

    def _write_fields(self, connection, batch_id, collection, records):
        values = [dict(scope_id=self.scope_id, batch_id=batch_id, collection_id=collection.collection_id, **field)
                  for field in field_metadata(collection, records, batch_id)]
        for start in range(0, len(values), 500):
            connection.execute(fields.insert(), values[start:start + 500])

    def _ensure_fields(self, connection, batch):
        # Lazily profile pre-migration batches while holding a batch/source lock.
        if batch['purged']:
            raise SnapshotExpiredError('Snapshot records have expired.')
        for collection in decode_snapshot(batch['manifest']).collections:
            where = sa.and_(self._where(fields, batch['batch_id']), fields.c.collection_id == collection.collection_id)
            if connection.execute(sa.select(fields.c.field_id).where(where).limit(1)).first():
                continue
            records = connection.execute(sa.select(rows.c.payload).where(self._where(rows, batch['batch_id']),
                rows.c.collection_id == collection.collection_id)).scalars().all()
            self._write_fields(connection, batch['batch_id'], collection, records)

    def publish(self, batch_id, expected_batch_id):
        with self.engine.begin() as connection:
            batch = self._batch(connection, batch_id)
            if batch['status'] != 'staged':
                raise ValueError('Batch has already been published.')
            if connection.execute(sa.select(collections.c.collection_id).where(self._where(collections, batch_id),
                    collections.c.complete == False).limit(1)).first():
                raise ValueError('Cannot publish an incomplete batch.')
            where = sa.and_(sources.c.scope_id == self.scope_id, sources.c.source_id == batch['source_id'])
            active = connection.execute(sa.select(sources.c.active_batch_id).where(where).with_for_update()).scalar_one()
            if active != expected_batch_id:
                raise PublicationConflict('Source changed before publication.')
            reconcile(connection, self.scope_id, batch['source_id'], batch_id)
            if active is not None:
                connection.execute(batches.update().where(self._where(batches, active)).values(retired_at=datetime.now(timezone.utc)))
            connection.execute(batches.update().where(self._where(batches, batch_id)).values(status='published'))
            connection.execute(sources.update().where(where).values(active_batch_id=batch_id))

    def discard_unpublished(self, batch_id):
        with self.engine.begin() as connection:
            self._insert_once(connection, batches, dict(scope_id=self.scope_id, batch_id=batch_id, status='discarded'),
                              ['scope_id', 'batch_id'])
            batch = connection.execute(sa.select(batches).where(self._where(batches, batch_id)).with_for_update()).mappings().one()
            if batch['status'] == 'published':
                raise ValueError('Cannot discard a published batch.')
            connection.execute(rows.delete().where(self._where(rows, batch_id)))
            connection.execute(fields.delete().where(self._where(fields, batch_id)))
            connection.execute(collections.delete().where(self._where(collections, batch_id)))
            connection.execute(batches.update().where(self._where(batches, batch_id)).values(status='discarded', manifest=None))

    def published_snapshot(self, source_id, batch_id):
        with self.engine.connect() as connection:
            value = connection.execute(sa.select(batches.c.manifest).where(self._where(batches, batch_id),
                batches.c.source_id == source_id, batches.c.status == 'published')).scalar_one_or_none()
        if value is None:
            raise IntakeNotFoundError('Published batch not found.')
        return decode_snapshot(value)

    def read_sample(self, source_id, batch_id, collection_id, *, limit=500):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Sample limit must be an integer between 1 and 500.')
        with self.engine.begin() as connection:
            batch = connection.execute(sa.select(batches).where(self._where(batches, batch_id),
                batches.c.source_id == source_id, batches.c.status == 'published').with_for_update(read=True)).mappings().first()
            if batch is None:
                raise IntakeNotFoundError('Published batch not found.')
            if batch['purged']:
                raise SnapshotExpiredError('Snapshot records have expired. Read the active batch or acquire a pin before a longer workflow.')
            snapshot = decode_snapshot(batch['manifest'])
            collection = next((item for item in snapshot.collections if item.collection_id == collection_id), None)
            if collection is None:
                raise IntakeNotFoundError('Collection not found.')
            expected = min(limit, collection.row_count)
            result = connection.execute(sa.select(rows.c.payload).where(self._where(rows, batch_id),
                rows.c.collection_id == collection_id).order_by(rows.c.ordinal).limit(expected)).scalars().all()
        if len(result) != expected:
            raise ValueError('Stored collection ended before its manifest row count.')
        for record in result:
            if not isinstance(record, dict):
                raise ValueError('Stored collection must contain JSON objects.')
            json.dumps(record, allow_nan=False)
        return result

    def source_fields(self, source_id):
        with self.engine.begin() as connection:
            batch = self._active_locked(connection, source_id)
            self._ensure_fields(connection, batch)
            result = connection.execute(sa.select(fields).where(self._where(fields, batch['batch_id']))).mappings().all()
            return {'sourceId': source_id, 'batchId': batch['batch_id'], 'fields': [
                {'fieldId': f['field_id'], 'collectionId': f['collection_id'], 'path': f['path'],
                 'kinds': f['kinds'], 'matchable': f['matchable']} for f in result]}

    def _active_locked(self, connection, source_id):
        active = connection.execute(sa.select(sources.c.active_batch_id).where(sources.c.scope_id == self.scope_id,
            sources.c.source_id == source_id).with_for_update()).scalar_one_or_none()
        if active is None:
            raise IntakeNotFoundError('Source not found.')
        return connection.execute(sa.select(batches).where(self._where(batches, active))).mappings().one()

    def save_mapping(self, source_id, mapping_id, *, expected_batch_id, collection_id, field_ids, definition):
        if not isinstance(mapping_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', mapping_id):
            raise ValueError('Mapping ID must contain 1-128 letters, digits, underscores or hyphens.')
        if (not isinstance(field_ids, list) or not 1 <= len(field_ids) <= 1000 or
                not all(isinstance(f, str) for f in field_ids) or len(set(field_ids)) != len(field_ids)):
            raise ValueError('Supply 1-1000 distinct field IDs.')
        if not isinstance(definition, dict) or not definition:
            raise ValueError('Supply a nonempty mapping definition object.')
        encoded = json.dumps(definition, allow_nan=False)
        if len(encoded.encode('utf-8')) > 100_000:
            raise ValueError('Mapping definition exceeds 100 KB.')
        with self.engine.begin() as connection:
            batch = self._active_locked(connection, source_id)
            if batch['batch_id'] != expected_batch_id:
                raise PublicationConflict('Source changed; reload fields before saving the mapping.')
            self._ensure_fields(connection, batch)
            available = set(connection.scalars(sa.select(fields.c.field_id).where(self._where(fields, batch['batch_id']),
                fields.c.collection_id == collection_id)))
            if not set(field_ids) <= available:
                raise ValueError('Fields must belong to the active source collection.')
            values = dict(collection_id=collection_id, field_ids=field_ids, definition=definition, status='valid',
                          valid_batch_id=batch['batch_id'], checked_batch_id=batch['batch_id'])
            insert = pg_insert if self.engine.dialect.name == 'postgresql' else sqlite_insert
            connection.execute(insert(mappings).values(scope_id=self.scope_id, source_id=source_id, mapping_id=mapping_id,
                **values).on_conflict_do_update(index_elements=['scope_id', 'source_id', 'mapping_id'], set_=values))
            return public_mapping(dict(mapping_id=mapping_id, **values))

    def list_mappings(self, source_id):
        with self.engine.begin() as connection:
            batch = self._active_locked(connection, source_id)
            saved = connection.execute(sa.select(mappings).where(mappings.c.scope_id == self.scope_id,
                mappings.c.source_id == source_id).order_by(mappings.c.mapping_id)).mappings().all()
            return {'sourceId': source_id, 'batchId': batch['batch_id'], 'mappings': [public_mapping(m) for m in saved]}

    def delete_mapping(self, source_id, mapping_id, expected_batch_id):
        with self.engine.begin() as connection:
            batch = self._active_locked(connection, source_id)
            if batch['batch_id'] != expected_batch_id:
                raise PublicationConflict('Source changed; reload before deleting the mapping.')
            connection.execute(mappings.delete().where(mappings.c.scope_id == self.scope_id,
                mappings.c.source_id == source_id, mappings.c.mapping_id == mapping_id))

    def pin_snapshot(self, source_id, batch_id, pin_id):
        """Durable pin: release explicitly after the consumer finishes."""
        if not isinstance(pin_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', pin_id):
            raise ValueError('Invalid pin ID.')
        with self.engine.begin() as connection:
            batch = self._batch(connection, batch_id)
            if batch['source_id'] != source_id or batch['status'] != 'published':
                raise IntakeNotFoundError('Published batch not found.')
            if batch['purged']:
                raise SnapshotExpiredError('Snapshot records have expired.')
            self._insert_once(connection, pins, dict(scope_id=self.scope_id, batch_id=batch_id, pin_id=pin_id),
                              ['scope_id', 'batch_id', 'pin_id'])

    def release_pin(self, batch_id, pin_id):
        with self.engine.begin() as connection:
            connection.execute(pins.delete().where(self._where(pins, batch_id), pins.c.pin_id == pin_id))

    def sweep_snapshots(self, source_id, *, keep_previous=1, grace_days=7, now=None):
        """Remove only superseded payloads; preserve manifests and publication history."""
        if type(keep_previous) is not int or keep_previous < 0 or type(grace_days) is not int or grace_days < 0:
            raise ValueError('Retention values must be nonnegative integers.')
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=grace_days)
        removed = []
        with self.engine.begin() as connection:
            active = self._active_locked(connection, source_id)['batch_id']
            old = connection.execute(sa.select(batches.c.batch_id).where(batches.c.scope_id == self.scope_id,
                batches.c.source_id == source_id, batches.c.status == 'published', batches.c.batch_id != active)
                .order_by(batches.c.retired_at.desc(), batches.c.batch_id)).scalars().all()
            for batch_id in old[keep_previous:]:
                # Skip readers currently holding a shared lock instead of blocking them.
                candidate = connection.execute(sa.select(batches.c.batch_id).where(self._where(batches, batch_id),
                    batches.c.purged == False, batches.c.retired_at <= cutoff)
                    .with_for_update(skip_locked=True)).first()
                if candidate is None:
                    continue
                if connection.execute(sa.select(pins.c.pin_id).where(self._where(pins, batch_id)).limit(1)).first():
                    continue
                if connection.execute(sa.select(mappings.c.mapping_id).where(mappings.c.scope_id == self.scope_id,
                    mappings.c.valid_batch_id == batch_id).limit(1)).first():
                    continue
                connection.execute(rows.delete().where(self._where(rows, batch_id)))
                connection.execute(batches.update().where(self._where(batches, batch_id)).values(purged=True))
                removed.append(batch_id)
        return removed
