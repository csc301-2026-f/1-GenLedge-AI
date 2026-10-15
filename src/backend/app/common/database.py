"""PostgreSQL connections for capability-owned persistence adapters."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn: str | None = None, *, schema: str | None = None):
        self.dsn = dsn or os.environ.get("GENLEDGE_DATABASE_URL")
        if not self.dsn:
            raise ValueError("Set GENLEDGE_DATABASE_URL to the PostgreSQL control database DSN")
        self.schema = schema or os.environ.get("GENLEDGE_DATABASE_SCHEMA", "genledge_control")
        if self.schema in {"public", "pg_catalog", "information_schema"} or self.schema.startswith("pg_"):
            raise ValueError("Use a dedicated application schema")

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        # Each operation owns its connection; API and worker share durable rows.
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=10) as connection:
            connection.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
            yield connection


class NotFoundError(LookupError):
    """A record is missing from the supplied organization scope."""


class PersistenceConflict(ValueError):
    """An immutable ID or idempotency key was reused with different content."""
