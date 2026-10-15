"""Bounded structural discovery over parsed JSON-compatible records."""

from collections import Counter
from dataclasses import dataclass, field
from itertools import islice
import json
from typing import Iterable, Literal, TypeAlias

from .date_ambiguity import detect_date_ambiguity


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | dict[str, "JSONValue"] | list["JSONValue"]
ObservedType: TypeAlias = Literal["null", "boolean", "number", "string", "object", "array"]
_TYPE_NAMES: dict[type, ObservedType] = {
    type(None): "null", bool: "boolean", int: "number", float: "number",
    str: "string", dict: "object", list: "array",
}


@dataclass(frozen=True)
class DiscoveredField:
    path: str
    types: tuple[ObservedType, ...]
    nullable: bool
    repeating: bool
    samples: tuple[JSONScalar, ...]
    ambiguity: str | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    sampled_count: int
    fields: tuple[DiscoveredField, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "contractVersion": 1,
            "samplingMethod": "head",
            "sampledCount": self.sampled_count,
            "fields": [{
                "path": item.path, "types": list(item.types),
                "nullable": item.nullable, "repeating": item.repeating,
                "samples": list(item.samples),
                **({"ambiguity": item.ambiguity} if item.ambiguity is not None else {}),
            } for item in self.fields],
        }


@dataclass
class _ObservedField:
    parent: str | None
    repeating: bool
    types: set[ObservedType] = field(default_factory=set)
    samples: list[JSONScalar] = field(default_factory=list)
    sample_keys: set[tuple[ObservedType, str]] = field(default_factory=set)
    documents: set[int] = field(default_factory=set)
    occurrences: int = 0
    ambiguity: str | None = None


def _key_path(parent: str, key: str) -> str:
    if key.isidentifier():
        return f"{parent}.{key}" if parent else key
    return parent + "[" + json.dumps(key, ensure_ascii=False) + "]"


def discover_records(records: Iterable[dict[str, JSONValue]], *,
                     sample_limit: int = 500) -> DiscoveryResult:
    """Observe the first sample_limit records without changing or coercing them."""
    if not 1 <= sample_limit <= 500:
        raise ValueError("sample_limit must be between 1 and 500.")
    observed: dict[str, _ObservedField] = {}
    object_counts: Counter[str] = Counter()

    def visit_object(value: dict[str, JSONValue], path: str,
                     repeating: bool, document: int) -> None:
        object_counts[path] += 1
        for key, child in value.items():
            visit(child, _key_path(path, key), path, repeating, document)

    def visit(value: JSONValue, path: str, parent: str | None,
              repeating: bool, document: int) -> None:
        kind = _TYPE_NAMES[type(value)]
        item = observed.setdefault(path, _ObservedField(parent, repeating))
        item.types.add(kind)
        item.documents.add(document)
        item.occurrences += 1
        item.repeating |= repeating or kind == "array"
        if isinstance(value, str) and item.ambiguity is None:
            item.ambiguity = detect_date_ambiguity(value)
        if len(item.samples) < 3:
            sample: JSONScalar
            if isinstance(value, dict):
                sample = f"{{{len(value)} fields}}"
            elif isinstance(value, list):
                sample = f"[{len(value)} items]"
            elif isinstance(value, str):
                sample = value[:80]
            else:
                sample = value
            sample_key = (kind, json.dumps(sample, ensure_ascii=False, allow_nan=False))
            if sample_key not in item.sample_keys:
                item.sample_keys.add(sample_key)
                item.samples.append(sample)
        if isinstance(value, dict):
            visit_object(value, path, repeating, document)
        elif isinstance(value, list):
            for child in value:
                visit(child, path + "[]", None, True, document)

    sampled_count = 0
    for document, record in enumerate(islice(records, sample_limit)):
        visit_object(record, "", False, document)
        sampled_count += 1
    return DiscoveryResult(sampled_count, tuple(
        DiscoveredField(
            path=path,
            types=tuple(sorted(item.types)),
            nullable=("null" in item.types or len(item.documents) < sampled_count
                      or (item.parent is not None
                          and item.occurrences < object_counts[item.parent])),
            repeating=item.repeating,
            samples=tuple(item.samples),
            ambiguity=item.ambiguity,
        ) for path, item in sorted(observed.items())
    ))


@dataclass(frozen=True)
class FieldTypeChange:
    path: str
    previous_types: tuple[ObservedType, ...]
    current_types: tuple[ObservedType, ...]


@dataclass(frozen=True)
class DiscoveryChanges:
    added_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    type_changes: tuple[FieldTypeChange, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "contractVersion": 1,
            "added": list(self.added_paths),
            "missing": list(self.missing_paths),
            "typeChanges": [{
                "path": change.path,
                "previousTypes": list(change.previous_types),
                "currentTypes": list(change.current_types),
            } for change in self.type_changes],
        }


def compare_discoveries(previous: DiscoveryResult,
                        current: DiscoveryResult) -> DiscoveryChanges:
    """Compare canonical paths/types; missing paths are sample observations."""
    before = {item.path: item for item in previous.fields}
    after = {item.path: item for item in current.fields}
    return DiscoveryChanges(
        added_paths=tuple(sorted(after.keys() - before.keys())),
        missing_paths=tuple(sorted(before.keys() - after.keys())),
        type_changes=tuple(
            FieldTypeChange(path, before[path].types, after[path].types)
            for path in sorted(before.keys() & after.keys())
            if before[path].types != after[path].types
        ),
    )
