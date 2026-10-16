"""Single-host intake storage: JSON Lines records and a transactional local catalog."""

import json
import os
import shutil
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from .metadata import (CollectionMetadata, HeaderMetadata, SnapshotMetadata,
                       SourceIdentity, stable_id)
from .writer import PublicationConflict


class IntakeNotFoundError(LookupError):
    """No accessible intake artifact exists in this store's scope."""


def _encode(snapshot: SnapshotMetadata) -> str:
    data = asdict(snapshot)
    data["uploaded_at"] = snapshot.uploaded_at.isoformat()
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def _decode(payload: str) -> SnapshotMetadata:
    data = json.loads(payload)
    source = SourceIdentity(**data.pop("source"))
    collections = []
    for item in data.pop("collections"):
        headers = tuple(HeaderMetadata(**header) for header in item.pop("headers"))
        warnings = tuple(item.pop("warnings"))
        collections.append(CollectionMetadata(headers=headers, warnings=warnings, **item))
    return SnapshotMetadata(source=source, collections=tuple(collections),
                            uploaded_at=datetime.fromisoformat(data.pop("uploaded_at")), **data)


def _sync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class LocalIntakeStore:
    """Construct only with a private absolute root and server-authorized scope.

    The caller authorizes identity. Scoping prevents accidental cross-organization
    lookup, but is not protection from a user who can access the storage directory.
    """

    def __init__(self, root: Path, *, organization_id: str, environment: str):
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("Intake storage root must be an absolute path.")
        if not organization_id.strip() or not environment.strip():
            raise ValueError("Organization and environment must be nonempty.")
        self.organization_id = organization_id
        self.environment = environment
        self.root = root.resolve()
        self.scope = self.root / stable_id("scope", organization_id, environment)
        self.records = self.scope / "records"
        for directory in (self.root, self.scope, self.records):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.catalog = self.scope / "catalog.sqlite3"
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    manifest TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0
                        CHECK (published IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS collections (
                    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 0
                        CHECK (complete IN (0, 1)),
                    PRIMARY KEY (batch_id, id)
                );
                CREATE TABLE IF NOT EXISTS active_sources (
                    source_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id)
                );
            """)
        for directory in (self.records, self.scope, self.root, self.root.parent):
            _sync_directory(directory)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.catalog)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection

    def _batch_path(self, batch_id: str) -> Path:
        return self.records / stable_id("batch", batch_id)

    def _collection_path(self, batch_id: str, collection_id: str) -> Path:
        return self._batch_path(batch_id) / (stable_id("collection", collection_id) + ".jsonl")

    @staticmethod
    def _batch(connection: sqlite3.Connection, batch_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise IntakeNotFoundError("Batch not found.")
        return row

    def active_snapshot(self, source_id: str) -> SnapshotMetadata | None:
        with self._connection() as connection:
            row = connection.execute("""SELECT b.manifest FROM active_sources a
                JOIN batches b ON b.id = a.batch_id WHERE a.source_id = ?""", (source_id,)).fetchone()
        return _decode(row["manifest"]) if row else None

    def stage(self, snapshot: SnapshotMetadata) -> None:
        if (snapshot.source.organization_id, snapshot.source.environment) != (self.organization_id, self.environment):
            raise PermissionError("Snapshot does not belong to this storage scope.")
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO batches (id, source_id, manifest) VALUES (?, ?, ?)",
                               (snapshot.batch_id, snapshot.source_id, _encode(snapshot)))
            connection.executemany("INSERT INTO collections (batch_id, id) VALUES (?, ?)",
                                   [(snapshot.batch_id, item.collection_id) for item in snapshot.collections])

    def write_collection(self, batch_id: str, collection_id: str,
                         records: Sequence[Mapping[str, object]]) -> None:
        with self._connection(write=True) as connection:
            batch = self._batch(connection, batch_id)
            if batch["published"]:
                raise ValueError("Published batches are immutable.")
            row = connection.execute("SELECT complete FROM collections WHERE batch_id = ? AND id = ?",
                                     (batch_id, collection_id)).fetchone()
            if row is None:
                raise IntakeNotFoundError("Collection not found.")
            if row["complete"]:
                raise ValueError("Collection has already been written.")
            metadata = next(item for item in _decode(batch["manifest"]).collections
                            if item.collection_id == collection_id)
            if len(records) != metadata.row_count:
                raise ValueError("Collection row count does not match its manifest.")
            target = self._collection_path(batch_id, collection_id)
            target.parent.mkdir(exist_ok=True, mode=0o700)
            _sync_directory(self.records)
            temporary = target.with_suffix(".partial")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                for record in records:
                    stream.write(json.dumps(dict(record), ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            _sync_directory(target.parent)
            connection.execute("UPDATE collections SET complete = 1 WHERE batch_id = ? AND id = ?",
                               (batch_id, collection_id))

    def publish(self, batch_id: str, expected_batch_id: str | None) -> None:
        with self._connection(write=True) as connection:
            batch = self._batch(connection, batch_id)
            if batch["published"]:
                raise ValueError("Batch has already been published.")
            incomplete = connection.execute("SELECT 1 FROM collections WHERE batch_id = ? AND complete = 0",
                                            (batch_id,)).fetchone()
            if incomplete:
                raise ValueError("Cannot publish an incomplete batch.")
            active = connection.execute("SELECT batch_id FROM active_sources WHERE source_id = ?",
                                        (batch["source_id"],)).fetchone()
            if (active["batch_id"] if active else None) != expected_batch_id:
                raise PublicationConflict("Source changed before publication.")
            connection.execute("UPDATE batches SET published = 1 WHERE id = ?", (batch_id,))
            connection.execute("""INSERT INTO active_sources (source_id, batch_id) VALUES (?, ?)
                ON CONFLICT(source_id) DO UPDATE SET batch_id = excluded.batch_id""",
                               (batch["source_id"], batch_id))

    def discard_unpublished(self, batch_id: str) -> None:
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT published FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if row and row["published"]:
                raise ValueError("Cannot discard a published batch.")
            # Remove visibility before file cleanup; interrupted cleanup leaves only
            # unreachable files, never a complete manifest pointing at missing data.
            connection.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
        try:
            shutil.rmtree(self._batch_path(batch_id))
        except FileNotFoundError:
            pass  # An absent staging directory is the desired idempotent result.
        _sync_directory(self.records)

    def published_snapshot(self, source_id: str, batch_id: str) -> SnapshotMetadata:
        """Read a published batch, including one superseded by a newer import."""
        with self._connection() as connection:
            row = connection.execute("""SELECT manifest FROM batches
                WHERE id = ? AND source_id = ? AND published = 1""", (batch_id, source_id)).fetchone()
        if row is None:
            raise IntakeNotFoundError("Published batch not found.")
        return _decode(row["manifest"])

    def read_sample(self, source_id: str, batch_id: str, collection_id: str,
                    *, limit: int = 500) -> list[dict[str, object]]:
        """Read first-N parsed records from one published, explicitly pinned batch."""
        if not 1 <= limit <= 500:
            raise ValueError("Sample limit must be between 1 and 500.")
        snapshot = self.published_snapshot(source_id, batch_id)
        collection = next((item for item in snapshot.collections if item.collection_id == collection_id), None)
        if collection is None:
            raise IntakeNotFoundError("Collection not found.")
        expected = min(limit, collection.row_count)
        records: list[dict[str, object]] = []
        with self._collection_path(batch_id, collection_id).open(encoding="utf-8") as stream:
            for line in islice(stream, expected):
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Stored collection must contain JSON objects.")
                records.append(record)
        if len(records) != expected:
            raise ValueError("Stored collection ended before its manifest row count.")
        return records
