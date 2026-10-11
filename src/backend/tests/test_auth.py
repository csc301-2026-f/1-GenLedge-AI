import time

import pytest
from flask import g
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from app import create_app
from app.auth.models import Base, LoginSession, Organization, User
from app.auth.service import login_required, require_organization


@pytest.fixture
def app(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        DATABASE_URL = "sqlite:///" + str(tmp_path / "auth.sqlite3").replace("\\", "/")
        SESSION_COOKIE_SECURE = False
    app = create_app(TestConfig)
    Base.metadata.create_all(app.extensions["auth_engine"])
    with app.extensions["auth_database"]() as db:
        db.add(Organization(id="org-1", name="Acme"))
        db.flush()
        db.add(User(id="user-1", email="analyst@example.com",
                    password_hash=generate_password_hash("correct-password"),
                    organization_id="org-1", role="Analyst"))
        db.commit()

    @app.get("/protected/<organization_id>")
    @login_required
    def protected(organization_id):
        require_organization(organization_id)
        return {"user": g.user}

    yield app
    app.extensions["auth_engine"].dispose()


def post(client, path, data=None):
    token = client.get("/api/auth/csrf").json["csrfToken"]
    return client.post("/api/auth/" + path, json=data or {}, headers={"X-CSRF-Token": token})


def sign_in(client, remember=False):
    return post(client, "login", {"email": " Analyst@Example.com ",
                                "password": "correct-password", "rememberMe": remember})


def test_login_restore_and_revoked_cookie(app):
    client = app.test_client()
    assert client.get("/api/auth/me").status_code == 401
    response = sign_in(client)
    assert response.status_code == 200
    assert response.json["user"]["role"] == "Analyst"
    assert "password_hash" not in response.json["user"]
    cookie = client.get_cookie("session").value
    assert "Expires=" not in response.headers["Set-Cookie"]
    restored = app.test_client()
    restored.set_cookie("session", cookie)
    assert restored.get("/api/auth/me").status_code == 200
    assert post(client, "logout").status_code == 204
    assert restored.get("/api/auth/me").status_code == 401


def test_remember_cookie_and_organization_access(app):
    client = app.test_client()
    response = sign_in(client, True)
    assert "Expires=" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert client.get("/protected/org-1").status_code == 200
    assert client.get("/protected/org-2").status_code == 403


def test_invalid_credentials_csrf_and_inputs(app):
    client = app.test_client()
    assert client.post("/api/auth/login", json={}).status_code == 403
    assert client.post("/api/auth/login", json={}, headers={"X-CSRF-Token": "invalid-é"}).status_code == 403
    assert post(client, "login").status_code == 400
    assert post(client, "login", {"email": "analyst@example.com", "password": "wrong"}).status_code == 401
    assert post(client, "login", {"email": "missing@example.com", "password": "wrong"}).status_code == 401
    assert post(client, "login", {"email": "analyst@example.com", "password": "correct-password", "rememberMe": "false"}).status_code == 400
    assert post(client, "login", {"email": "analyst@example.com", "password": "x" * 20000}).status_code == 413
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("disable", [False, True])
def test_expired_or_disabled_sessions(app, disable):
    client = app.test_client()
    sign_in(client)
    with app.extensions["auth_database"]() as db:
        if disable:
            db.get(User, "user-1").active = False
        else:
            db.scalar(select(LoginSession)).expires_at = int(time.time()) - 1
        db.commit()
    assert client.get("/api/auth/me").status_code == 401
    if disable:
        assert sign_in(client).status_code == 401


def test_login_rotates_csrf_and_revokes_previous_session(app):
    client = app.test_client()
    sign_in(client)
    previous = client.get_cookie("session").value
    old_csrf = client.get("/api/auth/csrf").json["csrfToken"]
    sign_in(client)
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": old_csrf}).status_code == 403
    replay = app.test_client()
    replay.set_cookie("session", previous)
    assert replay.get("/api/auth/me").status_code == 401


def test_cli_provisioning(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["auth-init-db"]).exit_code == 0
    args = ["auth-create-user", "--email", "new@example.com", "--organization", "New Org"]
    result = runner.invoke(args=args, input="a-long-password\na-long-password\n")
    assert result.exit_code == 0
    assert runner.invoke(args=args, input="a-long-password\na-long-password\n").exit_code != 0
    client = app.test_client()
    assert post(client, "login", {"email": "new@example.com", "password": "a-long-password"}).status_code == 200


def test_database_failure_returns_actionable_response(app):
    Base.metadata.drop_all(app.extensions["auth_engine"])
    client = app.test_client()
    assert sign_in(client).status_code == 503


def test_production_requires_configuration():
    class MissingSecret:
        AUTH_ENV = "production"
        SECRET_KEY = None
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(MissingSecret)

    class MissingDatabase:
        AUTH_ENV = "production"
        SECRET_KEY = "test-secret"
        DATABASE_URL = None
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(MissingDatabase)
