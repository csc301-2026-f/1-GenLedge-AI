"""Deterministic US4 mapping projection, validation, coverage, and redaction."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.agent.contracts import (
    Attribute,
    CoverageRecord,
    Disposition,
    EvidenceRef,
    FindingCode,
    InventoryField,
    InventoryView,
    Mapping,
    MappingDraft,
    ModelDraft,
    Severity,
    SourceCoverage,
    Table,
    TransformName,
    ValidationFinding,
)


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]-]*$")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"(?:^|\D)(?:\+?\d[\d().\s-]{6,}\d)(?:$|\D)")
_CREDENTIAL = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|credential|dsn|connection[_-]?string)", re.I)
_ADDRESS = re.compile(r"(?:address|street|postal|zip|city|province|state|country)", re.I)
_IDENTIFIER_FIELD = re.compile(r"(?:^|[_.\[\]])(?:id|identifier|account|customer|user|ssn|tax[_-]?id)(?:$|[_.\[\]])", re.I)

REDACTION_MARKERS = {
    "email": "<redacted:email>",
    "phone": "<redacted:phone>",
    "address": "<redacted:address>",
    "identifier": "<redacted:identifier>",
    "credential": "<redacted:credential>",
    "sensitive": "<redacted:sensitive>",
}


def _field_key(resource_id: str, field_path: str) -> str:
    return f"{resource_id}.{field_path}"


def _inventory_indexes(inventory: InventoryView) -> tuple[dict[str, InventoryField], dict[str, set[str]]]:
    fields: dict[str, InventoryField] = {}
    aliases: dict[str, set[str]] = {}
    for item in inventory.fields:
        canonical = _field_key(item.ref.resource_id, item.ref.field_path)
        fields[canonical] = item
        aliases.setdefault(canonical, set()).add(canonical)
        aliases.setdefault(_field_key(item.ref.source_id, item.ref.resource_id + "." + item.ref.field_path), set()).add(canonical)
        aliases.setdefault(item.ref.field_path, set()).add(canonical)
    return fields, aliases


def _resolve_source(value: str, inventory: InventoryView) -> InventoryField | None:
    fields, aliases = _inventory_indexes(inventory)
    candidates = aliases.get(value, set())
    if len(candidates) == 1:
        return fields[next(iter(candidates))]
    # A source-qualified form is commonly rendered as source.resource.field.
    for item in inventory.fields:
        if value in {
            f"{item.ref.source_id}.{item.ref.resource_id}.{item.ref.field_path}",
            f"{item.ref.resource_id}.{item.ref.field_path}",
        }:
            return item
    return None


def _canonical_source(item: InventoryField) -> str:
    return _field_key(item.ref.resource_id, item.ref.field_path)


def _safe_target(value: str | None) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _finding(code: FindingCode, message: str, *, target: str | None = None,
             severity: Severity = Severity.BLOCKER, evidence: Iterable[EvidenceRef] = ()) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        target=_safe_target(target),
        message=message,
        evidence=list(evidence),
    )


def _table_target(table: Table, attribute: Attribute | None = None) -> str:
    return f"{table.id}.{attribute.id}" if attribute is not None else table.id


def _coverage_records(model: ModelDraft, inventory: InventoryView) -> list[CoverageRecord]:
    declared: dict[tuple[str, str], SourceCoverage] = {
        (item.resource_id, item.field_path): item for item in model.source_coverage
    }
    used = {
        _canonical_source(source)
        for table in model.tables
        for attr in table.attributes
        for evidence in attr.evidence
        if evidence.field_path and (source := _resolve_source(_field_key(evidence.resource_id, evidence.field_path), inventory))
    }
    result: list[CoverageRecord] = []
    for item in inventory.fields:
        key = (item.ref.resource_id, item.ref.field_path)
        source_coverage = declared.get(key)
        if source_coverage is not None:
            disposition, reason = source_coverage.disposition, redact_value(source_coverage.reason)
        elif _canonical_source(item) in used:
            disposition, reason = Disposition.REPRESENTED, "Referenced by a proposed attribute"
        else:
            disposition, reason = Disposition.UNRESOLVED, "No proposed target mapping"
        result.append(CoverageRecord(
            resource_id=item.ref.resource_id,
            field_path=item.ref.field_path,
            disposition=disposition,
            reason=reason,
        ))
    return result


def _mapping_for_attribute(table: Table, attribute: Attribute, inventory: InventoryView) -> tuple[Mapping | None, str | None]:
    if len(attribute.evidence) != 1:
        return None, "An attribute must cite exactly one source field for deterministic projection"
    evidence = attribute.evidence[0]
    if not evidence.field_path:
        return None, "Evidence does not identify a source field"
    source = _resolve_source(_field_key(evidence.resource_id, evidence.field_path), inventory)
    if source is None:
        return None, "Evidence names a source field that is not in the inventory"
    return Mapping(
        target=f"{table.id}.{attribute.id}",
        sources=[_canonical_source(source)],
        operations=[],
        join_path=[],
        confidence=attribute.confidence,
        rationale=redact_value(table.rationale),
    ), None


def project_model_draft(
    model_draft: ModelDraft,
    inventory: InventoryView,
    catalog_table_ids: set[str] | None = None,
) -> tuple[MappingDraft, dict[str, bool], list[CoverageRecord], list[ValidationFinding]]:
    """Project a model draft without exposing raw source payloads.

    The return shape is deliberately simple for the worker boundary: mapping draft,
    table reuse flags, complete source coverage, and deterministic findings.
    """
    mappings: list[Mapping] = []
    unmapped_targets: list[str] = []
    findings: list[ValidationFinding] = []
    for table in model_draft.tables:
        for attribute in table.attributes:
            mapping, _ = _mapping_for_attribute(table, attribute, inventory)
            target = _table_target(table, attribute)
            if mapping is None:
                unmapped_targets.append(target)
            else:
                mappings.append(mapping)
    mapping_draft = MappingDraft(
        revision=model_draft.revision,
        based_on_model_revision=model_draft.revision,
        mappings=mappings,
        unmapped_targets=unmapped_targets,
        unresolved=[redact_value(item) for item in model_draft.unresolved],
    )
    coverage = _coverage_records(model_draft, inventory)
    findings.extend(run_checks(model_draft, mapping_draft, inventory, coverage))
    blockers_by_table: dict[str, bool] = {}
    for item in findings:
        if item.severity != Severity.BLOCKER or not item.target:
            continue
        table_id = item.target.split(".", 1)[0]
        blockers_by_table[table_id] = True
    valid_mappings = [item for item in mapping_draft.mappings if not blockers_by_table.get(item.target.split(".", 1)[0], False)]
    if valid_mappings and blockers_by_table:
        mapping_draft = mapping_draft.model_copy(update={"mappings": valid_mappings})
    is_new = {
        table.id: (catalog_table_ids is None or table.id not in catalog_table_ids)
        for table in model_draft.tables
    }
    return mapping_draft, is_new, coverage, findings


def _validate_evidence(evidence: EvidenceRef, inventory: InventoryView) -> bool:
    if not evidence.field_path:
        return bool(evidence.profile_ref and any(resource.resource_id == evidence.resource_id for resource in inventory.resources))
    return _resolve_source(_field_key(evidence.resource_id, evidence.field_path), inventory) is not None


def run_checks(
    model_draft: ModelDraft,
    mapping_draft: MappingDraft,
    inventory: InventoryView,
    coverage: Iterable[CoverageRecord] | None = None,
) -> list[ValidationFinding]:
    """Run all business checks and return findings instead of raising."""
    findings: list[ValidationFinding] = []
    attributes = {
        f"{table.id}.{attribute.id}": (table, attribute)
        for table in model_draft.tables for attribute in table.attributes
    }
    mapped_targets = {item.target for item in mapping_draft.mappings}
    if len({table.id for table in model_draft.tables}) != len(model_draft.tables):
        findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Target table IDs must be unique"))
    used_sources: set[str] = set()
    for mapping in mapping_draft.mappings:
        target = getattr(mapping, "target", None)
        target_pair = attributes.get(target)
        if target_pair is None:
            findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Mapping target is not a model attribute", target=target))
        for source_ref in getattr(mapping, "sources", []):
            source = _resolve_source(source_ref, inventory)
            if source is None:
                findings.append(_finding(FindingCode.INVALID_SOURCE_REFERENCE, "Mapping source is not in the source inventory", target=target))
            else:
                used_sources.add(_canonical_source(source))
        try:
            confidence = mapping.confidence
            if not isinstance(confidence, (float, int)) or not 0 <= confidence <= 1:
                findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Mapping confidence must be between 0 and 1", target=target))
        except Exception:
            findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Mapping confidence is invalid", target=target))
        for operation in getattr(mapping, "operations", []):
            name = getattr(operation, "name", None)
            try:
                name = name if isinstance(name, TransformName) else TransformName(name)
            except Exception:
                findings.append(_finding(FindingCode.UNSUPPORTED_OPERATION, "Transformation is outside the closed vocabulary", target=target))
                continue
            if name == TransformName.DATE_FORMAT:
                for source_ref in getattr(mapping, "sources", []):
                    source = _resolve_source(source_ref, inventory)
                    if source is not None and source.ambiguity:
                        findings.append(_finding(
                            FindingCode.AMBIGUOUS_DATE,
                            "date_format cannot run while the source date is ambiguous",
                            target=target,
                        ))
    for table in model_draft.tables:
        attribute_ids = [attribute.id for attribute in table.attributes]
        if len(attribute_ids) != len(set(attribute_ids)):
            findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Target attribute IDs must be unique within a table", target=table.id))
        if (len(set(table.key)) != len(table.key) or not table.key
                or any(key not in attribute_ids or f"{table.id}.{key}" not in mapped_targets for key in table.key)):
            findings.append(_finding(FindingCode.INVALID_MERGE_KEY, "Merge key must contain unique attributes on the target table", target=table.id))
        for attribute in table.attributes:
            if not attribute.evidence or not any(evidence.field_path or evidence.profile_ref for evidence in attribute.evidence):
                findings.append(_finding(FindingCode.MISSING_EVIDENCE, "Attribute evidence is required", target=_table_target(table, attribute)))
            for evidence in attribute.evidence:
                if not _validate_evidence(evidence, inventory):
                    findings.append(_finding(FindingCode.INVALID_SOURCE_REFERENCE, "Attribute evidence is not in the source inventory", target=_table_target(table, attribute), evidence=attribute.evidence))
        for relationship in table.relationships:
            if not relationship.evidence:
                findings.append(_finding(FindingCode.MISSING_EVIDENCE, "Relationship evidence is required", target=table.id))
            for ref in (relationship.from_ref, relationship.to_ref):
                if ref not in attributes:
                    findings.append(_finding(FindingCode.INVALID_TARGET_REFERENCE, "Relationship reference is not a model attribute", target=ref))
            for evidence in relationship.evidence:
                if not _validate_evidence(evidence, inventory):
                    findings.append(_finding(FindingCode.INVALID_SOURCE_REFERENCE, "Relationship evidence is not in the source inventory", target=table.id, evidence=relationship.evidence))
    if mapping_draft.based_on_model_revision != model_draft.revision:
        findings.append(_finding(
            FindingCode.STALE_MAPPING_REVISION,
            "Mappings were built against a superseded model revision",
            severity=Severity.BLOCKER,
        ))
    covered = set(used_sources)
    for item in inventory.fields:
        key = _canonical_source(item)
        if key not in covered:
            findings.append(_finding(
                FindingCode.UNMAPPED_SOURCE_FIELD,
                "Source field has no target mapping",
                target=key,
                severity=Severity.WARNING,
            ))
    # Coverage supplied by the caller must still be complete and one-to-one.
    if coverage is not None:
        seen: set[tuple[str, str]] = set()
        for item in coverage:
            key = (item.resource_id, item.field_path)
            if key in seen:
                findings.append(_finding(FindingCode.UNMAPPED_SOURCE_FIELD, "Source coverage contains a duplicate field", target=_field_key(*key)))
            seen.add(key)
        expected = {(item.ref.resource_id, item.ref.field_path) for item in inventory.fields}
        for missing in sorted(expected - seen):
            findings.append(_finding(FindingCode.UNMAPPED_SOURCE_FIELD, "Source coverage is missing an inventory field", target=_field_key(*missing)))
        for extra in sorted(seen - expected):
            findings.append(_finding(FindingCode.INVALID_SOURCE_REFERENCE, "Source coverage names a field outside the inventory", target=_field_key(*extra)))
    for target in attributes:
        if target not in mapped_targets:
            findings.append(_finding(FindingCode.UNMAPPED_TARGET_FIELD, "Target attribute has no deterministic source mapping", target=target, severity=Severity.WARNING))
    blocked_tables = {
        item.target.split(".", 1)[0]
        for item in findings
        if item.severity == Severity.BLOCKER and item.target and item.target.split(".", 1)[0] in {table.id for table in model_draft.tables}
    }
    if blocked_tables and any(item.target.split(".", 1)[0] not in blocked_tables for item in mapping_draft.mappings):
        findings.append(_finding(
            FindingCode.PARTIAL_TABLE_FAILURE,
            "Some target tables were blocked; valid table mappings were preserved",
            severity=Severity.WARNING,
        ))
    return findings


def _sensitivity_kind(field_name: str, value: Any, *, sensitive: bool = False) -> str | None:
    if _CREDENTIAL.search(field_name) or isinstance(value, str) and _CREDENTIAL.search(value):
        return "credential"
    if isinstance(value, str) and _EMAIL.search(value):
        return "email"
    if _ADDRESS.search(field_name):
        return "address"
    if _IDENTIFIER_FIELD.search(field_name):
        return "identifier"
    if _PHONE.search(str(value)) and any(char.isdigit() for char in str(value)):
        return "phone"
    return "sensitive" if sensitive else None


def redact_value(value: Any, field_path: str = "", *, sensitive: bool = False) -> Any:
    """Return a stable marker for sensitive scalar values; preserve safe structure."""
    kind = _sensitivity_kind(field_path, value, sensitive=sensitive)
    if kind:
        return REDACTION_MARKERS[kind]
    if isinstance(value, list):
        return [redact_value(item, field_path, sensitive=sensitive) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_value(item, str(key), sensitive=sensitive) for key, item in value.items()}
    return value


def redact_samples(samples: Iterable[Any], field_path: str = "", *, sensitive: bool = False) -> list[Any]:
    return [redact_value(value, field_path, sensitive=sensitive) for value in list(samples)[:3]]


def project_inventory(inventory: InventoryView, sensitive_fields: set[str] | None = None) -> dict[str, Any]:
    """Build the model-facing allow-list projection from an inventory."""
    return {
        "snapshot_id": inventory.snapshot_id,
        "resources": [
            {"resource_id": item.resource_id, "kind": item.kind, "field_count": item.field_count}
            for item in inventory.resources
        ],
        "fields": [
            {
                "resource_id": item.ref.resource_id,
                "field_path": item.ref.field_path,
                "type": item.type.value,
                "nullable": item.nullable,
                "repeating": item.repeating,
                "samples": redact_samples(item.samples, item.ref.field_path, sensitive=bool(sensitive_fields and _canonical_source(item) in sensitive_fields)),
                "description": redact_value(item.description, "description", sensitive=bool(sensitive_fields and _canonical_source(item) in sensitive_fields)),
                "ambiguity": redact_value(item.ambiguity, "ambiguity", sensitive=bool(sensitive_fields and _canonical_source(item) in sensitive_fields)),
                "status": item.status,
            }
            for item in inventory.fields
        ],
    }


# Explicit aliases make the service boundary easy for the worker to discover.
project_model_to_mapping = project_model_draft
validate_mappings = run_checks
redact_sample = redact_value
