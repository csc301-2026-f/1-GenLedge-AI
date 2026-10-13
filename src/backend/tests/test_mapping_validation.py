import pytest
from pydantic import ValidationError

from app.agent.contracts import (
    Attribute, CoverageRecord, Disposition, EvidenceRef, FindingCode,
    InventoryField, InventoryView, Mapping, MappingDraft, ModelDraft,
    ResourceSummary, Severity, SourceCoverage, SourceType, Table,
    TransformName, TransformOp, ValidationFinding,
)
from app.mappings.validation import project_inventory, project_model_draft, redact_samples, redact_value, run_checks


def field(resource, path, *, ambiguity=None, source="source-1"):
    return InventoryField(
        ref={"source_id": source, "resource_id": resource, "field_path": path},
        type=SourceType.TEXT, nullable=False, repeating="[]" in path,
        samples=[], ambiguity=ambiguity, status="stable",
    )


def attribute(name, resource, path, *, confidence=0.9, evidence=None):
    return Attribute(
        id=name, type=SourceType.TEXT, nullable=False,
        evidence=evidence if evidence is not None else [EvidenceRef(resource_id=resource, field_path=path)],
        confidence=confidence,
    )


def table(name, attrs, key=None):
    return Table(
        id=name, name=name, kind="event", grain="one source record",
        key=key if key is not None else [attrs[0].id],
        attributes=attrs, relationships=[], rationale="Observed source grain.",
    )


def base():
    inventory = InventoryView(
        snapshot_id="snapshot-1",
        resources=[ResourceSummary(resource_id="orders", name="orders", kind="collection", field_count=3)],
        fields=[field("orders", "order_id"), field("orders", "lines[].sku"), field("orders", "order_date", ambiguity="month/day or day/month")],
    )
    model = ModelDraft(
        revision=2,
        tables=[table("fact_orders", [attribute("order_id", "orders", "order_id")])],
        source_coverage=[
            SourceCoverage(resource_id="orders", field_path="order_id", disposition=Disposition.REPRESENTED, reason="Mapped"),
            SourceCoverage(resource_id="orders", field_path="lines[].sku", disposition=Disposition.RAW_ONLY, reason="Line grain"),
            SourceCoverage(resource_id="orders", field_path="order_date", disposition=Disposition.UNRESOLVED, reason="Ambiguous format"),
        ],
    )
    return inventory, model


def codes(findings):
    return {finding.code for finding in findings}


def test_projection_assigns_revisions_catalogue_and_one_coverage_record_per_field():
    inventory, model = base()
    mapping, is_new, coverage, findings = project_model_draft(model, inventory)
    assert mapping.revision == mapping.based_on_model_revision == 2
    assert mapping.mappings[0].target == "fact_orders.order_id"
    assert mapping.mappings[0].sources == ["orders.order_id"]
    assert mapping.mappings[0].operations == []
    assert is_new == {"fact_orders": True}
    assert len(coverage) == len(inventory.fields)
    assert {(item.resource_id, item.field_path) for item in coverage} == {(item.ref.resource_id, item.ref.field_path) for item in inventory.fields}
    assert is_new == project_model_draft(model, inventory, catalog_table_ids=set())[1]
    assert project_model_draft(model, inventory, catalog_table_ids={"fact_orders"})[1] == {"fact_orders": False}
    assert FindingCode.UNMAPPED_SOURCE_FIELD in codes(findings)


def test_multiple_targets_can_use_one_source_collection():
    inventory, model = base()
    line_table = table("fact_lines", [attribute("sku", "orders", "lines[].sku")])
    model = model.model_copy(update={"tables": [*model.tables, line_table]})
    mappings, _, _, findings = project_model_draft(model, inventory)
    assert {mapping.target for mapping in mappings.mappings} == {"fact_orders.order_id", "fact_lines.sku"}
    assert FindingCode.PARTIAL_TABLE_FAILURE not in codes(findings)


def test_multiple_field_evidence_is_unresolved_not_an_invented_join():
    inventory, model = base()
    combined = attribute("combined", "orders", "order_id", evidence=[
        EvidenceRef(resource_id="orders", field_path="order_id"),
        EvidenceRef(resource_id="orders", field_path="lines[].sku"),
    ])
    model = model.model_copy(update={"tables": [table("fact_orders", [model.tables[0].attributes[0], combined])]})
    mapping, _, _, findings = project_model_draft(model, inventory)
    assert len(mapping.mappings) == 1
    assert mapping.unmapped_targets == ["fact_orders.combined"]
    assert FindingCode.UNMAPPED_TARGET_FIELD in codes(findings)


