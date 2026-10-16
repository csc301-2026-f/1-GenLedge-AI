"""Compare observed schemas without changing source data or mappings."""

import json
from pathlib import Path

from app.sources.discovery import compare_discoveries, discover_records


def test_reports_added_missing_and_changed_nested_fields():
    previous = discover_records([{
        "order_no": "A", "total": 5, "legacy": "old", "lines": [{"qty": 2}],
    }])
    current = discover_records([{
        "order_no": "B", "total": "5", "discount": 1,
        "lines": [{"qty": "2", "sku": "B"}],
    }])
    changes = compare_discoveries(previous, current)
    assert changes.added_paths == ("discount", "lines[].sku")
    assert changes.missing_paths == ("legacy",)
    assert tuple(change.path for change in changes.type_changes) == ("lines[].qty", "total")
    assert changes.type_changes[0].previous_types == ("number",)
    assert changes.type_changes[0].current_types == ("string",)


def test_unchanged_result_has_no_changes():
    result = discover_records([{"id": "001", "nested": {"value": 1}}])
    changes = compare_discoveries(result, result)
    assert changes.added_paths == ()
    assert changes.missing_paths == ()
    assert changes.type_changes == ()


def test_sample_value_and_missing_observations_do_not_change_field_identity():
    previous = discover_records([{"id": "001", "optional": "old"}])
    current = discover_records([{"id": "002", "optional": "new"}, {"id": "003"}])
    changes = compare_discoveries(previous, current)
    assert current.fields[1].nullable
    assert changes.added_paths == changes.missing_paths == ()
    assert changes.type_changes == ()


def test_missing_from_small_sample_is_reported_without_claiming_deletion():
    previous = discover_records([{"a": 1, "late": 2}])
    current = discover_records([{"a": 1}, {"a": 1, "late": 2}], sample_limit=1)
    changes = compare_discoveries(previous, current)
    assert changes.missing_paths == ("late",)
    assert "removed" not in changes.as_dict()


def test_mixed_type_order_does_not_report_false_changes():
    previous = discover_records([{"value": 1}, {"value": "1"}])
    current = discover_records([{"value": "2"}, {"value": 2}])
    assert compare_discoveries(previous, current).type_changes == ()


def test_empty_samples_report_observed_paths_only():
    empty = discover_records([])
    populated = discover_records([{"a": 1, "b": {"c": 2}}])
    assert compare_discoveries(empty, populated).added_paths == ("a", "b", "b.c")
    assert compare_discoveries(populated, empty).missing_paths == ("a", "b", "b.c")


def test_literal_dot_key_and_nested_key_remain_distinct():
    previous = discover_records([{"a.b": 1, "a": {"b": 1}}])
    current = discover_records([{"a.b": 2, "a": {"b": "2"}}])
    changes = compare_discoveries(previous, current)
    assert tuple(change.path for change in changes.type_changes) == ("a.b",)


def test_comparison_does_not_modify_discoveries():
    previous = discover_records([{"old": [1, 2]}])
    current = discover_records([{"new": "value"}])
    before, after = previous.as_dict(), current.as_dict()
    compare_discoveries(previous, current)
    assert previous.as_dict() == before
    assert current.as_dict() == after


def test_change_payload_is_json_serializable():
    previous = discover_records([{"value": 1}])
    current = discover_records([{"value": "1", "added": True}])
    payload = compare_discoveries(previous, current).as_dict()
    assert payload == {
        "contractVersion": 1,
        "added": ["added"],
        "missing": [],
        "typeChanges": [{
            "path": "value", "previousTypes": ["number"], "currentTypes": ["string"],
        }],
    }
    assert json.loads(json.dumps(payload)) == payload


def test_synthetic_refresh_handoff():
    fixtures = Path(__file__).parent / "fixtures/us3"
    previous = discover_records(json.loads((fixtures / "orders.json").read_text()))
    current = discover_records(json.loads((fixtures / "orders-refreshed.json").read_text()))
    assert compare_discoveries(previous, current).as_dict() == {
        "contractVersion": 1,
        "added": ["currency"],
        "missing": ["paid"],
        "typeChanges": [{
            "path": "total", "previousTypes": ["null", "number", "string"],
            "currentTypes": ["string"],
        }],
    }
