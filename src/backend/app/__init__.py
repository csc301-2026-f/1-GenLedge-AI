from flask import Flask

from .config import Config


def create_app(config_object: object | None = None) -> Flask:
    """Create the Flask application without starting external services."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_object is not None:
        app.config.from_object(config_object)
    from .auth import init_auth
    init_auth(app)
    return app
