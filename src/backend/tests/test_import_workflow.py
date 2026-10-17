"""Workflow contract tests. This fake is not a database or production adapter."""
import copy
import io
import re

import pytest
from openpyxl import Workbook

from app.sources.connectors.files import FileValidationError
from app.sources.service import ImportStorageError, import_file
from app.sources.writer import PublicationConflict


class FakeWriter:
    def __init__(self):
        self.active = {}
        self.manifests = {}
        self.data = {}
        self.completed = set()
        self.published = set()
        self.calls = []
        self.fail_collection = None
        self.fail_stage = False
        self.fail_cleanup = False
        self.publish_mode = None
        self.before_publish = None

    def active_snapshot(self, source_id):
        self.calls.append("read")
        batch_id = self.active.get(source_id)
        return self.manifests[batch_id] if batch_id else None

    def stage(self, snapshot):
        self.calls.append("stage")
        if snapshot.batch_id in self.manifests:
            raise ValueError("Duplicate batch")
        self.manifests[snapshot.batch_id] = snapshot
        if self.fail_stage:
            raise OSError("Manifest write acknowledgement failed")

    def write_collection(self, batch_id, collection_id, records):
        self.calls.append("write")
        manifest = self.manifests[batch_id]
        collection = next(c for c in manifest.collections if c.collection_id == collection_id)
        key = (batch_id, collection_id)
        if batch_id in self.published or key in self.completed:
            raise ValueError("Immutable completed data")
        if len(records) != collection.row_count:
            raise ValueError("Row count mismatch")
        if collection.name == self.fail_collection:
            self.data[key] = copy.deepcopy(records[:1])
            raise OSError("Partial write")
        self.data[key] = copy.deepcopy(records)
        self.completed.add(key)

    def publish(self, batch_id, expected_batch_id):
        self.calls.append("publish")
        if self.before_publish:
            callback, self.before_publish = self.before_publish, None
            callback()
        manifest = self.manifests[batch_id]
        if any((batch_id, c.collection_id) not in self.completed for c in manifest.collections):
            raise ValueError("Incomplete batch")
        if self.active.get(manifest.source_id) != expected_batch_id:
            raise PublicationConflict("Another import won")
        if self.publish_mode == "before":
            raise OSError("Publish unavailable")
        self.active[manifest.source_id] = batch_id
        self.published.add(batch_id)
        if self.publish_mode == "after":
            raise OSError("Publish acknowledgement lost")

    def discard_unpublished(self, batch_id):
        self.calls.append("discard")
        if batch_id in self.published:
            raise ValueError("Cannot discard published snapshot")
        if self.fail_cleanup:
            raise OSError("Cleanup unavailable")
        self.manifests.pop(batch_id, None)
        self.data = {key: value for key, value in self.data.items() if key[0] != batch_id}
        self.completed = {key for key in self.completed if key[0] != batch_id}


def run(writer, data=b"id\n1", filename="orders.csv", org="org-1", env="production"):
    return import_file(filename, io.BytesIO(data), organization_id=org,
                       environment=env, writer=writer)


def workbook(sheets):
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets:
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_success_metadata_and_refresh_preserve_identity():
    writer = FakeWriter()
    first = run(writer, b"name,name\nAda,Grace")
    assert writer.calls == ["read", "stage", "write", "publish"]
    collection = first.collections[0]
    assert collection.headers[1].original == "name"
    assert collection.headers[1].key == "name_2"
    assert collection.warnings
    assert first.uploaded_at.utcoffset().total_seconds() == 0
    assert first.format == "csv" and first.size_bytes == 19
    assert re.fullmatch(r"intake_[a-f0-9]{64}", collection.intake_name)
    second = run(writer, b"name,name\nAlan,Katherine")
    assert first.source_id == second.source_id
    assert first.collections[0].collection_id == second.collections[0].collection_id
    assert first.batch_id != second.batch_id
    assert collection.intake_name != second.collections[0].intake_name
    assert writer.active[first.source_id] == second.batch_id
    assert writer.data[first.batch_id, collection.collection_id] == [{"name": "Ada", "name_2": "Grace"}]
    assert first.batch_id in writer.published  # Old snapshot retained for readers.


def test_scope_and_exact_filename_identity():
    writer = FakeWriter()
    snapshots = [run(writer), run(writer, org="org-2"), run(writer, env="staging"),
                 run(writer, filename="Orders.csv")]
    assert len({s.source_id for s in snapshots}) == 4
    assert len({s.collections[0].intake_name for s in snapshots}) == 4
    assert run(writer, filename=r"C:\fakepath\orders.csv").source_id == snapshots[0].source_id


@pytest.mark.parametrize("org,env", [("", "production"), ("org", " ")])
def test_missing_scope_never_calls_storage(org, env):
    writer = FakeWriter()
    with pytest.raises(ValueError):
        run(writer, org=org, env=env)
    assert writer.calls == []


