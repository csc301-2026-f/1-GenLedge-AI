"""Auth capability package."""
import secrets
import warnings
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def init_auth(app):
    from .cli import create_user, init_db
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
    engine = create_engine(url, pool_pre_ping=True)
    app.extensions["auth_engine"] = engine
    app.extensions["auth_database"] = sessionmaker(engine)
    app.register_blueprint(bp)
    app.cli.add_command(init_db)
    app.cli.add_command(create_user)
