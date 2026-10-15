import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg import sql

from app.agent.contracts import (
    AgentBudgets, Attribute, CoverageRecord, EvidenceRef, FailureInfo, JobStatus,
    Mapping, MappingDraft, ModelDraft, Table, ToolCallRequest, ValidationFinding,
)
from app.common.database import Database, NotFoundError, PersistenceConflict
from app.common.migrations import migrate
from app.mappings.repository import MappingRepository
from app.mappings.tool_repository import ToolResultRepository
from app.sources.fixtures import DEMO_ORGANIZATION_ID


def drafts(revision=0):
    evidence = [EvidenceRef(resource_id="orders", field_path="order_id")]
    model = ModelDraft(revision=revision, tables=[Table(
        id="fact_orders", name="fact_orders", kind="event", grain="One row per order", key=["order_id"],
        attributes=[Attribute(id="order_id", type="text", nullable=False, evidence=evidence, confidence=0.95)],
        relationships=[], rationale="Preserves the order grain")], source_coverage=[])
    mapping = MappingDraft(revision=revision, based_on_model_revision=revision, mappings=[Mapping(
        target="fact_orders.order_id", sources=["orders.order_id"], confidence=0.95)])
    findings = [ValidationFinding(code="ambiguous_date", severity="blocker", target="fact_orders.order_date",
                                  message="Date locale is unknown", evidence=[EvidenceRef(resource_id="orders", field_path="order_date")])]
    coverage = [CoverageRecord(resource_id="orders", field_path="order_date", disposition="unresolved", reason="Unknown locale"),
                CoverageRecord(resource_id="orders", field_path="order_id", disposition="represented", reason="Order key")]
    return model, mapping, findings, coverage


def save_package(repository, job_id, revision=0):
    model, mapping, findings, coverage = drafts(revision)
    return repository.save_revision(job_id, model, mapping_draft=mapping, findings=findings,
                                    coverage=coverage, table_is_new={"fact_orders": True})


def test_job_revision_findings_coverage_and_failure_round_trip(repository, job):
    assert job["status"] == JobStatus.QUEUED and job["budgets"] == AgentBudgets()
    package = save_package(repository, job["id"])
    assert repository.get_revision(job["id"]) == package
    assert [package[key] for key in ("model_draft", "mapping_draft", "findings", "coverage")] == list(drafts())
    failed = repository.update_status(job["id"], JobStatus.FAILED, expected_status=JobStatus.QUEUED,
                                      failure=FailureInfo(code="source_unavailable", message="Retry later", retryable=True))
    assert repository.get_job(job["id"]) == failed and failed["failure"].retryable
    with pytest.raises(PersistenceConflict):
        repository.update_status(job["id"], JobStatus.RUNNING, expected_status=JobStatus.QUEUED)


def test_revision_history_and_idempotent_save(repository, job):
    first = save_package(repository, job["id"])
    assert save_package(repository, job["id"]) == first
    second = save_package(repository, job["id"], 1)
    assert repository.get_revision(job["id"]) == second
    assert repository.get_revision(job["id"], 0) == first
    with pytest.raises(PersistenceConflict):
        repository.save_revision(job["id"], drafts()[0].model_copy(update={"notes": "Different content"}))


def test_package_write_is_atomic(repository, job, database):
    model, mapping, findings, coverage = drafts()
    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.save_revision(job["id"], model, mapping_draft=mapping, findings=findings, coverage=coverage + [coverage[0]])
    with pytest.raises(NotFoundError):
        repository.get_revision(job["id"])
    with database.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM proposal_findings").fetchone()["n"] == 0


def test_duplicate_job_idempotency_under_concurrent_requests(repository, seeded_inventory):
    def create(_):
        return repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="same-key", created_by="reviewer")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert len({row["id"] for row, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert repository.get_job_by_idempotency_key("same-key")["id"] == results[0][0]["id"]
    assert repository.get_job_by_idempotency_key("unknown-key") is None
    with pytest.raises(PersistenceConflict):
        repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="same-key",
                              created_by="reviewer", budgets=AgentBudgets(max_tool_calls=1))


def test_job_snapshot_scope_and_missing_records(repository, seeded_inventory, database, job):
    with pytest.raises(NotFoundError):
        repository.create_job(source_snapshot_ids=["missing"], idempotency_key="key", created_by="reviewer")
    other = MappingRepository(database, organization_id="other-organization")
    with pytest.raises(NotFoundError):
        other.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="key", created_by="reviewer")
    for read in [lambda: other.get_job(job["id"]), lambda: other.get_revision(job["id"]),
                 lambda: other.update_status(job["id"], JobStatus.RUNNING), lambda: other.list_edits(job["id"]),
                 lambda: other.save_revision(job["id"], drafts()[0])]:
        with pytest.raises(NotFoundError):
            read()


