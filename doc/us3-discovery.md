# US3 — Source discovery

## Scope and entry point

`app.sources.discovery.discover_records(records, sample_limit=500)` performs structural discovery over parsed JSON-compatible records. It needs no Flask context, database, credentials, or LLM. It observes fields without converting values or modifying the input.

This module supplies the independent US3 discovery core. Source selection, authorized reading, persisted schema snapshots, re-sample endpoints, and frontend integration are separate work. It does not implement the full profiling/tool layer described in the harness architecture.

## Input

Pass an iterable of dictionaries containing JSON values: strings, numbers, booleans, nulls, objects, and arrays. The source parser/adapter is responsible for decoding and validating input and normalizing database-specific values into this contract.

US2's proposed `ParsedCollection.records` can be passed directly once that parser is integrated. The upload validation summary contains counts and headers, not the records required by discovery. Do not reimplement file parsing here.

`sample_limit` must be between 1 and 500. Discovery consumes only that many records; it does not read a 501st record to determine dataset size. A total row count must come from source metadata. Empty input produces zero sampled records and no observed fields; declared headers/types cannot be inferred from absent records.

## Output contract v1

The returned `DiscoveryResult` and `DiscoveredField` dataclasses are immutable. `result.as_dict()` returns a JSON-compatible payload:

```json
{
  "contractVersion": 1,
  "samplingMethod": "head",
  "sampledCount": 1,
  "fields": [
    {
      "path": "order_no",
      "types": ["string"],
      "nullable": false,
      "repeating": false,
      "samples": ["ORD-001"]
    }
  ]
}
```

Fields are sorted by canonical path, and types are sorted and deduplicated. Types are `null`, `boolean`, `number`, `string`, `object`, and `array`. Mixed values retain all observed types. Booleans are distinct from numbers. Numeric-looking identifiers and date strings stay strings, including leading zeros and ambiguous dates.

Each field has up to three distinct rendered sample values in first-observed order. Strings are capped at 80 characters; object/array samples are size summaries such as `{2 fields}` and `[3 items]`, not full records. Scalar sample values are not redacted by this module. The caller must apply organization access and the agreed redaction policy before sending results to a browser or LLM.

## Paths and field references

- Nested keys use dotted identifiers: `shipping_address.city`.
- Arrays have a container field and an element field: `lines`, `lines[]`, `lines[].sku`.
- Nested arrays use repeated markers: `matrix[][]`.
- Arrays and their descendants have `repeating=true`.
- Non-identifier keys use JSON-quoted brackets: a literal `a.b` key is `["a.b"]`, distinct from the nested path `a.b`. An empty key is `[""]`.

These paths are local field references, not globally assigned field IDs. The source/snapshot integration must scope them by stable collection identity and agree on the downstream field-ID contract. Do not derive identity from row position or sample values.

`nullable=true` means an explicit null was observed, the field was absent from at least one sampled record, or an object property was missing from at least one observed parent object (including objects in arrays). It is a conservative sample observation, not a required/optional database constraint or proof about unsampled records. Empty arrays contain no observed element field.

## Comparison contract v1

`compare_discoveries(previous, current)` compares two `DiscoveryResult` values for the same source collection. The caller supplies the collection/version scope; this function does not infer it or access a database.

It returns immutable `DiscoveryChanges` with `added_paths`, `missing_paths`, and `type_changes`. Paths and changes are sorted. `changes.as_dict()` returns:

```json
{
  "contractVersion": 1,
  "added": ["currency"],
  "missing": ["paid"],
  "typeChanges": [
    {
      "path": "total",
      "previousTypes": ["null", "number", "string"],
      "currentTypes": ["string"]
    }
  ]
}
```

This is a sample-to-sample comparison. `missing` means not observed in the current sample, not confirmed deletion from the full source. Types describe observed values, not a declared database schema. Changes in values, sample order, or nullable flags alone do not change canonical path identity or produce a type change. The function neither deletes field references nor changes mappings; persistence/review must preserve and display references to paths no longer observed.

## Integration handoff

The core receives records after authorized source reading. The integration must pin a source/collection/batch, attach the discovery result to a schema snapshot, and retain previous field references for existing mappings. An upload batch manifest and a discovery schema snapshot are different artifacts.

Before connecting the UI or AI harness, agree on the sample reader, stable global IDs, persistence/versioning, access/redaction policy, and error envelope. The module does not create alternate versions of teammates' source entities, auth helpers, or storage adapters.

## Verification

From `src/backend`, run:

```bash
.venv/bin/python -m pytest tests/test_discovery.py tests/test_discovery_changes.py -q
.venv/bin/python -m pytest tests -q
```

The fixtures `tests/fixtures/us3/orders.json` and `orders-refreshed.json` contain synthetic nested orders. Their comparison reports added `currency`, missing `paid`, and changed observed types for `total`. Tests cover mixed types, missing/null values, arrays, sampling bounds, bounded samples, literal punctuation in keys, input preservation, deterministic comparisons, and JSON serialization.
