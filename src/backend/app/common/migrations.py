"""Alembic upgrade entrypoint with transaction-scoped startup serialization."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from .database import Database

BACKEND = Path(__file__).resolve().parents[2]


@contextmanager
def migration_connection(database: Database) -> Iterator[Connection]:
    engine = create_engine("postgresql+psycopg://", poolclass=NullPool,
                           creator=lambda: psycopg.connect(database.dsn, connect_timeout=10))
    try:
        with engine.begin() as connection:
            raw = connection.connection.driver_connection
            raw.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("genledge:migrations:" + database.schema,))
            raw.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(database.schema)))
            raw.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(database.schema)))
            yield connection
    finally:
        engine.dispose()


def migrate(database: Database | None = None) -> None:
    database = database or Database()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    with migration_connection(database) as connection:
        config.attributes.update(connection=connection, schema=database.schema)
        command.upgrade(config, "head")


if __name__ == "__main__":
    migrate()
    print("Control database migrated to head")
