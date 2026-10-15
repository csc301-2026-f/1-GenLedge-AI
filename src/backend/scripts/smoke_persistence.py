"""Run twice to verify durable inventory, packages, decisions, and replay.

From src/backend: python -m scripts.smoke_persistence
Requires GENLEDGE_DATABASE_URL. Uses a fixed synthetic job and no model/connector.
"""

from app.agent.contracts import (
    Attribute, CoverageRecord, EvidenceRef, InventoryView, Mapping, MappingDraft,
    ModelDraft, SourceCoverage, Table, ToolCallRequest, ValidationFinding,
)
from app.common.database import Database
from app.common.migrations import migrate
from app.mappings.repository import MappingRepository
from app.mappings.tool_repository import ToolResultRepository
from app.sources.fixtures import DEMO_ORGANIZATION_ID, seed_demo
from app.sources.repository import InventoryRepository
from app.sources.service import get_inventory


def run() -> None:
    database = Database()
    migrate(database)
    inventory = seed_demo(InventoryRepository(database))
    assert isinstance(get_inventory(inventory.snapshot_id), InventoryView)
    assert all(len(field.samples) <= 3 for field in inventory.fields)
    jobs = MappingRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    job, created = jobs.create_job(source_snapshot_ids=[inventory.snapshot_id],
                                   idempotency_key="person-a-smoke-v1", created_by="smoke-reviewer", model_mode="fake")
    duplicate, duplicate_created = jobs.create_job(source_snapshot_ids=[inventory.snapshot_id],
                                                  idempotency_key="person-a-smoke-v1", created_by="smoke-reviewer", model_mode="fake")
    assert duplicate["id"] == job["id"] and not duplicate_created

    evidence = [EvidenceRef(resource_id="orders", field_path="order_id")]
    coverage = [CoverageRecord(
        resource_id=field.ref.resource_id, field_path=field.ref.field_path,
        disposition="represented" if (field.ref.resource_id, field.ref.field_path) == ("orders", "order_id") else "unresolved",
        reason="Illustrative persistence smoke test; application validation is a separate workstream")
        for field in inventory.fields]
    model = ModelDraft(revision=0, tables=[Table(
        id="fact_orders", name="fact_orders", kind="event", grain="One row per order", key=["order_id"],
        attributes=[Attribute(id="order_id", type="text", nullable=False, evidence=evidence, confidence=0.95)],
        relationships=[], rationale="Demonstrates an immutable persisted proposal")],
        source_coverage=[SourceCoverage(**record.model_dump()) for record in coverage])
    mapping = MappingDraft(revision=0, based_on_model_revision=0, mappings=[Mapping(
        target="fact_orders.order_id", sources=["orders.order_id"], confidence=0.95)])
    findings = [ValidationFinding(code="ambiguous_date", severity="blocker", message="Order date locale remains unknown",
                                  evidence=[EvidenceRef(resource_id="orders", field_path="order_date")])]
    package = jobs.save_revision(job["id"], model, mapping_draft=mapping, findings=findings,
                                 coverage=coverage, table_is_new={"fact_orders": True})
    assert jobs.get_revision(job["id"])["findings"] == findings
    assert jobs.get_revision(job["id"])["coverage"] == coverage

    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="smoke-profile-v1", name="profile_resource",
                           arguments={"source_id": "demo-orders-source", "resource_id": "orders.lines[]"})
    calls = []

    def synthetic_profile():
        calls.append(1)
        return "ok", {"resource_id": "orders.lines[]", "repeating": True}

    result = tools.get_or_record(job["id"], call, synthetic_profile, redacted=True)
    replay = tools.get_or_record(job["id"], call, synthetic_profile, redacted=True)
    assert replay["ref"].replayed and len(calls) <= 1
    assert result["ref"].result_ref == replay["ref"].result_ref
    edit_args = dict(edit_id="person-a-smoke-edit-v1", revision_id=package["id"], reviewer="smoke-reviewer",
                     reviewer_role="editor", target="fact_orders", decision="reject", idempotency_key="person-a-smoke-edit-v1")
    edit, _ = jobs.save_edit(job["id"], **edit_args)
    same_edit, edit_created = jobs.save_edit(job["id"], **edit_args)
    assert same_edit == edit and not edit_created
    assert jobs.list_edits(job["id"])[0]["decision"] == "reject"
    print(f"snapshot={inventory.snapshot_id}; resources={len(inventory.resources)}; fields={len(inventory.fields)}")
    print(f"job_id={job['id']}; created={created}; revision={package['revision']}")
    print(f"tool_replayed={result['ref'].replayed}; factory_calls={len(calls)}; decision=reject")
    print("Persistence smoke test passed; run again to verify replay across processes")


if __name__ == "__main__":
    run()
