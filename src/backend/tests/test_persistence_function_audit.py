"""Public-function edge cases and regressions discovered in the Person A audit."""

import pytest

from app.agent.contracts import JobStatus, MappingDraft, ToolCallRequest, TransformOp
from app.common.database import Database, NotFoundError, PersistenceConflict
from app.mappings.repository import MappingRepository
from app.mappings.tool_repository import ToolResultRepository
from app.sources.fixtures import DEMO_ORGANIZATION_ID, DEMO_SOURCE_ID, demo_inventory
from scripts.smoke_persistence import run as smoke_persistence

from test_mapping_persistence import drafts


def test_database_requires_configuration(monkeypatch):
    monkeypatch.delenv("GENLEDGE_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="GENLEDGE_DATABASE_URL"):
        Database()


@pytest.mark.parametrize("schema", ["public", "pg_catalog", "information_schema", "pg_private"])
def test_database_rejects_reserved_schema(schema):
    with pytest.raises(ValueError):
        Database("dbname=unused", schema=schema)


@pytest.mark.parametrize("schema", ["", "   ", "bad\x00schema", "a" * 64, "é" * 32, 123, ["schema"]])
def test_database_rejects_invalid_schema_before_connecting(schema):
    with pytest.raises(ValueError):
        Database("dbname=unused", schema=schema)


def test_database_rejects_empty_environment_schema(monkeypatch):
    monkeypatch.setenv("GENLEDGE_DATABASE_SCHEMA", "")
    with pytest.raises(ValueError):
        Database("dbname=unused")


@pytest.mark.parametrize("schema", ["a" * 63, "é" * 31 + "a"])
def test_database_accepts_schema_at_identifier_byte_limit(schema):
    assert Database("dbname=unused", schema=schema).schema == schema


def test_database_defaults_and_explicit_schema_override_environment(monkeypatch):
    monkeypatch.delenv("GENLEDGE_DATABASE_SCHEMA", raising=False)
    assert Database("dbname=unused").schema == "genledge_control"
    monkeypatch.setenv("GENLEDGE_DATABASE_SCHEMA", "")
    assert Database("dbname=unused", schema="MixedCase").schema == "MixedCase"


@pytest.mark.parametrize("payload", [
    None,
    {"tables": [None]},
    {"tables": [123]},
    {"tables": [{"name": "orders", "columns": [None]}]},
    {"tables": [{"name": "orders", "columns": [123]}]},
    ["tables"],
    {"tables": [["name", "columns"]]},
    {"tables": [{"name": "orders", "columns": [["name", "type"]]}]},
])
def test_catalogue_malformed_container_reports_value_error(repository, payload):
    with pytest.raises(ValueError):
        repository.save_catalogue("invalid-catalogue", payload)
    with pytest.raises(NotFoundError):
        repository.get_catalogue("invalid-catalogue")


@pytest.mark.parametrize("payload", [
    {"tables": [{"name": "orders", "columns": [], "extra": "rejected"}]},
    {"tables": [{"name": "orders", "columns": [{"name": 1, "type": "text"}]}]},
    {"tables": [{"name": "orders", "columns": [{"name": "id", "type": "unknown"}]}]},
])
def test_catalogue_rejects_invalid_names_and_types(repository, payload):
    with pytest.raises(ValueError):
        repository.save_catalogue("invalid-catalogue", payload)


@pytest.mark.parametrize("operation", ["replay", "get_or_record"])
def test_tool_replay_preserves_json_boolean_and_number_identity(database, job, operation):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="typed-arguments", name="profile_resource", arguments={"options": {"limit": True}})
    tools.save_result(job["id"], call, status="ok", payload={"count": 1}, redacted=True)
    different = call.model_copy(update={"arguments": {"options": {"limit": 1}}})

    def must_not_run():
        pytest.fail("A conflicting request must not invoke a connector")

    with pytest.raises(PersistenceConflict):
        if operation == "replay":
            tools.replay(job["id"], different)
        else:
            tools.get_or_record(job["id"], different, must_not_run, redacted=True)


def test_tool_replay_uses_the_same_normalized_json_as_persistence(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="normalized", name="profile_resource", arguments={"fields": ("id", "sku")})
    ref = tools.save_result(job["id"], call, status="ok", payload={}, redacted=True)
    assert tools.replay(job["id"], call)["ref"].result_ref == ref.result_ref


def test_tool_replay_ignores_object_key_order_and_equivalent_number_forms(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="ordered", name="profile_resource", arguments={"limit": 1, "fields": ["id", "sku"]})
    ref = tools.save_result(job["id"], call, status="ok", payload={}, redacted=True)
    reordered = call.model_copy(update={"arguments": {"fields": ["id", "sku"], "limit": 1.0}})
    assert tools.replay(job["id"], reordered)["ref"].result_ref == ref.result_ref


def test_tool_replay_preserves_array_order_and_large_integer_values(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="exact-values", name="profile_resource", arguments={"fields": ["id", "sku"], "key": 2**60})
    tools.save_result(job["id"], call, status="ok", payload={}, redacted=True)
    for arguments in [{"fields": ["sku", "id"], "key": 2**60}, {"fields": ["id", "sku"], "key": 2**60 + 1}]:
        with pytest.raises(PersistenceConflict):
            tools.replay(job["id"], call.model_copy(update={"arguments": arguments}))


