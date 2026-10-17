"""Database-independent metadata for a fully validated file snapshot."""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime


def stable_id(kind: str, *parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return f"{kind}_{hashlib.sha256(payload.encode()).hexdigest()}"


@dataclass(frozen=True)
class SourceIdentity:
    organization_id: str
    environment: str
    filename: str

    def __post_init__(self):
        for value in (self.organization_id, self.environment, self.filename):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Organization, environment and filename must be nonempty strings.")

    @property
    def source_id(self) -> str:
        return stable_id("src", self.organization_id, self.environment, self.filename)


@dataclass(frozen=True)
class HeaderMetadata:
    column: int
    original: str
    key: str


@dataclass(frozen=True)
class CollectionMetadata:
    collection_id: str
    name: str
    intake_name: str
    row_count: int
    headers: tuple[HeaderMetadata, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotMetadata:
    source: SourceIdentity
    batch_id: str
    uploaded_at: datetime
    format: str
    size_bytes: int
    collections: tuple[CollectionMetadata, ...]

    @property
    def source_id(self) -> str:
        return self.source.source_id


def decode_snapshot(payload: str) -> SnapshotMetadata:
    data = json.loads(payload)
    source = SourceIdentity(**data.pop("source"))
    collections = []
    for item in data.pop("collections"):
        headers = tuple(HeaderMetadata(**header) for header in item.pop("headers"))
        warnings = tuple(item.pop("warnings"))
        collections.append(CollectionMetadata(headers=headers, warnings=warnings, **item))
    return SnapshotMetadata(source=source, collections=tuple(collections),
                            uploaded_at=datetime.fromisoformat(data.pop("uploaded_at")), **data)