def test_nested_data_unchanged():
    writer = FakeWriter()
    result = run(writer, b'{"_id":{"$oid":"abc"},"items":[{"qty":2}]}', "orders.json")
    assert writer.data[result.batch_id, result.collections[0].collection_id] == [
        {"_id": {"$oid": "abc"}, "items": [{"qty": 2}]}]


def test_active_read_failure_does_not_write():
    class UnavailableWriter(FakeWriter):
        def active_snapshot(self, source_id):
            raise OSError("Storage unavailable")
    writer = UnavailableWriter()
    with pytest.raises(OSError, match="unavailable"):
        run(writer)
    assert writer.manifests == {} and writer.calls == []


def test_invalid_refresh_keeps_previous_snapshot():
    writer = FakeWriter()
    previous = run(writer)
    writer.calls.clear()
    with pytest.raises(FileValidationError):
        run(writer, b"id\n1,2")
    assert writer.calls == []
    assert writer.active[previous.source_id] == previous.batch_id


def test_later_invalid_sheet_never_calls_writer():
    writer = FakeWriter()
    data = workbook([("Good", [["id"], [1]]), ("Bad", [["id"], ["=1+1"]])])
    with pytest.raises(FileValidationError):
        run(writer, data, "orders.xlsx")
    assert writer.calls == []


def test_refresh_publishes_exact_manifest_including_removed_and_empty_sheets():
    writer = FakeWriter()
    first = run(writer, workbook([("Keep", [["id"], [1]]), ("Remove", [["id"], [2]])]), "a.xlsx")
    second = run(writer, workbook([("Keep", [["id"]]), ("New", [["id"], [3]])]), "a.xlsx")
    assert first.collections[0].collection_id == second.collections[0].collection_id
    assert [c.name for c in writer.active_snapshot(first.source_id).collections] == ["Keep", "New"]
    assert second.collections[0].row_count == 0
    assert len(writer.manifests[first.batch_id].collections) == 2


@pytest.mark.parametrize("existing", [False, True])
def test_partial_write_never_publishes(existing):
    writer = FakeWriter()
    data = workbook([("First", [["id"], [1]]), ("Second", [["id"], [2], [3]])])
    previous = run(writer, data, "a.xlsx") if existing else None
    before_active = dict(writer.active)
    writer.calls.clear()
    writer.fail_collection = "Second"
    with pytest.raises(ImportStorageError) as error:
        run(writer, data, "a.xlsx")
    assert error.value.phase == "staging"
    assert isinstance(error.value.__cause__, OSError)
    assert writer.active == before_active
    assert error.value.batch_id not in writer.manifests
    assert "publish" not in writer.calls
    if previous:
        assert previous.batch_id in writer.manifests


def test_manifest_failure_and_cleanup_failure_remain_unpublished():
    writer = FakeWriter()
    writer.fail_stage = writer.fail_cleanup = True
    with pytest.raises(ImportStorageError) as error:
        run(writer)
    assert error.value.cleanup_failed is True
    assert error.value.batch_id in writer.manifests
    assert writer.active == {}
    assert writer.calls == ["read", "stage", "discard"]


@pytest.mark.parametrize("mode", ["before", "after"])
def test_publication_failure_retains_batch_for_reconciliation(mode):
    writer = FakeWriter()
    old = run(writer)
    writer.publish_mode = mode
    writer.calls.clear()
    with pytest.raises(ImportStorageError) as error:
        run(writer, b"id\n2")
    batch_id = error.value.batch_id
    assert error.value.phase == "publication"
    assert batch_id in writer.manifests
    assert "discard" not in writer.calls
    assert writer.active[old.source_id] == (batch_id if mode == "after" else old.batch_id)


@pytest.mark.parametrize("existing", [False, True])
def test_concurrent_import_cannot_overwrite_winner(existing):
    writer = FakeWriter()
    if existing:
        run(writer)
    winner = []
    writer.before_publish = lambda: winner.append(run(writer, b"id\n3"))
    with pytest.raises(ImportStorageError) as error:
        run(writer, b"id\n2")
    assert isinstance(error.value.__cause__, PublicationConflict)
    assert writer.active[winner[0].source_id] == winner[0].batch_id
    assert error.value.batch_id not in writer.published


def test_fake_rejects_incomplete_publication_and_live_cleanup():
    writer = FakeWriter()
    live = run(writer)
    with pytest.raises(ValueError, match="published"):
        writer.discard_unpublished(live.batch_id)
    from dataclasses import replace
    staging = replace(live, batch_id="unpublished")
    writer.stage(staging)
    with pytest.raises(ValueError, match="Incomplete"):
        writer.publish(staging.batch_id, live.batch_id)
    assert writer.active[live.source_id] == live.batch_id
