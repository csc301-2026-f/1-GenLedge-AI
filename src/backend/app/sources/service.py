"""Import orchestration without Flask, credentials or a concrete database."""
from datetime import datetime, timezone
from typing import BinaryIO
from uuid import uuid4

from .connectors.files import parse_file
from .metadata import (CollectionMetadata, HeaderMetadata, SnapshotMetadata,
                       SourceIdentity, stable_id)
from .writer import IntakeWriter


class ImportStorageError(RuntimeError):
    def __init__(self, batch_id: str, phase: str, *, cleanup_failed: bool = False):
        super().__init__(f"Import batch {batch_id} failed during {phase}.")
        self.batch_id = batch_id
        self.phase = phase
        self.cleanup_failed = cleanup_failed


def import_file(filename: str, stream: BinaryIO, *, organization_id: str,
                environment: str, writer: IntakeWriter) -> SnapshotMetadata:
    """Validate, stage, then publish. Organization/environment must be authorized
    by the future caller, never trusted directly from browser form fields.
    """
    parsed = parse_file(filename, stream)
    source = SourceIdentity(organization_id, environment, parsed.filename)
    batch_id = uuid4().hex
    collections = []
    for collection in parsed.collections:
        collection_id = stable_id("col", source.source_id, collection.name)
        collections.append(CollectionMetadata(
            collection_id=collection_id, name=collection.name,
            intake_name=stable_id("intake", source.source_id, collection_id, batch_id),
            row_count=len(collection.records),
            headers=tuple(HeaderMetadata(**header) for header in collection.headers),
            warnings=tuple(collection.warnings),
        ))
    snapshot = SnapshotMetadata(
        source=source, batch_id=batch_id, uploaded_at=datetime.now(timezone.utc),
        format=parsed.format, size_bytes=parsed.size_bytes,
        collections=tuple(collections),
    )
    previous = writer.active_snapshot(source.source_id)
    try:
        writer.stage(snapshot)
        for metadata, collection in zip(snapshot.collections, parsed.collections):
            writer.write_collection(batch_id, metadata.collection_id, collection.records)
    except Exception as error:
        cleanup_failed = False
        try:
            writer.discard_unpublished(batch_id)
        except Exception:
            cleanup_failed = True
        raise ImportStorageError(batch_id, "staging", cleanup_failed=cleanup_failed) from error

    # No cleanup here: a timeout can occur AFTER a successful publish. Retain
    # the batch for reconciliation rather than risk deleting live data.
    try:
        writer.publish(batch_id, previous.batch_id if previous else None)
    except Exception as error:
        raise ImportStorageError(batch_id, "publication") from error
    return snapshot