def test_catalogue_round_trip_and_scope(repository, seeded_inventory, database):
    catalogue = {"tables": [{"name": "fact_orders", "columns": [{"name": "order_id", "type": "text"}]}]}
    assert repository.save_catalogue("catalogue-1", catalogue) == catalogue
    assert repository.save_catalogue("catalogue-1", catalogue) == catalogue
    job, _ = repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="catalog-job",
                                   catalog_ref="catalogue-1", created_by="reviewer")
    assert job["catalog_ref"] == "catalogue-1"
    with pytest.raises(PersistenceConflict):
        repository.save_catalogue("catalogue-1", {"tables": []})
    with pytest.raises(ValueError):
        repository.save_catalogue("unsafe", {"tables": [], "password": "sentinel"})
    with pytest.raises(NotFoundError):
        MappingRepository(database, organization_id="other").get_catalogue("catalogue-1")


def test_tool_replay_and_result_reference_loading(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="call-1", name="profile_resource", arguments={"resource_id": "orders.lines[]"})
    calls = []
    def factory():
        calls.append(1)
        return "ok", {"fields": [{"path": "quantity", "samples": ["1", "2"]}]}
    first = tools.get_or_record(job["id"], call, factory, redacted=True)
    restarted = ToolResultRepository(Database(os.environ["GENLEDGE_TEST_DATABASE_URL"], schema=database.schema),
                                      organization_id=DEMO_ORGANIZATION_ID)
    replay = restarted.get_or_record(job["id"], call, factory, redacted=True)
    assert not first["ref"].replayed and replay["ref"].replayed
    assert replay["ref"].result_ref == first["ref"].result_ref and calls == [1]
    assert replay["payload"] == first["payload"] == restarted.get_result(first["ref"].result_ref)["payload"]
    with pytest.raises(NotFoundError):
        ToolResultRepository(database, organization_id="other").get_result(first["ref"].result_ref)
    with pytest.raises(PersistenceConflict):
        restarted.replay(job["id"], call.model_copy(update={"arguments": {"resource_id": "customers"}}))
    with pytest.raises(ValueError):
        restarted.save_result(job["id"], call, status="ok", payload={}, redacted=False)


def test_concurrent_tool_replay_records_errors_once(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="call-error", name="sample_rows")
    calls = []
    def factory():
        calls.append(1)
        return "error", {"code": "unsupported_capability", "message": "Sampling not supported"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: tools.get_or_record(job["id"], call, factory, redacted=True), range(4)))
    assert calls == [1] and len({result["ref"].result_ref for result in results}) == 1
    assert sum(not result["ref"].replayed for result in results) == 1
    assert all(result["ref"].status == "error" for result in results)


def test_tool_call_ids_are_scoped_to_job(database, repository, job, seeded_inventory):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    second, _ = repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="job-two", created_by="reviewer")
    call = ToolCallRequest(id="same-call", name="profile_resource")
    first_ref = tools.save_result(job["id"], call, status="ok", payload={"count": 1}, redacted=True)
    second_ref = tools.save_result(second["id"], call, status="ok", payload={"count": 2}, redacted=True)
    assert first_ref.result_ref != second_ref.result_ref
    with pytest.raises(NotFoundError):
        ToolResultRepository(database, organization_id="other").replay(job["id"], call)


