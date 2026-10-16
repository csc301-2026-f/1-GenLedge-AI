import pytest
from pydantic import ValidationError

from app.agent.contracts import (
    AgentBudgets,
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
    PersistedArtifact,
    Relationship,
    ResourceSummary,
    Severity,
    SourceCoverage,
    SourceType,
    Table,
    ToolCallRequest,
    TransformName,
    TransformOp,
    ValidationFinding,
)


def evidence():
    return [EvidenceRef(resource_id="orders", field_path="order_id", profile_ref="profile-1")]


def attribute():
    return Attribute(id="order_id", type=SourceType.TEXT, nullable=False, evidence=evidence(), confidence=0.95)


def table():
    return Table(id="fact_orders", name="fact_orders", kind="event", grain="one row per order", key=["order_id"], attributes=[attribute()], relationships=[], rationale="Preserves order grain.")


def inventory():
    return InventoryView(
        snapshot_id="snapshot-1",
        resources=[ResourceSummary(resource_id="orders", name="orders", kind="collection", field_count=1)],
        fields=[InventoryField(ref={"source_id": "source-1", "resource_id": "orders", "field_path": "order_id"}, type="text", nullable=False, repeating=False, samples=["1"], description=None, ambiguity=None, status="stable")],
    )


def test_valid_contracts_round_trip_through_json():
    assert InventoryView.model_validate_json(inventory().model_dump_json()).snapshot_id == "snapshot-1"
    draft = ModelDraft(revision=0, tables=[table()], source_coverage=[SourceCoverage(field_path="order_id", resource_id="orders", disposition=Disposition.REPRESENTED, reason="Mapped")])
    assert ModelDraft.model_validate_json(draft.model_dump_json()).tables[0].key == ["order_id"]
    mapping = Mapping(target="fact_orders.order_id", sources=["orders.order_id"], operations=[TransformOp(name=TransformName.TRIM)], join_path=[], confidence=0.9)
    mappings = MappingDraft(revision=1, based_on_model_revision=0, mappings=[mapping], unmapped_targets=[], unresolved=[])
    assert MappingDraft.model_validate_json(mappings.model_dump_json()).mappings[0].operations[0].name == TransformName.TRIM


def test_valid_finding_coverage_and_budget_contracts():
    finding = ValidationFinding(code=FindingCode.INVALID_SOURCE_REFERENCE, severity=Severity.BLOCKER, target="fact_orders.order_id", message="Missing source", evidence=evidence())
    coverage = CoverageRecord(resource_id="orders", field_path="order_id", disposition=Disposition.REPRESENTED, reason="Mapped")
    assert finding.code == FindingCode.INVALID_SOURCE_REFERENCE
    assert coverage.disposition == Disposition.REPRESENTED
    assert AgentBudgets().max_tool_calls == 40


@pytest.mark.parametrize("payload", [
    {"id": "order_id", "type": "text", "nullable": False, "evidence": evidence(), "confidence": 0.95, "unexpected": True},
    {"id": "order_id", "type": "text", "nullable": False, "evidence": evidence(), "confidence": "0.95"},
])
def test_strict_models_reject_unknown_fields_and_coercion(payload):
    with pytest.raises(ValidationError):
        Attribute.model_validate(payload)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_is_bounded(confidence):
    with pytest.raises(ValidationError):
        Attribute(id="order_id", type=SourceType.TEXT, nullable=False, evidence=evidence(), confidence=confidence)


def test_required_evidence_grain_key_and_rationale_are_enforced():
    with pytest.raises(ValidationError):
        Attribute(id="order_id", type=SourceType.TEXT, nullable=False, evidence=[], confidence=0.9)
    with pytest.raises(ValidationError):
        Table(id="fact_orders", name="fact_orders", kind="event", grain="", key=["order_id"], attributes=[attribute()], relationships=[], rationale="ok")
    with pytest.raises(ValidationError):
        Table(id="fact_orders", name="fact_orders", kind="event", grain="one row", key=[], attributes=[attribute()], relationships=[], rationale="ok")
    with pytest.raises(ValidationError):
        Table(id="fact_orders", name="fact_orders", kind="event", grain="one row", key=["order_id"], attributes=[attribute()], relationships=[], rationale="")


def test_invalid_identifier_source_type_transform_and_finding_code_are_rejected():
    with pytest.raises(ValidationError):
        Attribute(id="not valid", type=SourceType.TEXT, nullable=False, evidence=evidence(), confidence=0.9)
    with pytest.raises(ValidationError):
        InventoryField(ref={"source_id": "s", "resource_id": "r", "field_path": "f"}, type="object-id", nullable=False, repeating=False, samples=[], description=None, ambiguity=None, status="stable")
    with pytest.raises(ValidationError):
        TransformOp(name="parse_timestamp")
    with pytest.raises(ValidationError):
        ValidationFinding(code="made_up_code", severity=Severity.WARNING, target=None, message="bad", evidence=[])


def test_relationship_from_alias_round_trips():
    relationship = Relationship.model_validate({"from": "orders.customer_id", "to_ref": "customers.customer_id", "cardinality": "many_to_one", "evidence": evidence()})
    assert relationship.from_ref == "orders.customer_id"
    assert relationship.model_dump(by_alias=True)["from"] == "orders.customer_id"


def test_contract_version_mismatch_is_rejected():
    with pytest.raises(ValidationError):
        PersistedArtifact(contract_version="2")