def test_revision_replay_rejects_boolean_to_number_operation_change(repository, job):
    model, mapping, _, _ = drafts()
    mapping.mappings[0].operations.append(TransformOp(name="default_value", args={"value": True}))
    repository.save_revision(job["id"], model, mapping_draft=mapping)
    changed = MappingDraft.model_validate_json(mapping.model_dump_json())
    changed.mappings[0].operations[0].args["value"] = 1
    with pytest.raises(PersistenceConflict):
        repository.save_revision(job["id"], model, mapping_draft=changed)


def test_source_cannot_move_between_organizations(inventory_repository, seeded_inventory):
    with pytest.raises(PersistenceConflict):
        inventory_repository.save_snapshot(demo_inventory(), source_id=DEMO_SOURCE_ID,
                                           organization_id="other", source_name="Changed owner")
    assert inventory_repository.get_inventory(seeded_inventory.snapshot_id) == seeded_inventory


@pytest.mark.parametrize("changes", [
    {"idempotency_key": ""}, {"source_snapshot_ids": []}, {"model_mode": "unknown"},
])
def test_create_job_rejects_invalid_arguments(repository, seeded_inventory, changes):
    arguments = dict(source_snapshot_ids=[seeded_inventory.snapshot_id], idempotency_key="invalid-job", created_by="reviewer")
    with pytest.raises(ValueError):
        repository.create_job(**{**arguments, **changes})


def test_create_job_rejects_duplicate_snapshots(repository, seeded_inventory):
    with pytest.raises(ValueError):
        repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id] * 2,
                              idempotency_key="duplicate-snapshots", created_by="reviewer")


def test_revision_without_optional_mapping_and_status_compare_and_set(repository, job):
    model = drafts()[0]
    package = repository.save_revision(job["id"], model)
    assert package["model_draft"] == model
    assert package["mapping_draft"] is None and package["findings"] == package["coverage"] == []
    assert repository.get_revision(job["id"], 0) == package
    assert repository.save_revision(job["id"], model) == package
    updated = repository.update_status(job["id"], JobStatus.RUNNING, expected_status=JobStatus.QUEUED)
    assert updated["status"] == JobStatus.RUNNING and updated["failure"] is None


@pytest.mark.parametrize("flags", [{"fact_orders": 1}, {1: True}])
def test_revision_rejects_invalid_table_flags(repository, job, flags):
    with pytest.raises(ValueError):
        repository.save_revision(job["id"], drafts()[0], table_is_new=flags)


def test_missing_revision_and_edit_report_not_found(repository, job):
    with pytest.raises(NotFoundError):
        repository.get_revision(job["id"])
    with pytest.raises(NotFoundError):
        repository.mark_edit_applied(job["id"], "missing-edit")


@pytest.mark.parametrize("changes", [
    {"edit_id": ""}, {"idempotency_key": ""}, {"target": ""}, {"decision": "approve"},
])
def test_edit_rejects_invalid_arguments(repository, job, changes):
    revision = repository.save_revision(job["id"], drafts()[0])
    arguments = dict(edit_id="edit", revision_id=revision["id"], reviewer="reviewer", reviewer_role="editor",
                     target="fact_orders", decision="reject", idempotency_key="edit")
    with pytest.raises(ValueError):
        repository.save_edit(job["id"], **{**arguments, **changes})
    assert repository.list_edits(job["id"]) == []


def test_idempotency_lookup_does_not_cross_organization(database, repository, job):
    other = MappingRepository(database, organization_id="other")
    assert other.get_job_by_idempotency_key("create-job") is None


def test_tool_factory_failure_rolls_back_and_can_retry(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="failed-then-retried", name="profile_resource")

    def unavailable():
        raise TimeoutError("Synthetic connector timeout")

    with pytest.raises(TimeoutError):
        tools.get_or_record(job["id"], call, unavailable, redacted=True)
    assert tools.replay(job["id"], call) is None
    result = tools.get_or_record(job["id"], call, lambda: ("ok", {"count": 1}), redacted=True)
    assert not result["ref"].replayed and result["payload"] == {"count": 1}


def test_nonfinite_tool_payload_rolls_back(database, job):
    tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
    call = ToolCallRequest(id="nan-payload", name="profile_resource")
    with pytest.raises(ValueError):
        tools.save_result(job["id"], call, status="ok", payload={"count": float("nan")}, redacted=True)
    assert tools.replay(job["id"], call) is None


def test_smoke_command_exercises_all_persisted_artifacts_twice(database, monkeypatch, capsys):
    monkeypatch.setenv("GENLEDGE_DATABASE_URL", database.dsn)
    monkeypatch.setenv("GENLEDGE_DATABASE_SCHEMA", database.schema)
    smoke_persistence()
    first = capsys.readouterr().out
    smoke_persistence()
    second = capsys.readouterr().out
    assert "created=True" in first and "factory_calls=1" in first
    assert "created=False" in second and "tool_replayed=True" in second and "factory_calls=0" in second
    assert "decision=reject" in first and "decision=reject" in second
