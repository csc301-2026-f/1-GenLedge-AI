"""Intake contract tests; opt-in PostgreSQL uses a disposable owned schema."""
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.migrations import upgrade_database
from app.sources.postgres_store import PostgresIntakeStore
from app.sources.writer import IntakeNotFoundError
from app.sources.service import import_file, ImportStorageError
from app.sources.writer import PublicationConflict


@pytest.fixture(params=['sqlite', 'postgresql'])
def engine(request):
    if request.param == 'sqlite':
        tmp_path = request.getfixturevalue('tmp_path')
        db = create_engine('sqlite:///' + (tmp_path / 'intake.sqlite3').as_posix())
        upgrade_database(db)
        yield db
        db.dispose()
        return
    if not os.environ.get('TEST_DATABASE_URL'):
        pytest.skip('Set TEST_DATABASE_URL to a developer-owned PostgreSQL database')
    url = make_url(os.environ['TEST_DATABASE_URL'])
    if not url.drivername.startswith('postgresql'):
        pytest.fail('TEST_DATABASE_URL must be PostgreSQL')
    sslmode = os.environ.get('DB_SSLMODE', 'require')
    if sslmode not in {'require', 'verify-ca', 'verify-full'}:
        pytest.fail('Use encrypted PostgreSQL for remote integration tests')
    args = dict(sslmode=sslmode, connect_timeout=5)
    if os.environ.get('DB_SSLROOTCERT'):
        args['sslrootcert'] = os.environ['DB_SSLROOTCERT']
    admin = create_engine(url, connect_args=args)
    schema = 'intake_test_' + uuid.uuid4().hex
    db = None
    created = False
    try:
        with admin.begin() as connection:
            owner = connection.execute(text("SELECT current_user = current_database(), "
                "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user), "
                "(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid())")).one()
            if not owner[0] or owner[1] or not owner[2]:
                pytest.fail('Use a non-superuser developer-owned database over TLS')
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        db = create_engine(url, connect_args=dict(args, options=f'-csearch_path={schema}'))
        upgrade_database(db)
        yield db
    finally:
        if db is not None:
            db.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def store(engine):
    return PostgresIntakeStore(engine, organization_id='org', environment='test')


def upload(store, data=b'[{"id":"001","nested":[true,null,{"n":1.5}]}]'):
    return import_file('data.json', io.BytesIO(data), organization_id=store.organization_id,
                       environment=store.environment, writer=store)


def sample(store, snapshot, **kwargs):
    return store.read_sample(snapshot.source_id, snapshot.batch_id, snapshot.collections[0].collection_id, **kwargs)


def staged_copy(store, original):
    staged = replace(original, batch_id=uuid.uuid4().hex)
    store.stage(staged)
    return staged


