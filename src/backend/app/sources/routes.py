"""Read-only HTTP boundary for organization-scoped saved inventory."""

import psycopg
from flask import Blueprint, current_app, g
from sqlalchemy.exc import SQLAlchemyError

from app.agent.contracts import CONTRACT_VERSION
from app.auth.service import login_required
from app.common.database import NotFoundError
from app.common.errors import make_error
from .service import InventoryService

bp = Blueprint("sources", __name__, url_prefix="/api/sources")


def error_response(code, message, status):
    return make_error(code, message).model_dump(mode="json"), status


@bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(NotFoundError)
def not_found(error):
    return error_response("snapshot_not_found", "Snapshot not found.", 404)


@bp.errorhandler(psycopg.Error)
@bp.errorhandler(SQLAlchemyError)
def database_error(error):
    current_app.logger.error("Saved snapshot request failed (%s).", type(error).__name__)
    return error_response("snapshot_unavailable", "Snapshot service is unavailable. Please try again.", 503)


@bp.get("/snapshots/<path:snapshot_id>")
@login_required
def get_snapshot(snapshot_id):
    repository = current_app.extensions.get("source_inventory_repository")
    if repository is None:
        return error_response("snapshot_not_configured", "Snapshot storage is not configured.", 503)
    inventory = InventoryService(
        repository, organization_id=g.user["organizationId"],
    ).get_inventory(snapshot_id)
    return {"contract_version": CONTRACT_VERSION, "inventory": inventory.model_dump(mode="json")}
