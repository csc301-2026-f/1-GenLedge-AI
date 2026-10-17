"""Mapping preservation and retention against SQLite and disposable PostgreSQL."""
import io
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier

import pytest
import sqlalchemy as sa

from app.sources.postgres_store import PostgresIntakeStore, SnapshotExpiredError, batches, rows
from app.sources.mapping_store import fields
from app.sources.service import import_file, ImportStorageError
from app.sources.writer import PublicationConflict
from app.sources.writer import IntakeNotFoundError
from test_postgres_intake import engine, store
from test_upload_validation import client, login, token


def upload(store, content=b'id,name\n1,Alice', name='orders.csv'):
    return import_file(name, io.BytesIO(content), organization_id=store.organization_id,
                       environment=store.environment, writer=store)


def save(store, snapshot, path=['name'], mapping_id='name-map'):
    field = next(f for f in store.source_fields(snapshot.source_id)['fields'] if f['path'] == path)
    return store.save_mapping(snapshot.source_id, mapping_id, expected_batch_id=snapshot.batch_id,
        collection_id=field['collectionId'], field_ids=[field['fieldId']],
        definition={'target': 'customer_name', 'transform': {'operation': 'uppercase'}, 'humanNote': 'keep this'})


def test_mapping_survives_reorder_but_not_removed_or_changed_field(store):
    first = upload(store)
    original = save(store, first)
    second = upload(store, b'name,id\nBob,2')
    saved = store.list_mappings(first.source_id)['mappings'][0]
    assert saved['definition'] == original['definition']
    assert saved['status'] == 'valid' and saved['validBatchId'] == second.batch_id
    third = upload(store, b'id,other\n3,Cathy')
    saved = store.list_mappings(first.source_id)['mappings'][0]
    assert saved['status'] == 'needs_review' and saved['validBatchId'] == second.batch_id
    assert saved['checkedBatchId'] == third.batch_id and saved['definition'] == original['definition']
    with pytest.raises(PublicationConflict): save(store, first, path=['other'])
    assert store.list_mappings(first.source_id)['mappings'][0] == saved


def test_json_path_identity_arrays_literals_and_type_changes(store):
    first = upload(store, b'[{"a.b":"literal","a":{"b":2},"items":[{"sku":"001"}]}]', 'data.json')
    all_fields = store.source_fields(first.source_id)['fields']
    assert len({f['fieldId'] for f in all_fields}) == len(all_fields)
    assert {tuple(f['path']) for f in all_fields} >= {('a.b',), ('a', 'b'), ('items', None, 'sku')}
    original = save(store, first, ['a', 'b'])
    second = upload(store, b'[{"a":{"b":"two"}}]', 'data.json')
    saved = store.list_mappings(first.source_id)['mappings'][0]
    assert saved['status'] == 'needs_review' and saved['definition'] == original['definition']
    assert saved['validBatchId'] == first.batch_id and saved['checkedBatchId'] == second.batch_id


def test_ambiguous_headers_require_review(store):
    first = upload(store, b'id,id,\n1,2,3')
    assert all(not f['matchable'] for f in store.source_fields(first.source_id)['fields'])
    save(store, first, ['id'])
    upload(store, b'id,id,\n2,1,3')
    assert store.list_mappings(first.source_id)['mappings'][0]['status'] == 'needs_review'


def test_failed_import_and_failed_publication_leave_mappings_unchanged(store, monkeypatch):
    first = upload(store)
    original = save(store, first)
    with pytest.raises(Exception): upload(store, b'id,name\n1,2,3')
    import app.sources.postgres_store as module
    reconcile = module.reconcile
    def fail_after_reconcile(*args):
        reconcile(*args)
        raise RuntimeError('synthetic publication failure')
    monkeypatch.setattr(module, 'reconcile', fail_after_reconcile)
    with pytest.raises(ImportStorageError): upload(store, b'name,id\nBob,2')
    assert store.active_snapshot(first.source_id).batch_id == first.batch_id
    assert store.list_mappings(first.source_id)['mappings'] == [original]


