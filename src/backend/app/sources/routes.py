"""Authenticated file validation, publication and organization-scoped listing."""
import secrets
from dataclasses import asdict

from flask import Blueprint, current_app, g, request, session
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from .connectors.files import MAX_FILE_BYTES, FileValidationError, parse_file
from ..auth.service import login_required
from .postgres_store import PostgresIntakeStore
from .service import import_file, ImportStorageError
from .writer import PublicationConflict
from .local_store import IntakeNotFoundError

bp = Blueprint("sources", __name__, url_prefix="/api/sources")


@bp.before_request
@login_required
def protect_upload():
    # Multipart framing is additional to the independently enforced file limit.
    request.max_content_length = MAX_FILE_BYTES + 1_000_000
    request.max_form_parts = 10
    if request.method in {"POST", "PUT", "DELETE"}:
        expected = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not isinstance(expected, str) or not secrets.compare_digest(expected.encode(), supplied.encode()):
            return {"error": "Invalid CSRF token. Refresh and try again."}, 403


@bp.after_request
def prevent_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(FileValidationError)
def invalid_file(error):
    return {"error": str(error), "code": error.code}, error.status


@bp.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    if '/mappings/' in request.path:
        return {'error': 'Mapping request is too large.', 'code': 'request_too_large'}, 413
    return {"error": "Upload request is too large. Maximum file size is 25 MB.", "code": "file_too_large"}, 413


@bp.errorhandler(BadRequest)
def invalid_request(error):
    return {"error": "Invalid multipart upload request."}, 400


@bp.get("/uploads/csrf")
def upload_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrfToken": session["csrf_token"]}


@bp.post("/uploads/validate")
def validate_upload():
    upload = uploaded_file()
    return parse_file(upload.filename, upload.stream).summary()


def uploaded_file():
    files = list(request.files.items(multi=True))
    if len(files) != 1 or files[0][0] != "file" or not files[0][1].filename:
        raise BadRequest("Upload exactly one file using the 'file' form field.")
    return files[0][1]


def intake_store():
    engine = current_app.extensions['auth_engine']
    environment = current_app.config.get("INTAKE_ENVIRONMENT")
    if not isinstance(environment, str) or not environment.strip():
        raise OSError("Intake environment is not configured.")
    if engine.dialect.name != 'postgresql' and not current_app.testing:
        raise OSError("PostgreSQL must be configured for intake.")
    return PostgresIntakeStore(engine, organization_id=g.user["organizationId"], environment=environment)


def source_summary(snapshot):
    return {
        "sourceId": snapshot.source_id, "batchId": snapshot.batch_id,
        "filename": snapshot.source.filename, "environment": snapshot.source.environment,
        "format": snapshot.format, "sizeBytes": snapshot.size_bytes,
        "uploadedAt": snapshot.uploaded_at.isoformat(),
        "collections": [{"collectionId": item.collection_id, "name": item.name,
                         "rowCount": item.row_count, "warnings": list(item.warnings),
                         "headers": [asdict(header) for header in item.headers]}
                        for item in snapshot.collections],
    }


@bp.errorhandler(SQLAlchemyError)
def database_unavailable(error):
    return {"error": "Database unavailable or migrations not applied. Contact the administrator.",
            "code": "database_unavailable"}, 503


@bp.errorhandler(OSError)
def storage_unavailable(error):
    return {"error": "Intake storage unavailable. Contact the administrator.",
            "code": "storage_unavailable"}, 503


@bp.errorhandler(ImportStorageError)
def import_failed(error):
    if isinstance(error.__cause__, PublicationConflict):
        return {"error": "Another upload updated this source. Refresh the source list before retrying.",
                "code": "publication_conflict", "batchId": error.batch_id}, 409
    if error.phase == "publication":
        return {"error": "Import completion could not be confirmed. Refresh the source list before retrying.",
                "code": "publication_unknown", "batchId": error.batch_id}, 503
    return {"error": "Import could not be saved. Existing published data is unchanged.",
            "code": "import_failed", "batchId": error.batch_id}, 503


@bp.post("/uploads")
def import_upload():
    upload = uploaded_file()
    store = intake_store()
    snapshot = import_file(upload.filename, upload.stream,
                           organization_id=g.user["organizationId"],
                           environment=store.environment, writer=store)
    warnings = []
    try:
        store.sweep_snapshots(snapshot.source_id,
                             keep_previous=current_app.config.get('INTAKE_KEEP_PREVIOUS', 1),
                             grace_days=current_app.config.get('INTAKE_GRACE_DAYS', 7))
    except (SQLAlchemyError, ValueError):
        # Publication already committed. A maintenance failure must not claim the upload failed.
        current_app.logger.warning('Post-import snapshot cleanup failed; retry with intake-sweep.')
        warnings.append('Import saved. Snapshot cleanup is pending administrator maintenance.')
    return {"status": "imported", "persisted": True, "source": source_summary(snapshot), "warnings": warnings}, 201


@bp.get("")
def list_sources():
    return {"sources": [source_summary(snapshot) for snapshot in intake_store().list_sources()]}


@bp.errorhandler(IntakeNotFoundError)
def missing_source(error):
    return {'error': str(error)}, 404


@bp.errorhandler(PublicationConflict)
def stale_source(error):
    return {'error': str(error), 'code': 'publication_conflict'}, 409


@bp.get('/<source_id>/fields')
def source_fields(source_id):
    return intake_store().source_fields(source_id)


@bp.get('/<source_id>/mappings')
def source_mappings(source_id):
    return intake_store().list_mappings(source_id)


@bp.put('/<source_id>/mappings/<mapping_id>')
def save_mapping(source_id, mapping_id):
    request.max_content_length = 150_000
    data = request.get_json(silent=True)
    keys = {'expectedBatchId', 'collectionId', 'fieldIds', 'definition'}
    if not isinstance(data, dict) or set(data) != keys or not isinstance(data['expectedBatchId'], str) or not isinstance(data['collectionId'], str):
        return {'error': 'Supply expectedBatchId, collectionId, fieldIds and definition.'}, 400
    try:
        result = intake_store().save_mapping(source_id, mapping_id, expected_batch_id=data['expectedBatchId'],
            collection_id=data['collectionId'], field_ids=data['fieldIds'], definition=data['definition'])
    except ValueError as error:
        return {'error': str(error)}, 400
    return {'mapping': result}


@bp.delete('/<source_id>/mappings/<mapping_id>')
def delete_mapping(source_id, mapping_id):
    request.max_content_length = 4096
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'expectedBatchId'} or not isinstance(data['expectedBatchId'], str):
        return {'error': 'Supply expectedBatchId.'}, 400
    intake_store().delete_mapping(source_id, mapping_id, data['expectedBatchId'])
    return '', 204
