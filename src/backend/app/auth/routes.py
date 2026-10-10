import secrets

from flask import Blueprint, g, request, session
from sqlalchemy.exc import SQLAlchemyError

from .service import authenticate, login_required, normalize_email, revoke_session

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.before_request
def protect_requests():
    request.max_content_length = 16 * 1024
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not isinstance(expected, str) or not secrets.compare_digest(expected.encode(), supplied.encode()):
            return {"error": "Invalid CSRF token. Refresh and try again."}, 403


@bp.after_request
def prevent_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(SQLAlchemyError)
def database_error(error):
    return {"error": "Authentication database unavailable. Contact the administrator."}, 503


@bp.get("/csrf")
def csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrfToken": session["csrf_token"]}


@bp.post("/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"error": "A JSON object is required."}, 400
    try:
        email = normalize_email(data.get("email"))
    except ValueError as error:
        return {"error": str(error)}, 400
    password = data.get("password")
    remember = data.get("rememberMe", False)
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return {"error": "Password is required (maximum 1024 characters)."}, 400
    if not isinstance(remember, bool):
        return {"error": "rememberMe must be a boolean."}, 400
    user = authenticate(email, password, remember)
    if user is None:
        return {"error": "Invalid email or password."}, 401
    return {"user": user}


@bp.get("/me")
@login_required
def me():
    return {"user": g.user}


@bp.post("/logout")
def logout():
    revoke_session()
    return "", 204