def test_invalid_source_and_target_references_return_blockers():
    inventory, model = base()
    mapping = MappingDraft(revision=2, based_on_model_revision=2, mappings=[
        Mapping(target="fact_orders.order_id", sources=["orders.unknown"], confidence=0.9),
        Mapping(target="fact_orders.phantom", sources=["orders.order_id"], confidence=0.9),
    ])
    findings = run_checks(model, mapping, inventory, [])
    assert {FindingCode.INVALID_SOURCE_REFERENCE, FindingCode.INVALID_TARGET_REFERENCE} <= codes(findings)
    assert all(item.severity == Severity.BLOCKER for item in findings if item.code in {FindingCode.INVALID_SOURCE_REFERENCE, FindingCode.INVALID_TARGET_REFERENCE})


def test_merge_keys_must_be_unique_real_and_mapped():
    inventory, model = base()
    bad = table("fact_orders", [model.tables[0].attributes[0]], key=["order_id", "order_id", "phantom"])
    model = model.model_copy(update={"tables": [bad]})
    empty_mapping = MappingDraft(revision=2, based_on_model_revision=2, mappings=[])
    assert FindingCode.INVALID_MERGE_KEY in codes(run_checks(model, empty_mapping, inventory, []))


def test_missing_or_wrong_evidence_produces_finding():
    inventory, model = base()
    no_field = attribute("order_id", "orders", "order_id", evidence=[EvidenceRef(resource_id="orders")])
    model = model.model_copy(update={"tables": [table("fact_orders", [no_field])]})
    mapping = MappingDraft(revision=2, based_on_model_revision=2, mappings=[Mapping(target="fact_orders.order_id", sources=["orders.order_id"], confidence=0.9)])
    assert FindingCode.MISSING_EVIDENCE in codes(run_checks(model, mapping, inventory, []))


def test_ambiguous_date_and_stale_revision_block():
    inventory, model = base()
    date_attr = attribute("order_date", "orders", "order_date")
    model = model.model_copy(update={"tables": [table("fact_orders", [model.tables[0].attributes[0], date_attr])]})
    mapping = MappingDraft(revision=1, based_on_model_revision=1, mappings=[
        Mapping(target="fact_orders.order_id", sources=["orders.order_id"], confidence=0.9),
        Mapping(target="fact_orders.order_date", sources=["orders.order_date"], operations=[TransformOp(name=TransformName.DATE_FORMAT, args={"format": "%m/%d/%Y"})], confidence=0.9),
    ])
    assert {FindingCode.AMBIGUOUS_DATE, FindingCode.STALE_MAPPING_REVISION} <= codes(run_checks(model, mapping, inventory, []))


def test_unsupported_operation_is_a_finding_even_for_bypassed_boundary():
    inventory, model = base()
    bypassed = TransformOp.model_construct(name="parse_timestamp", args={})
    mapping = MappingDraft(revision=2, based_on_model_revision=2, mappings=[
        Mapping.model_construct(target="fact_orders.order_id", sources=["orders.order_id"], operations=[bypassed], join_path=[], confidence=0.9, rationale=None)
    ])
    assert FindingCode.UNSUPPORTED_OPERATION in codes(run_checks(model, mapping, inventory, []))


def test_unmapped_source_and_target_findings_are_stable():
    inventory, model = base()
    attr = attribute("unrouted", "orders", "unknown")
    model = model.model_copy(update={"tables": [table("fact_orders", [model.tables[0].attributes[0], attr])]})
    mapping, _, coverage, findings = project_model_draft(model, inventory)
    assert FindingCode.UNMAPPED_SOURCE_FIELD in codes(findings)
    assert FindingCode.UNMAPPED_TARGET_FIELD in codes(findings)
    assert len(coverage) == len(inventory.fields)
    assert mapping.unmapped_targets == ["fact_orders.unrouted"]


def test_partial_table_failure_preserves_valid_table_mapping():
    inventory, model = base()
    bad = table("fact_bad", [attribute("missing", "orders", "unknown")])
    model = model.model_copy(update={"tables": [*model.tables, bad]})
    mapping, _, _, findings = project_model_draft(model, inventory)
    assert [item.target for item in mapping.mappings] == ["fact_orders.order_id"]
    assert FindingCode.PARTIAL_TABLE_FAILURE in codes(findings)
    assert any(item.target == "fact_bad.missing" and item.severity == Severity.BLOCKER for item in findings)


