"""Project structural discovery into the shared source inventory contract."""

import json
from typing import Literal

from app.agent.contracts import (
    FieldRef, InventoryField, InventoryView, ResourceSummary, SourceType,
)
from .discovery import DiscoveryResult, ObservedType

_SOURCE_TYPES: dict[ObservedType, SourceType] = {
    "string": SourceType.TEXT,
    "number": SourceType.NUMBER,
    "boolean": SourceType.BOOLEAN,
    "object": SourceType.JSON,
    "array": SourceType.JSON,
}


def _inventory_type(types: tuple[ObservedType, ...]) -> SourceType:
    non_null = tuple(kind for kind in types if kind != "null")
    return _SOURCE_TYPES[non_null[0]] if len(non_null) == 1 else SourceType.JSON


def to_inventory(result: DiscoveryResult, *, snapshot_id: str, source_id: str,
                 resource_id: str, resource_name: str,
                 resource_kind: Literal["collection", "table", "sheet", "file"]) -> InventoryView:
    """Adapt one resource, preserving paths and observed evidence without coercion.

    Identity and exposure/redaction policy belong to the caller. Keep the original
    result for sample counts/method, which InventoryView does not represent.
    """
    fields = [InventoryField(
        ref=FieldRef(source_id=source_id, resource_id=resource_id, field_path=field.path),
        type=_inventory_type(field.types),
        nullable=field.nullable,
        repeating=field.repeating,
        samples=[json.dumps(value, ensure_ascii=False) for value in field.samples],
        native_type="observed:" + "|".join(field.types),
        status="unknown",
    ) for field in result.fields]
    return InventoryView(
        snapshot_id=snapshot_id,
        resources=[ResourceSummary(resource_id=resource_id, name=resource_name,
                                   kind=resource_kind, field_count=len(fields))],
        fields=fields,
    )