def test_retention_age_previous_count_active_pins_and_receipts(store):
    first, second, third = upload(store), upload(store), upload(store)
    future = datetime.now(timezone.utc) + timedelta(days=8)
    assert store.sweep_snapshots(first.source_id) == []
    store.pin_snapshot(first.source_id, first.batch_id, 'job-1')
    assert store.sweep_snapshots(first.source_id, now=future) == []
    store.release_pin(first.batch_id, 'job-1')
    assert store.sweep_snapshots(first.source_id, now=future) == [first.batch_id]
    assert store.sweep_snapshots(first.source_id, now=future) == []
    assert store.published_snapshot(first.source_id, first.batch_id) == first
    with pytest.raises(SnapshotExpiredError): store.read_sample(first.source_id, first.batch_id, first.collections[0].collection_id)
    with pytest.raises(SnapshotExpiredError): store.pin_snapshot(first.source_id, first.batch_id, 'too-late')
    assert store.read_sample(second.source_id, second.batch_id, second.collections[0].collection_id)
    assert store.read_sample(third.source_id, third.batch_id, third.collections[0].collection_id)


def test_needs_review_mapping_protects_last_valid_batch_until_deleted(store):
    first = upload(store)
    save(store, first)
    second = upload(store, b'id,renamed\n1,Bob')
    assert store.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0) == []
    store.delete_mapping(first.source_id, 'name-map', second.batch_id)
    assert store.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0) == [first.batch_id]
    assert store.active_snapshot(first.source_id).batch_id == second.batch_id


def test_scope_and_membership_and_lazy_old_fields(store):
    first = upload(store)
    with store.engine.begin() as db:
        db.execute(fields.delete())  # Simulate a batch imported before this migration.
    save(store, first)
    for org, env in [('other', store.environment), (store.organization_id, 'other')]:
        other = PostgresIntakeStore(store.engine, organization_id=org, environment=env)
        with pytest.raises(IntakeNotFoundError): other.source_fields(first.source_id)
        with pytest.raises(IntakeNotFoundError): other.list_mappings(first.source_id)
        with pytest.raises(IntakeNotFoundError): other.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0)
        with pytest.raises(IntakeNotFoundError): other.pin_snapshot(first.source_id, first.batch_id, 'pin')
    with pytest.raises(ValueError):
        store.save_mapping(first.source_id, 'bad', expected_batch_id=first.batch_id, collection_id='other',
                           field_ids=['missing'], definition={'target': 'name'})


def test_sweep_skips_reader_lock_postgresql(store):
    if store.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locks are required')
    first = upload(store)
    upload(store)
    started, release = Event(), Event()
    def reader():
        with store.engine.begin() as db:
            db.execute(sa.select(batches).where(batches.c.batch_id == first.batch_id).with_for_update(read=True)).all()
            started.set()
            assert release.wait(10)
            return db.scalar(sa.select(sa.func.count()).select_from(rows).where(rows.c.batch_id == first.batch_id))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reader)
        try:
            assert started.wait(10)
            assert store.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0) == []
        finally:
            release.set()
        assert future.result() == 1
    assert store.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0) == [first.batch_id]


