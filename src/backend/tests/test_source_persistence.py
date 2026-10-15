from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from pydantic import ValidationError

from app.agent.contracts import InventoryView
from app.common.database import NotFoundError, PersistenceConflict
from app.sources.fixtures import DEMO_ORGANIZATION_ID, DEMO_SOURCE_ID, demo_inventory, seed_demo
from app.sources.service import InventoryService, get_inventory


def save(repository, inventory):
    return repository.save_snapshot(inventory, source_id=DEMO_SOURCE_ID,
                                    organization_id=DEMO_ORGANIZATION_ID, source_name="Demo")


def test_fixture_contains_bounded_metadata_only():
    inventory = demo_inventory()
    assert {resource.name for resource in inventory.resources} == {"orders", "orders.lines[]", "customers"}
    assert max(len(field.samples) for field in inventory.fields) == 3
    ambiguous = next(field for field in inventory.fields if field.ref.field_path == "order_date")
    assert ambiguous.ambiguity and ambiguous.samples == ["03/04/2026", "04/05/2026"]
    assert any(field.repeating and field.nullable for field in inventory.fields)
    assert all(field.native_type and field.description for field in inventory.fields)
    assert next(field for field in inventory.fields if field.ref.field_path == "email").samples == []
    data = inventory.model_dump(mode="json")
    with pytest.raises(ValidationError):
        InventoryView.model_validate({**data, "raw_rows": [{"order_id": "private"}]})
    with pytest.raises(ValidationError):
        InventoryView.model_validate({**data, "credentials": "sentinel-secret"})
    data["fields"][0]["samples"].append("fourth")
    with pytest.raises(ValidationError):
        InventoryView.model_validate(data)


def test_inventory_round_trip_and_scoped_service(inventory_repository, seeded_inventory):
    assert InventoryService(inventory_repository).get_inventory(seeded_inventory.snapshot_id) == demo_inventory()
    assert InventoryService(inventory_repository, organization_id=DEMO_ORGANIZATION_ID).get_inventory(seeded_inventory.snapshot_id) == demo_inventory()
    with pytest.raises(NotFoundError):
        InventoryService(inventory_repository, organization_id="other").get_inventory(seeded_inventory.snapshot_id)
    with pytest.raises(NotFoundError):
        inventory_repository.get_inventory("missing")


def test_environment_service(database, seeded_inventory, monkeypatch):
    monkeypatch.setattr("app.sources.service.Database", lambda: database)
    assert get_inventory(seeded_inventory.snapshot_id) == seeded_inventory


def test_sample_limit_revalidated_after_nested_mutation(inventory_repository):
    inventory = demo_inventory()
    inventory.fields[0].samples.append("fourth")
    with pytest.raises(ValidationError):
        save(inventory_repository, inventory)


def test_sample_limit_enforced_in_database_and_write_rolls_back(database):
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.transaction() as connection:
            connection.execute("INSERT INTO sources(id, organization_id, name) VALUES ('s', 'org', 'Demo')")
            connection.execute("INSERT INTO source_snapshots(id, source_id, fingerprint, contract_version) VALUES ('ss', 's', 'fp', '1')")
            connection.execute("INSERT INTO source_resources(snapshot_id, resource_id, name, kind, position) VALUES ('ss', 'r', 'r', 'table', 0)")
            connection.execute("""INSERT INTO source_fields(snapshot_id, resource_id, field_path, type, nullable,
                repeating, samples, status, position) VALUES ('ss', 'r', 'f', 'text', false, false, %s, 'stable', 0)""",
                               (["a", "b", "c", "d"],))
    with database.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM source_snapshots").fetchone()["n"] == 0


@pytest.mark.parametrize("statement", [
    "UPDATE source_snapshots SET fingerprint = 'changed'",
    "UPDATE source_snapshots SET sealed = false",
    "DELETE FROM source_snapshots",
    "UPDATE source_fields SET description = 'changed'",
    "DELETE FROM source_fields",
    "UPDATE source_resources SET name = 'changed'",
    "DELETE FROM source_resources",
    "INSERT INTO source_resources(snapshot_id, resource_id, name, kind, position) VALUES (%s, 'extra', 'extra', 'table', 9)",
    "INSERT INTO source_fields(snapshot_id, resource_id, field_path, type, nullable, repeating, status, position) VALUES (%s, 'orders', 'extra', 'text', true, false, 'new', 99)",
    "TRUNCATE source_fields",
])
def test_snapshot_immutability_through_direct_sql(database, seeded_inventory, inventory_repository, statement):
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.transaction() as connection:
            connection.execute(statement, (seeded_inventory.snapshot_id,) if "%s" in statement else None)
    assert inventory_repository.get_inventory(seeded_inventory.snapshot_id) == seeded_inventory


def test_snapshot_deduplication_and_new_version(inventory_repository, seeded_inventory):
    assert seed_demo(inventory_repository) == seeded_inventory
    assert save(inventory_repository, seeded_inventory.model_copy(update={"snapshot_id": "another-id"})).snapshot_id == seeded_inventory.snapshot_id
    changed = demo_inventory()
    changed.fields[0].samples[0] = "ORD-2000"
    with pytest.raises(PersistenceConflict):
        save(inventory_repository, changed)
    changed = changed.model_copy(update={"snapshot_id": "new-snapshot"})
    assert save(inventory_repository, changed) == changed
    assert inventory_repository.get_inventory(seeded_inventory.snapshot_id) == seeded_inventory


def test_concurrent_seed_publishes_one_snapshot(inventory_repository):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: seed_demo(inventory_repository), range(4)))
    assert all(inventory == results[0] for inventory in results)


@pytest.mark.parametrize("mutation", ["resource", "source", "count", "duplicate"])
def test_snapshot_rejects_inconsistent_references(inventory_repository, mutation):
    data = demo_inventory().model_dump(mode="json")
    if mutation == "resource":
        data["fields"][0]["ref"]["resource_id"] = "missing"
    elif mutation == "source":
        data["fields"][0]["ref"]["source_id"] = "wrong-source"
    elif mutation == "count":
        data["resources"][0]["field_count"] = 100
    else:
        data["fields"].append(data["fields"][0])
    with pytest.raises(ValueError):
        save(inventory_repository, InventoryView.model_validate(data))