def test_edits_replay_and_preserve_unrelated_decisions(repository, job):
    package = save_package(repository, job["id"])
    edit_args = dict(edit_id="edit-1", revision_id=package["id"], reviewer="reviewer", reviewer_role="editor",
                     target="fact_orders", decision="reject", idempotency_key="edit-request-1")
    first, created = repository.save_edit(job["id"], **edit_args)
    assert created
    replay, created = repository.save_edit(job["id"], **edit_args)
    assert not created and replay == first
    repository.save_edit(job["id"], **{**edit_args, "edit_id": "edit-2", "idempotency_key": "edit-request-2",
                                      "target": "dim_customers", "decision": "accept"})
    assert [(edit["target"], edit["decision"]) for edit in repository.list_edits(job["id"])] == [
        ("fact_orders", "reject"), ("dim_customers", "accept")]
    with pytest.raises(PersistenceConflict):
        repository.save_edit(job["id"], **{**edit_args, "decision": "accept"})
    applied = repository.mark_edit_applied(job["id"], "edit-1")
    assert repository.mark_edit_applied(job["id"], "edit-1") == applied
    assert [edit["id"] for edit in repository.list_edits(job["id"], pending_only=True)] == ["edit-2"]
    assert repository.get_revision(job["id"]) == package


def test_records_and_replay_visible_in_new_process(database, repository, job, seeded_inventory):
    package = save_package(repository, job["id"])
    call = ToolCallRequest(id="restart-call", name="profile_resource")
    ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID).save_result(
        job["id"], call, status="ok", payload={"count": 3}, redacted=True)
    repository.save_edit(job["id"], edit_id="restart-edit", revision_id=package["id"], reviewer="reviewer",
                         reviewer_role="editor", target="fact_orders", decision="reject", idempotency_key="restart-edit")
    code = '''
import os
from app.common.database import Database
from app.sources.repository import InventoryRepository
from app.mappings.repository import MappingRepository
from app.mappings.tool_repository import ToolResultRepository
from app.agent.contracts import ToolCallRequest
db = Database(os.environ["GENLEDGE_TEST_DATABASE_URL"], schema=os.environ["TEST_SCHEMA"])
repo = MappingRepository(db, organization_id="demo-organization")
job_id = os.environ["TEST_JOB"]
assert InventoryRepository(db).get_inventory(os.environ["TEST_SNAPSHOT"]).fields
assert repo.get_job(job_id)["status"] == "queued"
duplicate, created = repo.create_job(source_snapshot_ids=[os.environ["TEST_SNAPSHOT"]],
                                    idempotency_key="create-job", created_by="demo-reviewer", model_mode="fake")
assert duplicate["id"] == job_id and not created
package = repo.get_revision(job_id)
assert package["findings"][0].code == "ambiguous_date"
assert package["coverage"][0].disposition == "unresolved"
assert repo.list_edits(job_id)[0]["decision"] == "reject"
tools = ToolResultRepository(db, organization_id="demo-organization")
def forbidden():
    raise AssertionError("Committed tool call was dispatched again")
result = tools.get_or_record(job_id, ToolCallRequest(id="restart-call", name="profile_resource"), forbidden, redacted=True)
assert result["ref"].replayed and result["payload"] == {"count": 3}
print("restart-visible")
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
                            env={**os.environ, "TEST_SCHEMA": database.schema, "TEST_JOB": job["id"],
                                 "TEST_SNAPSHOT": seeded_inventory.snapshot_id})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "restart-visible"


def test_job_and_revision_artifacts_are_immutable(database, repository, job):
    save_package(repository, job["id"])
    for statement in ["UPDATE proposal_jobs SET budgets_json = '{}'", "UPDATE proposal_revisions SET model_draft_json = '{}'",
                      "DELETE FROM proposal_findings", "DELETE FROM source_coverage_records"]:
        with pytest.raises(psycopg.errors.CheckViolation):
            with database.transaction() as connection:
                connection.execute(statement)


def test_alembic_migration_repeatable_and_concurrent(empty_database):
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: migrate(empty_database), range(3)))
    with empty_database.transaction() as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [{"version_num": "001_us4_control_plane"}]


def test_failed_alembic_migration_rolls_back(empty_database):
    with empty_database.transaction() as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(empty_database.schema)))
        connection.execute("CREATE TABLE sources(id integer)")
    with pytest.raises(psycopg.errors.DuplicateTable):
        migrate(empty_database)
    with empty_database.transaction() as connection:
        assert connection.execute("SELECT to_regclass('alembic_version') AS name").fetchone()["name"] is None
        assert connection.execute("SELECT to_regclass('source_snapshots') AS name").fetchone()["name"] is None
