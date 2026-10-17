"""Explicitly scoped maintenance; no database-wide deletion command."""
import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy.exc import SQLAlchemyError

from .postgres_store import PostgresIntakeStore
from .writer import IntakeNotFoundError


@click.command('intake-sweep')
@click.option('--organization', required=True, help='Authorized organization ID to maintain.')
@click.option('--source', required=True, help='Source ID to maintain.')
@with_appcontext
def sweep(organization, source):
    """Sweep eligible superseded records using the server's retention policy."""
    engine = current_app.extensions['auth_engine']
    if engine.dialect.name != 'postgresql' and not current_app.testing:
        raise click.ClickException('PostgreSQL is required.')
    store = PostgresIntakeStore(engine, organization_id=organization, environment=current_app.config['INTAKE_ENVIRONMENT'])
    try:
        removed = store.sweep_snapshots(source, keep_previous=current_app.config.get('INTAKE_KEEP_PREVIOUS', 1),
                                       grace_days=current_app.config.get('INTAKE_GRACE_DAYS', 7))
    except (SQLAlchemyError, IntakeNotFoundError, ValueError):
        raise click.ClickException('Cleanup failed. Check source scope, migrations and database access.') from None
    click.echo(f'Swept {len(removed)} superseded snapshot(s). Active, pinned and mapping-referenced data retained.')
