"""Sources capability package."""


def init_sources(app):
    from app.common.database import Database
    from .repository import InventoryRepository
    from .routes import bp

    app.register_blueprint(bp)
    dsn = app.config.get("GENLEDGE_DATABASE_URL")
    if dsn:
        app.extensions["source_inventory_repository"] = InventoryRepository(
            Database(dsn, schema=app.config["GENLEDGE_DATABASE_SCHEMA"])
        )
