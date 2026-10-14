from flask import Flask

from .agent.graph import init_agent
from .config import Config
from .auth.routes import bp as auth_bp


def create_app(config_object: object | None = None) -> Flask:
    """Create the Flask application without starting external services."""
    app = Flask(__name__)
    app.config.from_object(Config())
    if config_object is not None:
        app.config.from_object(config_object)
    app.register_blueprint(auth_bp)
    # Registers no routes yet; emits the resolved model mode at start-up so the
    # deployment can see whether it is on the fake or the live adapter, and never a
    # secret. A half-configured live mode is logged, not fatal.
    init_agent(app)
    return app
