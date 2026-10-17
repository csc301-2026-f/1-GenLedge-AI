"""Storage contract: a real adapter must enforce these semantics durably."""
from typing import Mapping, Protocol, Sequence

from .metadata import SnapshotMetadata


class IntakeNotFoundError(LookupError):
    """No accessible intake artifact exists in this store's scope."""


class PublicationConflict(RuntimeError):
    """The source changed since the import read its active batch; retry explicitly."""


class IntakeWriter(Protocol):
    def active_snapshot(self, source_id: str) -> SnapshotMetadata | None:
        """Return the published manifest only, or None for a new source."""
        ...

    def stage(self, snapshot: SnapshotMetadata) -> None:
        """Create an unpublished batch manifest. Reject duplicate batch IDs.

        Must not create/replace an active source or modify existing snapshots.
        """
        ...

    def write_collection(self, batch_id: str, collection_id: str,
                         records: Sequence[Mapping[str, object]]) -> None:
        """Write only to the staged batch. Preserve nested data and original keys.

        Mark collection complete only after all records are durably written.
        Reject unknown collections, repeated writes, and mismatched row counts.
        Zero-row collections also require a completion marker.
        """
        ...

    def publish(self, batch_id: str, expected_batch_id: str | None) -> None:
        """Verify every collection complete, then atomically publish the manifest.

        Compare source.active_batch_id to expected_batch_id (None means absent).
        Raise PublicationConflict on mismatch without changing the active batch.
        Never expose a mix of old/new collections or delete old snapshots.
        Other exceptions may mean commit succeeded but acknowledgement was lost;
        callers must retain this batch and reconcile its status before cleanup.
        """
        ...

    def discard_unpublished(self, batch_id: str) -> None:
        """Idempotently discard partial staging; never delete a published batch.

        Failed cleanup must be recoverable by later orphan reconciliation.
        """
        ...
