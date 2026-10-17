import io

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.auth.models import Organization, User


@pytest.fixture
def client(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "upload-test"
        DATABASE_URL = "sqlite:///" + str(tmp_path / "auth.sqlite3").replace("\\", "/")
        SESSION_COOKIE_SECURE = False
        INTAKE_ENVIRONMENT = "test"
    app = create_app(Config)
    assert app.test_cli_runner().invoke(args=["auth-init-db"]).exit_code == 0
    with app.extensions["auth_database"]() as db:
        db.add(Organization(id="upload-org", name="Upload tests"))
        db.flush()
        db.add(User(id="upload-user", email="test@example.com",
                    password_hash=generate_password_hash("password"),
                    organization_id="upload-org", role="Analyst"))
        db.commit()
    yield app.test_client()
    app.extensions["auth_engine"].dispose()


def token(client):
    return {"X-CSRF-Token": client.get("/api/auth/csrf").json["csrfToken"]}


def login(client):
    csrf = client.get("/api/auth/csrf").json["csrfToken"]
    assert client.post("/api/auth/login", json={"email": "test@example.com", "password": "password"}, headers={"X-CSRF-Token": csrf}).status_code == 200


def save(client, content=b"id\n1", filename="a.csv", headers=None, extra=None):
    return client.post("/api/sources/uploads",
                       data={"file": (io.BytesIO(content), filename), **(extra or {})},
                       headers=headers if headers is not None else token(client))


def test_requires_auth_and_csrf(client):
    assert save(client, headers={}).status_code == 401
    login(client)
    assert save(client, headers={}).status_code == 403
    assert save(client, headers={"X-CSRF-Token": "invalid-é"}).status_code == 403


def test_upload_token_is_session_scoped_and_cleared_on_logout(client):
    login(client)
    previous = token(client)
    assert token(client) == previous
    assert previous["X-CSRF-Token"] == client.get("/api/auth/csrf").json["csrfToken"]
    assert save(client, headers=previous).status_code == 201
    assert client.post("/api/auth/logout", headers=previous).status_code == 204
    assert save(client, headers=previous).status_code == 401
    login(client)
    assert save(client, headers=previous).status_code == 403
    assert token(client) != previous
    assert save(client).status_code == 201


def test_success_summary_without_records(client):
    login(client)
    result = save(client)
    assert result.status_code == 201
    assert result.json["persisted"] is True
    assert result.json["source"]["collections"][0]["rowCount"] == 1
    assert "records" not in result.json["source"]["collections"][0]
    assert result.headers["Cache-Control"] == "no-store"


def test_upload_contract_and_errors(client):
    login(client)
    assert client.post("/api/sources/uploads", headers=token(client)).status_code == 400
    assert save(client, b"id\n1,2").status_code == 422
    assert save(client, filename="a.exe").status_code == 415
    response = client.post("/api/sources/uploads", data={"file": [(io.BytesIO(b"id"), "a.csv"), (io.BytesIO(b"id"), "b.csv")]}, headers=token(client))
    assert response.status_code == 400


def test_upload_size_enforced(client):
    login(client)
    assert save(client, b"x" * 25_000_001).status_code == 413
    assert save(client, b"x" * 26_000_001).status_code == 413


def test_import_list_refresh_and_pinned_sample(client):
    from types import SimpleNamespace
    from app.sources.postgres_store import PostgresIntakeStore
    login(client)
    assert client.get('/api/sources').json == {'sources': []}
    first = save(client)
    assert first.status_code == 201
    assert first.json['persisted'] is True
    old = first.json['source']
    assert 'records' not in old['collections'][0]
    assert save(client, b'id\n1,2').status_code == 422
    assert client.get('/api/sources').json['sources'] == [old]
    new = save(client, b'id\n2\n3').json['source']
    assert new['sourceId'] == old['sourceId']
    assert new['batchId'] != old['batchId']
    assert new['collections'][0]['collectionId'] == old['collections'][0]['collectionId']
    assert client.get('/api/sources').json['sources'] == [new]
    store = PostgresIntakeStore(client.application.extensions['auth_engine'],
                            organization_id='upload-org', environment='test')
    assert store.read_sample(old['sourceId'], old['batchId'], old['collections'][0]['collectionId']) == [{'id': '1'}]
    assert store.read_sample(new['sourceId'], new['batchId'], new['collections'][0]['collectionId']) == [{'id': '2'}, {'id': '3'}]
    app = create_app(SimpleNamespace(**dict(client.application.config)))
    try:
        reopened = app.test_client()
        reopened.set_cookie('session', client.get_cookie('session').value)
        assert reopened.get('/api/sources').json['sources'] == [new]
    finally:
        app.extensions['auth_engine'].dispose()


def test_import_authorization_scope_and_revocation(client):
    assert client.get('/api/sources').status_code == 401
    assert client.post('/api/sources/uploads').status_code == 401
    login(client)
    assert client.post('/api/sources/uploads').status_code == 403
    original = save(client, extra={'organizationId': 'other', 'environment': 'production'}).json['source']
    assert original['environment'] == 'test'
    with client.application.extensions['auth_database']() as db:
        db.add(Organization(id='other', name='Other'))
        db.flush()
        db.add(User(id='other-user', email='other@example.com', password_hash=generate_password_hash('password'),
                    organization_id='other', role='Analyst'))
        db.commit()
    other = client.application.test_client()
    csrf = other.get('/api/auth/csrf').json['csrfToken']
    assert other.post('/api/auth/login', json={'email': 'other@example.com', 'password': 'password'},
                      headers={'X-CSRF-Token': csrf}).status_code == 200
    assert other.get('/api/sources').json['sources'] == []
    foreign = save(other).json['source']
    assert foreign['sourceId'] != original['sourceId']
    assert client.get('/api/sources').json['sources'] == [original]
    cookie = client.get_cookie('session').value
    assert client.post('/api/auth/logout', headers=token(client)).status_code == 204
    client.set_cookie('session', cookie)
    assert client.get('/api/sources').status_code == 401


def test_import_validation_and_disabled_storage(client):
    login(client)
    assert client.post('/api/sources/uploads', headers=token(client)).status_code == 400
    assert save(client, filename='bad.exe').status_code == 415
    assert save(client, b'x' * 25_000_001).status_code == 413
    client.application.config['INTAKE_ENVIRONMENT'] = ''
    assert save(client).status_code == 503
    assert client.get('/api/sources').status_code == 503


def test_import_storage_failure_preserves_old_source(client, monkeypatch):
    from app.sources.postgres_store import PostgresIntakeStore
    from app.sources.writer import PublicationConflict
    login(client)
    original = save(client).json['source']
    def fail(*args):
        raise OSError('private path or secret must not be echoed')
    with monkeypatch.context() as patch:
        patch.setattr(PostgresIntakeStore, 'write_collection', fail)
        response = save(client, b'id\n2')
        assert response.status_code == 503
        assert response.json['code'] == 'import_failed'
        assert 'private' not in response.get_data(as_text=True)
    assert client.get('/api/sources').json['sources'] == [original]
    def conflict(*args):
        raise PublicationConflict('conflict')
    with monkeypatch.context() as patch:
        patch.setattr(PostgresIntakeStore, 'publish', conflict)
        assert save(client).status_code == 409
    assert client.get('/api/sources').json['sources'] == [original]
    publish = PostgresIntakeStore.publish
    def lost_ack(self, *args):
        publish(self, *args)
        raise OSError('ack lost')
    with monkeypatch.context() as patch:
        patch.setattr(PostgresIntakeStore, 'publish', lost_ack)
        response = save(client, b'id\n3')
        assert response.status_code == 503
        assert response.json['code'] == 'publication_unknown'
    assert client.get('/api/sources').json['sources'][0]['batchId'] == response.json['batchId']
