"""Structural discovery checks using synthetic records."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.sources.discovery import discover_records


@pytest.fixture
def orders():
    return json.loads((Path(__file__).parent / "fixtures/us3/orders.json").read_text())


def fields(result):
    return {item.path: item for item in result.fields}


def test_discovers_nested_objects_and_repeating_elements(orders):
    result = discover_records(orders)
    found = fields(result)
    assert result.sampled_count == 3
    assert found["shipping_address"].types == ("object",)
    assert found["shipping_address.city"].types == ("string",)
    assert found["lines"].types == ("array",)
    assert found["lines"].repeating
    assert found["lines[]"].types == ("object",)
    assert found["lines[].sku"].types == ("string",)
    assert found["lines[].qty"].types == ("number",)
    assert found["lines[].sku"].repeating
    assert not found["shipping_address.city"].repeating
    assert found["tags[]"].types == ("string",)
    assert found["lines"].samples == ("[2 items]", "[1 items]", "[0 items]")


def test_observes_mixed_types_without_coercing_strings_or_dates(orders):
    found = fields(discover_records(orders))
    assert found["total"].types == ("null", "number", "string")
    assert found["total"].samples == (120.5, "99.00", None)
    assert found["paid"].types == ("boolean",)
    assert found["customer_code"].samples[0] == "00123"
    assert found["order_date"].types == ("string",)
    assert found["order_date"].samples[0] == "03/04/2026"


def test_missing_fields_and_explicit_null_are_nullable(orders):
    found = fields(discover_records(orders))
    assert found["total"].nullable
    assert found["shipping_address"].nullable
    assert found["shipping_address.city"].nullable
    assert found["shipping_address.zip"].nullable
    assert not found["order_no"].nullable


def test_missing_property_in_array_element_is_nullable():
    found = fields(discover_records([{"lines": [{"sku": "A"}, {}]}]))
    assert found["lines[].sku"].nullable
    assert not found["lines[]"].nullable


def test_caps_distinct_samples_and_string_length():
    records = [{"value": v} for v in ["a", "a", "b", "c", "d"]]
    assert fields(discover_records(records))["value"].samples == ("a", "b", "c")
    assert fields(discover_records([{"value": "x" * 200}]))["value"].samples == ("x" * 80,)


def test_boolean_and_number_samples_are_distinct():
    item = fields(discover_records([{"value": True}, {"value": 1}]))["value"]
    assert item.types == ("boolean", "number")
    assert len(item.samples) == 2
    assert type(item.samples[0]) is bool
    assert type(item.samples[1]) is int


def test_sampling_does_not_consume_the_501st_record():
    records = iter([{"early": i} for i in range(500)] + [{"late": "not sampled"}])
    result = discover_records(records)
    assert result.sampled_count == 500
    assert "late" not in fields(result)
    assert next(records) == {"late": "not sampled"}


def test_smaller_sample_limit():
    result = discover_records([{"a": 1}, {"later": 2}], sample_limit=1)
    assert result.sampled_count == 1
    assert tuple(fields(result)) == ("a",)


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_invalid_sample_limit(limit):
    with pytest.raises(ValueError, match="1.*500"):
        discover_records([], sample_limit=limit)


def test_empty_records_and_empty_containers():
    assert discover_records([]).fields == ()
    assert discover_records([]).sampled_count == 0
    found = fields(discover_records([{"object": {}, "array": [], "null": None}]))
    assert tuple(found) == ("array", "null", "object")
    assert found["null"].types == ("null",)
    assert found["null"].nullable
    assert found["object"].samples == ("{0 fields}",)
    assert "array[]" not in found


def test_literal_keys_do_not_collide_with_structural_paths():
    found = fields(discover_records([{
        "a.b": 1, "a": {"b": 2}, "lines[]": 3,
        "lines": [4], "": 5, "tags": {"[]": 6},
    }]))
    assert found['["a.b"]'].samples == (1,)
    assert found["a.b"].samples == (2,)
    assert found['["lines[]"]'].samples == (3,)
    assert not found['["lines[]"]'].repeating
    assert found["lines[]"].samples == (4,)
    assert found['[""]'].samples == (5,)
    assert found['tags["[]"]'].samples == (6,)


def test_nested_arrays_keep_their_structure():
    found = fields(discover_records([{"matrix": [[1, None], [2]]}]))
    assert found["matrix[][]"].types == ("null", "number")
    assert found["matrix[][]"].repeating
    assert found["matrix[][]"].nullable


def test_input_is_not_modified(orders):
    original = deepcopy(orders)
    discover_records(orders)
    assert orders == original


def test_result_is_deterministic_and_json_serializable(orders):
    result = discover_records(orders)
    assert result == discover_records(orders)
    payload = result.as_dict()
    assert payload["contractVersion"] == 1
    assert payload["samplingMethod"] == "head"
    assert payload["sampledCount"] == 3
    assert [f["path"] for f in payload["fields"]] == sorted(fields(result))
    assert json.loads(json.dumps(payload)) == payload
