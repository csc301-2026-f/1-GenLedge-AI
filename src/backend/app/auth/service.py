"""Credential validation and revocable sessions."""
import hashlib
import re
import secrets
import time
from functools import wraps

from flask import abort, current_app, g, session
from sqlalchemy import delete, select
from werkzeug.security import check_password_hash, generate_password_hash

from .models import LoginSession, User

DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def database():
    return current_app.extensions["auth_database"]()


def normalize_email(value):
    if not isinstance(value, str) or len(value) > 254:
        raise ValueError("A valid email is required.")
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("A valid email is required.")
    return email


def public_user(user):
    return {"id": user.id, "email": user.email, "role": user.role,
            "organizationId": user.organization_id}


def revoke_session():
    token = session.get("auth_token")
    if isinstance(token, str):
        with database() as db:
            db.execute(delete(LoginSession).where(
                LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
            db.commit()
    session.clear()


def authenticate(email, password, remember):
    with database() as db:
        user = db.scalar(select(User).where(User.email == email))
        valid = check_password_hash(user.password_hash if user else DUMMY_HASH, password)
        if not user or not valid or not user.active:
            return None
        result = public_user(user)
        user_id = user.id
    revoke_session()
    token = secrets.token_urlsafe(32)
    lifetime = 14 * 86400 if remember else 12 * 3600
    with database() as db:
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= int(time.time())))
        db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                            user_id=user_id, expires_at=int(time.time()) + lifetime))
        db.commit()
    session["auth_token"] = token
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = remember
    return result


def current_user():
    token = session.get("auth_token")
    if not isinstance(token, str):
        return None
    with database() as db:
        user = db.scalar(select(User).join(LoginSession).where(
            LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            LoginSession.expires_at > int(time.time()), User.active.is_(True)))
        return public_user(user) if user else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        g.user = current_user()
        if not g.user:
            return {"error": "Authentication required."}, 401
        return view(*args, **kwargs)
    return wrapped


def require_organization(organization_id):
    """Call after login_required for every organization-scoped resource."""
    if not getattr(g, "user", None):
        abort(401)
    if g.user["organizationId"] != organization_id:
        abort(403)
