"""Auth capability package."""
import secrets
import warnings
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..migrations import upgrade_database


def init_auth(app):
    from .cli import create_user, db_check, init_db
    from .routes import bp

    if not app.config.get("SECRET_KEY"):
        if app.config["AUTH_ENV"] != "development" and not app.testing:
            raise RuntimeError("SECRET_KEY is required outside development.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        if not app.testing:
            warnings.warn("Using a temporary development SECRET_KEY; sessions reset on restart.")
    url = app.config.get("DATABASE_URL")
    if not url:
        if app.config["AUTH_ENV"] != "development" and not app.testing:
            raise RuntimeError("DATABASE_URL is required outside development.")
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + str(Path(app.instance_path) / "auth.sqlite3").replace("\\", "/")
    connect_args = {}
    if engine_url_is_postgres(url):
        if app.config.get('DB_SSLMODE'):
            connect_args['sslmode'] = app.config['DB_SSLMODE']
        if app.config.get('DB_SSLROOTCERT'):
            connect_args['sslrootcert'] = app.config['DB_SSLROOTCERT']
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    app.extensions["auth_engine"] = engine
    app.extensions["auth_database"] = sessionmaker(engine)
    app.extensions['auth_migrate'] = lambda: upgrade_database(engine)
    app.register_blueprint(bp)
    app.cli.add_command(init_db)
    app.cli.add_command(db_check)
    app.cli.add_command(create_user)


def engine_url_is_postgres(url: str) -> bool:
    return url.startswith(('postgresql://', 'postgresql+'))
