import uuid

import click
from flask.cli import with_appcontext
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from .models import Base, Organization, User
from .service import database, normalize_email


@click.command("auth-init-db")
@with_appcontext
def init_db():
    """Create missing auth tables without deleting existing data."""
    from flask import current_app
    Base.metadata.create_all(current_app.extensions["auth_engine"])
    click.echo("Auth tables ready.")


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
