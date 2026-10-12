import uuid

import click
from flask.cli import with_appcontext
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from .models import Organization, User
from .service import database, normalize_email


@click.command("auth-init-db")
@with_appcontext
def init_db():
    """Apply all pending application database migrations."""
    from flask import current_app
    try:
        current_app.extensions['auth_migrate']()
    except RuntimeError as error:
        raise click.ClickException(str(error)) from error
    except SQLAlchemyError as error:
        raise click.ClickException('Database migration failed.') from error
    click.echo('Database migrations applied.')


@click.command('auth-db-check')
@with_appcontext
def db_check():
    """Report database identity and TLS state without writing data."""
    from flask import current_app
    from sqlalchemy import text

    engine = current_app.extensions['auth_engine']
    try:
        with engine.connect() as connection:
            if engine.dialect.name == 'postgresql':
                identity = connection.execute(text(
                    'SELECT current_user, current_database(), '
                    '(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())'
                )).one()
                click.echo(f'role={identity[0]} database={identity[1]} tls={identity[2]}')
            else:
                click.echo(f'dialect={engine.dialect.name} database=local-development')
    except SQLAlchemyError as error:
        raise click.ClickException('Database connection failed. Check the URL, credentials, network, and TLS settings.') from error


@click.command("auth-create-user")
@click.option("--email", required=True)
@click.option("--organization", required=True)
@click.option("--role", type=click.Choice(["Administrator", "Analyst"]), default="Analyst")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_user(email, organization, role, password):
    """Provision an account; passwords are prompted, never printed."""
    try:
        email = normalize_email(email)
        organization = organization.strip()
        if not 1 <= len(organization) <= 200:
            raise ValueError("Organization must contain 1–200 characters.")
        if not 12 <= len(password) <= 1024:
            raise ValueError("Password must contain 12–1024 characters.")
        with database() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise ValueError("Email already exists.")
            org = db.scalar(select(Organization).where(Organization.name == organization))
            if not org:
                org = Organization(id=str(uuid.uuid4()), name=organization)
                db.add(org)
                db.flush()
            db.add(User(id=str(uuid.uuid4()), email=email,
                        password_hash=generate_password_hash(password),
                        organization_id=org.id, role=role))
            db.commit()
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    except SQLAlchemyError as error:
        raise click.ClickException("Database unavailable or account could not be created. Run auth-init-db first.") from error
    click.echo("Account created.")
