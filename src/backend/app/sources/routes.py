"""Validation only: no intake writes or source metadata persistence."""
import secrets

from flask import Blueprint, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from .connectors.files import MAX_FILE_BYTES, FileValidationError, parse_file

bp = Blueprint("sources", __name__, url_prefix="/api/sources")


@bp.before_request
def protect_upload():
    # Multipart framing is additional to the independently enforced file limit.
    request.max_content_length = MAX_FILE_BYTES + 1_000_000
    request.max_form_parts = 10
    # Match main's demo session contract. Replace this boundary with the shared
    # auth helper when real authentication lands; parsers remain independent.
    if not session.get("user"):
        return {"error": "Authentication required."}, 401
    if request.method == "POST":
        expected = session.get("sources_csrf_token")
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
    return {"error": "Upload request is too large. Maximum file size is 25 MB.", "code": "file_too_large"}, 413


@bp.errorhandler(BadRequest)
def invalid_request(error):
    return {"error": "Invalid multipart upload request."}, 400


@bp.get("/uploads/csrf")
def upload_csrf():
    if "sources_csrf_token" not in session:
        session["sources_csrf_token"] = secrets.token_urlsafe(32)
    return {"csrfToken": session["sources_csrf_token"]}


@bp.post("/uploads/validate")
def validate_upload():
    files = list(request.files.items(multi=True))
    if len(files) != 1 or files[0][0] != "file" or not files[0][1].filename:
        return {"error": "Upload exactly one file using the 'file' form field."}, 400
    upload = files[0][1]
    return parse_file(upload.filename, upload.stream).summary()
