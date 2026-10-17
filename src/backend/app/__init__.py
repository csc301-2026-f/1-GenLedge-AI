from flask import Flask

from .config import Config


def create_app(config_object: object | None = None) -> Flask:
    """Create the Flask application without starting external services."""
    app = Flask(__name__)
    app.config.from_object(Config())
    if config_object is not None:
        app.config.from_object(config_object)
    from .sources.routes import bp as sources_bp
    app.register_blueprint(sources_bp)
    from .auth import init_auth
    init_auth(app)
    from .sources.cli import sweep
    app.cli.add_command(sweep)
    return app
