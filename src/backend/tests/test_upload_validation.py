import io

import pytest

from app import create_app


@pytest.fixture
def client():
    class Config:
        TESTING = True
        SECRET_KEY = "upload-test"
    app = create_app(Config)
    return app.test_client()


def token(client):
    return {"X-CSRF-Token": client.get("/api/sources/uploads/csrf").json["csrfToken"]}


def login(client):
    assert client.post("/api/auth/login", json={"username": "test@example.com", "password": "password"}).status_code == 200


def upload(client, content=b"id\n1", filename="a.csv", headers=None):
    return client.post("/api/sources/uploads/validate", data={"file": (io.BytesIO(content), filename)}, headers=headers if headers is not None else token(client))


def test_requires_auth_and_csrf(client):
    assert client.get("/api/sources/uploads/csrf").status_code == 401
    assert upload(client, headers={}).status_code == 401
    login(client)
    assert upload(client, headers={}).status_code == 403
    assert upload(client, headers={"X-CSRF-Token": "invalid-é"}).status_code == 403


def test_upload_token_is_session_scoped_and_cleared_on_logout(client):
    login(client)
    previous = token(client)
    assert token(client) == previous
    assert upload(client, headers=previous).status_code == 200
    client.post("/api/auth/logout")
    assert upload(client, headers=previous).status_code == 401
    assert client.get("/api/sources/uploads/csrf").status_code == 401
    login(client)
    assert upload(client, headers=previous).status_code == 403
    assert token(client) != previous
    assert upload(client).status_code == 200


def test_success_summary_no_records_or_persistence(client):
    login(client)
    result = upload(client)
    assert result.status_code == 200
    assert result.json["persisted"] is False
    assert result.json["collections"][0]["rowCount"] == 1
    assert "records" not in result.json["collections"][0]
    assert result.headers["Cache-Control"] == "no-store"


def test_upload_contract_and_errors(client):
    login(client)
    assert client.post("/api/sources/uploads/validate", headers=token(client)).status_code == 400
    assert upload(client, b"id\n1,2").status_code == 422
    assert upload(client, filename="a.exe").status_code == 415
    response = client.post("/api/sources/uploads/validate", data={"file": [(io.BytesIO(b"id"), "a.csv"), (io.BytesIO(b"id"), "b.csv")]}, headers=token(client))
    assert response.status_code == 400


def test_upload_size_enforced(client):
    login(client)
    assert upload(client, b"x" * 25_000_001).status_code == 413
    assert upload(client, b"x" * 26_000_001).status_code == 413
