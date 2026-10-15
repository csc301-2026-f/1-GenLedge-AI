"""Alembic uses the same control database configuration as the repositories."""

from alembic import context

from app.common.database import Database
from app.common.migrations import migration_connection


def run(connection, schema):
    context.configure(connection=connection, version_table_schema=schema, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Control migrations require an online PostgreSQL connection")
elif context.config.attributes.get("connection") is not None:
    run(context.config.attributes["connection"], context.config.attributes["schema"])
else:
    database = Database()
    with migration_connection(database) as connection:
        run(connection, database.schema)