def test_publication_racing_cleanup_keeps_active_mapping_and_records(store):
    if store.engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locks are required')
    first = upload(store)
    save(store, first)
    upload(store)
    gate = Barrier(2)
    def publish():
        gate.wait(timeout=10)
        return upload(store, b'name,id\nNew,3')
    def sweep():
        gate.wait(timeout=10)
        return store.sweep_snapshots(first.source_id, keep_previous=0, grace_days=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        publish_result, sweep_result = pool.submit(publish), pool.submit(sweep)
        newest = publish_result.result(timeout=20)
        assert newest.batch_id not in sweep_result.result(timeout=20)
    assert store.active_snapshot(first.source_id).batch_id == newest.batch_id
    assert store.list_mappings(first.source_id)['mappings'][0]['validBatchId'] == newest.batch_id
    assert store.read_sample(newest.source_id, newest.batch_id, newest.collections[0].collection_id) == [{'name': 'New', 'id': '3'}]


def test_existing_data_migration_grace_and_lazy_fields(engine, store):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from app.migrations import upgrade_database
    first = upload(store)
    second = upload(store)
    app_dir = Path(__file__).resolve().parents[1] / 'app'
    config = Config(str(app_dir / 'alembic.ini'))
    config.set_main_option('script_location', str(app_dir / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0002_intake')
    upgrade_database(engine)
    assert store.active_snapshot(first.source_id) == second
    assert store.read_sample(first.source_id, first.batch_id, first.collections[0].collection_id)
    assert store.sweep_snapshots(first.source_id) == []
    assert save(store, second)['status'] == 'valid'


def test_http_mapping_api_and_post_import_sweep(client):
    login(client)
    client.application.config.update(INTAKE_KEEP_PREVIOUS=0, INTAKE_GRACE_DAYS=0)
    def post(content):
        result = client.post('/api/sources/uploads', data={'file': (io.BytesIO(content), 'orders.csv')}, headers=token(client))
        assert result.status_code == 201, result.json
        return result.json['source']
    first = post(b'id,name\n1,Alice')
    base = '/api/sources/' + first['sourceId']
    field = next(f for f in client.get(base + '/fields').json['fields'] if f['path'] == ['name'])
    body = dict(expectedBatchId=first['batchId'], collectionId=field['collectionId'], fieldIds=[field['fieldId']], definition={'target': 'customer'})
    assert client.put(base + '/mappings/name', json=body).status_code == 403
    assert client.put(base + '/mappings/name', json=body, headers=token(client)).status_code == 200
    second = post(b'name,id\nBob,2')
    assert client.get(base + '/mappings').json['mappings'][0]['validBatchId'] == second['batchId']
    assert client.put(base + '/mappings/name', json=body, headers=token(client)).status_code == 409
    with client.application.extensions['auth_engine'].connect() as db:
        assert db.scalar(sa.select(batches.c.purged).where(batches.c.batch_id == first['batchId'])) is True
    assert client.delete(base + '/mappings/name', json={'expectedBatchId': second['batchId']}).status_code == 403
    assert client.delete(base + '/mappings/name', json={'expectedBatchId': second['batchId']}, headers=token(client)).status_code == 204
    assert client.get(base + '/mappings').json['mappings'] == []
    client.application.config['INTAKE_ENVIRONMENT'] = 'other'
    assert client.get(base + '/mappings').status_code == 404


def test_cleanup_failure_does_not_report_import_failure(client, monkeypatch):
    login(client)
    from sqlalchemy.exc import OperationalError
    def fail(*args, **kwargs):
        raise OperationalError('synthetic', {}, Exception('cleanup unavailable'))
    monkeypatch.setattr(PostgresIntakeStore, 'sweep_snapshots', fail)
    result = client.post('/api/sources/uploads', data={'file': (io.BytesIO(b'id\n1'), 'a.csv')}, headers=token(client))
    assert result.status_code == 201 and result.json['persisted'] is True
    assert result.json['warnings']
    assert client.get('/api/sources').json['sources'][0]['batchId'] == result.json['source']['batchId']


def test_scoped_maintenance_command(client):
    login(client)
    client.application.config.update(INTAKE_KEEP_PREVIOUS=0, INTAKE_GRACE_DAYS=0)
    store = PostgresIntakeStore(client.application.extensions['auth_engine'], organization_id='upload-org', environment='test')
    first = upload(store)
    upload(store)
    runner = client.application.test_cli_runner()
    wrong = runner.invoke(args=['intake-sweep', '--organization', 'other', '--source', first.source_id])
    assert wrong.exit_code != 0
    result = runner.invoke(args=['intake-sweep', '--organization', 'upload-org', '--source', first.source_id])
    assert result.exit_code == 0 and 'Swept 1' in result.output
    with pytest.raises(SnapshotExpiredError): store.read_sample(first.source_id, first.batch_id, first.collections[0].collection_id)
