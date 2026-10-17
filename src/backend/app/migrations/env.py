"""Alembic environment for the auth schema."""
from alembic import context

from app.auth.models import Base


target_metadata = Base.metadata
connection = context.config.attributes['connection']
context.configure(connection=connection, target_metadata=target_metadata)

with context.begin_transaction():
    context.run_migrations()
