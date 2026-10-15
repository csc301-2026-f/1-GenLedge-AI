"""Flask application factory.

Flask is imported **inside** `create_app`, not at module import time. The US4
harness under `app.agent` must stay importable, and testable, on a machine without
Flask or a database — importing a submodule must not drag in a web framework.
"""

from __future__ import annotations

from typing import Any

from .config import Config


def create_app(config_object: object | None = None) -> Any:
    """Create the Flask application without starting external services."""
    from flask import Flask

    from .auth.routes import bp as auth_bp

    app = Flask(__name__)
    app.config.from_object(Config())
    if config_object is not None:
        app.config.from_object(config_object)
    app.register_blueprint(auth_bp)
    return app