def test_strict_boundaries_reject_malformed_contract_data():
    inventory, model = base()
    with pytest.raises(ValidationError):
        ModelDraft.model_validate({**model.model_dump(), "invented": True})
    with pytest.raises(ValidationError):
        ModelDraft.model_validate({**model.model_dump(), "revision": "2"})
    with pytest.raises(ValidationError):
        Attribute(id="not valid", type=SourceType.TEXT, nullable=False, evidence=[EvidenceRef(resource_id="orders", field_path="order_id")], confidence=0.9)
    with pytest.raises(ValidationError):
        Attribute(id="x", type=SourceType.TEXT, nullable=False, evidence=[], confidence=0.9)
    with pytest.raises(ValidationError):
        Attribute(id="x", type=SourceType.TEXT, nullable=False, evidence=[EvidenceRef(resource_id="orders", field_path="order_id")], confidence=1.1)
    with pytest.raises(ValidationError):
        Table(id="x", name="x", kind="event", grain="one", key=["x"], attributes=[], relationships=[], rationale="")
    with pytest.raises(ValidationError):
        TransformOp(name="invented")
    with pytest.raises(ValidationError):
        ValidationFinding(code="invented", severity=Severity.WARNING, message="invalid")


def test_every_finding_code_has_a_triggering_test_case():
    # Each code is exercised by the tests above; this guards additions to the shared enum.
    assert set(FindingCode) == {
        FindingCode.INVALID_SOURCE_REFERENCE, FindingCode.INVALID_TARGET_REFERENCE,
        FindingCode.INVALID_MERGE_KEY, FindingCode.MISSING_EVIDENCE,
        FindingCode.UNMAPPED_SOURCE_FIELD, FindingCode.UNMAPPED_TARGET_FIELD,
        FindingCode.AMBIGUOUS_DATE, FindingCode.UNSUPPORTED_OPERATION,
        FindingCode.STALE_MAPPING_REVISION, FindingCode.PARTIAL_TABLE_FAILURE,
    }


@pytest.mark.parametrize(("name", "value", "expected"), [
    ("email", "ada@example.com", "<redacted:email>"),
    ("mobile", "+1 (416) 555-0123", "<redacted:phone>"),
    ("billing_address", "12 Main Street", "<redacted:address>"),
    ("customer_id", "ABC-12345", "<redacted:identifier>"),
    ("api_key", "sk-test-secret", "<redacted:credential>"),
    ("notes", "password=hidden", "<redacted:credential>"),
    ("private_value", "unclassified", "<redacted:sensitive>"),
])
def test_redaction_categories_are_deterministic(name, value, expected):
    assert redact_value(value, name, sensitive=name == "private_value") == expected
    assert redact_value(value, name, sensitive=name == "private_value") == expected


def test_inventory_projection_is_an_allow_list_and_caps_samples():
    inventory, _ = base()
    dangerous = InventoryField(
        ref={"source_id": "org-secret-123", "resource_id": "orders", "field_path": "contact_email"},
        type=SourceType.TEXT, nullable=True, repeating=False,
        samples=["ada@example.com", "other@example.com", "third@example.com"],
        description="password=hidden", status="stable",
    )
    inventory = inventory.model_copy(update={"fields": [*inventory.fields, dangerous]})
    result = project_inventory(inventory)
    rendered = str(result)
    assert "org-secret-123" not in rendered
    assert "ada@example.com" not in rendered
    assert "password=hidden" not in rendered
    assert "<redacted:email>" in rendered
    assert result["fields"][-1]["samples"] == ["<redacted:email>"] * 3
    assert len(redact_samples(["a", "b", "c", "d"])) == 3
    assert "rows" not in result


def test_unknown_sensitive_field_uses_generic_marker():
    inventory, _ = base()
    private = field("orders", "private_note")
    private = private.model_copy(update={"samples": ["unclassified partner value"]})
    inventory = inventory.model_copy(update={"fields": [*inventory.fields, private]})
    projected = project_inventory(inventory, {"orders.private_note"})
    assert projected["fields"][-1]["samples"] == ["<redacted:sensitive>"]
