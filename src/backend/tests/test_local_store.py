"""Regression checks for the concrete local intake adapter."""
import io
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app.sources.local_store import LocalIntakeStore
from app.sources.service import import_file


@pytest.fixture
def root(tmp_path):
    # Keep fixture cleanup independent of the Windows path fix being tested.
    path = Path("\\\\?\\" + str(tmp_path)) if os.name == "nt" else tmp_path
    yield path
    shutil.rmtree(path)


def store_at(root):
    return LocalIntakeStore(root, organization_id="test-org", environment="test")


def upload(store, data=b'[{"n":1}]'):
    return import_file("data.json", io.BytesIO(data), organization_id="test-org",
                       environment="test", writer=store)


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path regression")
def test_ordinary_windows_root_supports_long_record_paths(root):
    ordinary = Path(str(root).removeprefix("\\\\?\\"))
    store = store_at(ordinary)
    manifest = upload(store)
    cid = manifest.collections[0].collection_id
    assert len(str(store._collection_path(manifest.batch_id, cid))) > 260
    reopened = store_at(ordinary)
    assert reopened.read_sample(manifest.source_id, manifest.batch_id, cid) == [{"n": 1}]


def test_cleanup_prevents_restage_before_file_deletion(root, monkeypatch):
    store = store_at(root)
    published = upload(store)
    staged = replace(published, batch_id="discard-me")
    cid = staged.collections[0].collection_id
    store.stage(staged)
    store.write_collection(staged.batch_id, cid, [{"n": 2}])
    original = shutil.rmtree

    def concurrent_retry(path):
        # Run after cleanup's catalog transaction, before its filesystem deletion.
        with pytest.raises(ValueError, match="discarded"):
            store_at(root).stage(staged)
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", concurrent_retry)
        store.discard_unpublished(staged.batch_id)
    store.discard_unpublished(staged.batch_id)
    with pytest.raises(ValueError, match="discarded"):
        store_at(root).stage(staged)
    assert store.active_snapshot(published.source_id) == published
    assert store.read_sample(published.source_id, published.batch_id, cid) == [{"n": 1}]


def test_failed_cleanup_keeps_tombstone_and_can_be_retried(root, monkeypatch):
    store = store_at(root)
    staged = replace(upload(store), batch_id="interrupted")
    store.stage(staged)
    store.write_collection(staged.batch_id, staged.collections[0].collection_id, [{"n": 2}])
    with monkeypatch.context() as patch:
        def fail(path):
            raise PermissionError("busy file")
        patch.setattr(shutil, "rmtree", fail)
        with pytest.raises(PermissionError):
            store.discard_unpublished(staged.batch_id)
    reopened = store_at(root)
    with pytest.raises(ValueError, match="discarded"):
        reopened.stage(staged)
    reopened.discard_unpublished(staged.batch_id)
    assert not reopened._batch_path(staged.batch_id).exists()


def test_unknown_discard_reserves_id_but_published_discard_is_rejected(root):
    store = store_at(root)
    published = upload(store)
    unknown = replace(published, batch_id="not-staged-yet")
    store.discard_unpublished(unknown.batch_id)
    store.discard_unpublished(unknown.batch_id)
    with pytest.raises(ValueError, match="discarded"):
        store_at(root).stage(unknown)
    with pytest.raises(ValueError, match="published"):
        store.discard_unpublished(published.batch_id)
    assert store.read_sample(published.source_id, published.batch_id,
                             published.collections[0].collection_id) == [{"n": 1}]


def test_existing_catalog_gets_tombstone_table_without_losing_data(root):
    store = store_at(root)
    published = upload(store)
    # Model a catalog created by the previous version, before tombstones existed.
    with store._connection(write=True) as connection:
        connection.execute("DROP TABLE discarded_batches")
    reopened = store_at(root)
    assert reopened.active_snapshot(published.source_id) == published
    discarded = replace(published, batch_id="after-upgrade")
    reopened.stage(discarded)
    reopened.discard_unpublished(discarded.batch_id)
    with pytest.raises(ValueError, match="discarded"):
        reopened.stage(discarded)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_sample_rejects_nonfinite_numbers(root, number):
    store = store_at(root)
    manifest = upload(store)
    cid = manifest.collections[0].collection_id
    store._collection_path(manifest.batch_id, cid).write_text(
        '{"nested": [{"n": ' + number + '}]}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        store.read_sample(manifest.source_id, manifest.batch_id, cid)


def test_finite_nested_sample_and_old_batch_survive_refresh(root):
    store = store_at(root)
    manifest = upload(store, b'[{"n":1.25,"nested":[null,true,"001"]}]')
    upload(store)
    assert store.read_sample(manifest.source_id, manifest.batch_id,
                             manifest.collections[0].collection_id) == [
        {"n": 1.25, "nested": [None, True, "001"]}]