def test_migration_idempotent_preserves_existing_auth(engine, store):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    app_dir = Path(__file__).resolve().parents[1] / 'app'
    config = Config(str(app_dir / 'alembic.ini'))
    config.set_main_option('script_location', str(app_dir / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0001_auth_tables')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO auth_organizations (id,name) VALUES ('keep','Keep')"))
    upgrade_database(engine)
    saved = upload(store)
    upgrade_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM auth_organizations WHERE id='keep'")).scalar_one() == 'Keep'
        assert connection.execute(text('SELECT COUNT(*) FROM intake_records')).scalar_one() == 1
    assert store.active_snapshot(saved.source_id) == saved


def test_roundtrip_refresh_and_strict_scope(engine, store):
    original = upload(store)
    updated = upload(store, b'[{"id":"002"}]')
    reopened = PostgresIntakeStore(engine, organization_id='org', environment='test')
    assert reopened.list_sources() == [updated]
    assert original.source_id == updated.source_id
    assert original.collections[0].collection_id == updated.collections[0].collection_id
    assert sample(reopened, original) == [{'id': '001', 'nested': [True, None, {'n': 1.5}]}]
    assert sample(reopened, updated) == [{'id': '002'}]
    for org, env in [('foreign','test'), ('org','production')]:
        foreign = PostgresIntakeStore(engine, organization_id=org, environment=env)
        assert foreign.list_sources() == []
        with pytest.raises(IntakeNotFoundError):
            sample(foreign, original)
        with pytest.raises(PermissionError):
            foreign.stage(original)
    with pytest.raises(IntakeNotFoundError):
        store.published_snapshot('wrong-source', original.batch_id)


def test_json_preserves_values_not_supported_by_jsonb(store):
    data = b'[{"nul":"\\u0000","surrogate":"\\ud800","big":1e100,"zero":"001"}]'
    snapshot = upload(store, data)
    assert sample(store, snapshot) == [{'nul':'\x00', 'surrogate':'\ud800', 'big':1e100, 'zero':'001'}]


def test_sample_bounds_and_empty_collection(store):
    saved = upload(store, b'[' + b','.join(b'{"n":1}' for _ in range(501)) + b']')
    assert len(sample(store, saved)) == 500
    assert len(sample(store, saved, limit=3)) == 3
    for limit in (0, 501, True, 1.5, '3'):
        with pytest.raises(ValueError):
            sample(store, saved, limit=limit)
    empty = import_file('empty.csv', io.BytesIO(b'id\n'), organization_id='org', environment='test', writer=store)
    assert sample(store, empty) == []


def test_incomplete_and_failed_writes_are_not_visible(store):
    saved = upload(store)
    staged = staged_copy(store, saved)
    cid = staged.collections[0].collection_id
    with pytest.raises(ValueError):
        store.publish(staged.batch_id, saved.batch_id)
    with pytest.raises(IntakeNotFoundError):
        sample(store, staged)
    with pytest.raises(ValueError):
        store.write_collection(staged.batch_id, cid, [])
    with pytest.raises(ValueError):
        store.write_collection(staged.batch_id, cid, [{'n':float('nan')}])
    assert store.list_sources() == [saved]
    store.write_collection(staged.batch_id, cid, [{'valid': True}])
    with pytest.raises(ValueError):
        store.write_collection(staged.batch_id, cid, [{'valid': False}])
    store.publish(staged.batch_id, saved.batch_id)
    assert sample(store, staged) == [{'valid': True}]


def test_discard_tombstone_and_published_immutability(store):
    saved = upload(store)
    staged = staged_copy(store, saved)
    store.write_collection(staged.batch_id, staged.collections[0].collection_id, [{'n':2}])
    store.discard_unpublished(staged.batch_id)
    store.discard_unpublished(staged.batch_id)
    with pytest.raises(IntegrityError):
        store.stage(staged)
    unknown = replace(staged, batch_id='unknown')
    store.discard_unpublished(unknown.batch_id)
    with pytest.raises(IntegrityError):
        store.stage(unknown)
    with pytest.raises(ValueError):
        store.discard_unpublished(saved.batch_id)
    with pytest.raises(ValueError):
        store.write_collection(saved.batch_id, saved.collections[0].collection_id, [{'n':2}])
    assert sample(store, saved)[0]['id'] == '001'


def test_conflict_and_lost_ack_keep_published_data(store, monkeypatch):
    saved = upload(store)
    staged = staged_copy(store, saved)
    store.write_collection(staged.batch_id, staged.collections[0].collection_id, [{'n':2}])
    with pytest.raises(PublicationConflict):
        store.publish(staged.batch_id, None)
    publish = store.publish
    def lost_ack(*args):
        publish(*args)
        raise OSError('acknowledgement lost')
    monkeypatch.setattr(store, 'publish', lost_ack)
    with pytest.raises(ImportStorageError) as error:
        upload(store, b'[{"n":3}]')
    assert error.value.phase == 'publication'
    current = store.active_snapshot(saved.source_id)
    assert current.batch_id == error.value.batch_id
    assert sample(store, current) == [{'n':3}]
    assert sample(store, saved)[0]['id'] == '001'


def test_concurrent_first_publish_and_refresh(engine, store):
    if engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row-lock concurrency test')
    template = upload(store)
    # A distinct source has no active pointer; then repeat against its winner.
    from app.sources.metadata import SourceIdentity
    template = replace(template, source=SourceIdentity('org','test','fresh.json'))
    for expected in (None, 'winner'):
        if expected == 'winner':
            expected = store.active_snapshot(template.source_id).batch_id
        candidates = [staged_copy(store, template) for _ in range(2)]
        for candidate in candidates:
            store.write_collection(candidate.batch_id, candidate.collections[0].collection_id, [{'n':1}])
        barrier = Barrier(2)
        def publish(candidate):
            worker = PostgresIntakeStore(engine, organization_id='org', environment='test')
            barrier.wait(timeout=10)
            try:
                worker.publish(candidate.batch_id, expected)
                return 'published'
            except PublicationConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(publish, candidates)) == ['conflict','published']


def test_authenticated_http_import_uses_database(engine):
    from app import create_app
    from app.auth.models import Organization, User
    from sqlalchemy.orm import sessionmaker
    from werkzeug.security import generate_password_hash
    class Config:
        TESTING = True
        SECRET_KEY = 'intake-http-test'
        DATABASE_URL = 'sqlite://'
        SESSION_COOKIE_SECURE = False
        INTAKE_ENVIRONMENT = 'test'
    app = create_app(Config)
    app.extensions['auth_engine'].dispose()
    app.extensions['auth_engine'] = engine
    app.extensions['auth_database'] = sessionmaker(engine)
    with app.extensions['auth_database']() as db:
        db.add(Organization(id='http-org', name='HTTP Org'))
        db.flush()
        db.add(User(id='http-user', email='http@example.com', organization_id='http-org',
                    password_hash=generate_password_hash('test-password'), role='Analyst'))
        db.commit()
    client = app.test_client()
    csrf = client.get('/api/auth/csrf').json['csrfToken']
    assert client.post('/api/auth/login', json={'email':'http@example.com','password':'test-password'},
                       headers={'X-CSRF-Token':csrf}).status_code == 200
    csrf = client.get('/api/auth/csrf').json['csrfToken']
    response = client.post('/api/sources/uploads', headers={'X-CSRF-Token':csrf},
                           data={'file':(io.BytesIO(b'id\n001'), 'http.csv')})
    assert response.status_code == 201
    source = response.json['source']
    assert client.get('/api/sources').json['sources'] == [source]
    store = PostgresIntakeStore(engine, organization_id='http-org', environment='test')
    assert store.read_sample(source['sourceId'],source['batchId'],source['collections'][0]['collectionId']) == [{'id':'001'}]
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM intake_records')).scalar_one() == 1
    if engine.dialect.name == 'sqlite':
        app.testing = False
        assert client.get('/api/sources').status_code == 503


def test_late_serialization_failure_rolls_back_all_chunks(engine, store):
    saved = upload(store, b'[' + b','.join(b'{"n":1}' for _ in range(501)) + b']')
    staged = staged_copy(store, saved)
    with pytest.raises(ValueError):
        store.write_collection(staged.batch_id, staged.collections[0].collection_id,
                               [{'n':1}] * 500 + [{'n':float('inf')}])
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM intake_records WHERE batch_id=:batch'),
                                  {'batch':staged.batch_id}).scalar_one() == 0
    with pytest.raises(ValueError):
        store.publish(staged.batch_id, saved.batch_id)
    assert store.active_snapshot(saved.source_id) == saved
