"""Persistence tests use disposable local schemas, never the team's database."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from app.common.database import Database
from app.common.migrations import migrate
from app.mappings.repository import MappingRepository
from app.sources.fixtures import DEMO_ORGANIZATION_ID, seed_demo
from app.sources.repository import InventoryRepository


@pytest.fixture
def empty_database():
    dsn = os.environ.get("GENLEDGE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set GENLEDGE_TEST_DATABASE_URL to an isolated local PostgreSQL database")
    options = conninfo_to_dict(dsn)
    if (options.get("host", "localhost") not in {"localhost", "127.0.0.1", "::1"}
            or options.get("hostaddr", "127.0.0.1") not in {"127.0.0.1", "::1"} or "service" in options):
        pytest.fail("Persistence tests require local PostgreSQL, never a shared/team server")
    database = Database(dsn, schema="test_us4_" + uuid4().hex)
    try:
        yield database
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(database.schema)))


@pytest.fixture
def database(empty_database):
    migrate(empty_database)
    return empty_database


@pytest.fixture
def inventory_repository(database):
    return InventoryRepository(database)


@pytest.fixture
def seeded_inventory(inventory_repository):
    return seed_demo(inventory_repository)


@pytest.fixture
def repository(database, seeded_inventory):
    return MappingRepository(database, organization_id=DEMO_ORGANIZATION_ID)


@pytest.fixture
def job(repository, seeded_inventory):
    return repository.create_job(source_snapshot_ids=[seeded_inventory.snapshot_id],
                                 idempotency_key="create-job", created_by="demo-reviewer", model_mode="fake")[0]
