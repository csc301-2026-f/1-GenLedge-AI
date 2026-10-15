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

## Frontend presentation

The connected App now uses DiscoveryContainer to load a saved snapshot by ID from the authenticated API. It shows idle/loading/error/ready states, selects resources returned by that snapshot, clears stale results when the ID changes, cancels replaced/unmounted requests and bounds requests to 15 seconds. Reload snapshot re-reads the same immutable artifact; it does not sample a source or publish a new snapshot.

DiscoverScreen remains presentation-only. Its caller supplies sourceName, collectionName, a controlled DiscoveryState, and optional refresh/advance callbacks. The display model is separate from both raw DiscoveryResult and shared InventoryView: discoveryView renders raw samples as JSON literals; snapshotView displays canonical saved types and already prepared sample strings without quoting them twice. Native type evidence is shown separately, not parsed into invented raw types. Saved status is displayed as stored. Filters use the types/statuses present in the selected resource.

Raw previews can show sampledCount. Saved InventoryView has no sample count/method, so its screen explicitly says they were not recorded. No total record count is invented. A resource with zero fields displays an empty-resource message; changing snapshot/resource resets filters. An error never leaves the previous snapshot's fields visible.

DiscoveryPreview remains an isolated synthetic component using generated core payloads and initial/refreshed/empty/loading/error modes. It is no longer the connected App's default discovery host. The preserved standalone Frontend Demo is unchanged.

Routing remains disconnected in this step: the live view's action is disabled rather than navigating to the still-mocked routing screen. The later job integration must pass the displayed persisted snapshot ID to the mapping job API.

## Shared inventory adapter

`app.sources.inventory_adapter.to_inventory` adapts one `DiscoveryResult` to the existing `app.agent.contracts.InventoryView`. It does not introduce another inventory schema. The frozen shared-contract commit is retained as a dependency of this branch; it is also used by the US4 workstreams.

```python
from app.sources.discovery import discover_records
from app.sources.inventory_adapter import to_inventory

result = discover_records([{"order_no": "001", "total": 12.5}])
inventory = to_inventory(
    result,
    snapshot_id="snapshot-orders-1",
    source_id="source-orders-1",
    resource_id="orders",
    resource_name="Orders",
    resource_kind="collection",
)
print(inventory.model_dump_json(indent=2))
```

The caller supplies all identities and resource metadata. One report becomes one resource; all canonical paths and their nullable/repeating flags are preserved, including parent objects, array containers/elements and quoted literal-key paths. This adapter does not extract nested arrays into independent resources or rename fields. If US4 needs `orders.lines[]` with a relative `sku`, the caller must discover that explicitly scoped resource rather than relabel the full orders result. Downstream mapping/tool identifier restrictions still need integration review for literal-key and non-ASCII paths.

| Structural observations | Inventory type |
| --- | --- |
| string, optionally with null | text |
| number, optionally with null | number |
| boolean, optionally with null | boolean |
| object or array, optionally with null | json |
| multiple non-null types | json |
| null only | json |

`json` for mixed/null-only observations is a conservative projection, not a conversion of source values or a claim about a warehouse target type. `native_type` records the complete observed structural type set as `observed:null|number|string`, distinguishing observation from a connector's declared native type. Every field starts with status `unknown`; this adapter has no prior snapshot with which to establish `stable` or `new`. Description remains unset. Existing date ambiguity evidence is copied from discovery into InventoryField.ambiguity; the adapter does not infer it from rendered samples or choose a format. Dates and leading-zero identifiers stay structural strings.

The shared contract requires string samples. Each existing bounded scalar sample is JSON-rendered into a string: the source string `001` becomes the display string `"001"`, boolean true becomes `true`, and actual null becomes `null`. This keeps a source string such as `"null"` distinguishable from actual null. Object/array samples remain the core's size-summary strings. The original report is not modified.

`InventoryView` does not contain `sampledCount` or `samplingMethod`; the caller must retain the original report alongside the inventory if those observations need to be displayed or persisted. Do not manufacture total record counts from the sample. The adapter does not redact samples, authorize access, assign IDs, save snapshots, or call HTTP/model/connector services. Apply the agreed access/redaction policy before exposing the result. Construction uses the shared Pydantic models and their existing validation rules.

## Date ambiguity evidence

Discovery inspects every string value in the bounded sample for one/two-digit slash-separated day/month values followed by a four-digit year. Surrounding whitespace is ignored only for detection; the original sample value is retained. A marker is set only when both DD/MM/YYYY and MM/DD/YYYY are valid Gregorian dates and represent different dates. For example, 03/04/2026 is flagged; 13/04/2026, 04/04/2026, invalid dates and year-first ISO text are not flagged.

Flagged DiscoveredField values carry ambiguity equal to date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY. The raw contract-v1 field JSON adds this optional property only when flagged; unflagged fields omit it. The shared InventoryField contract is unchanged and receives the same marker. Structural types and all source/sample values remain unchanged: detecting an ambiguous date never promotes text to date or applies a transformation.

Detection runs over all observed strings within the existing first-N record limit, even after the three display samples have been collected. An ambiguity can therefore be reported even when its triggering value is not among the displayed samples. Values in record 501 are not inspected. Nested objects and array elements use the same rule.

The discovery screen displays a field marker and confirmation notice from the supplied result. It does not resolve ambiguity, block routing proposals, or implement a reviewer decision. Downstream validation owns the existing rule that date_format cannot be applied while the ambiguity remains unresolved. Schema comparison still reports added/missing paths and type changes only; ambiguity-only changes do not produce a comparison entry.

This detector is deliberately narrow: hyphen/dot separators, two-digit years, timestamps, locale inference and mixed-format consistency checks are outside this step. No marker means this rule found no distinct slash-date interpretations in the sample; it is not confirmation of the field's format, validity, meaning or unsampled values. Sampling and bounded display-value limits still apply.

## Snapshot publication

`app.sources.snapshot_service.publish_discovery` connects an existing DiscoveryResult to the inventory adapter and Person A's InventoryRepository. Supply the configured repository, server-authorized organization/source identity, candidate snapshot/resource metadata, and an explicit prepare_inventory callback. The function does not open a second storage implementation or infer identity from request data.

```python
from app.common.database import Database
from app.sources.repository import InventoryRepository
from app.sources.snapshot_service import publish_discovery


def withhold_samples(inventory):
    return inventory.model_copy(update={
        "fields": [field.model_copy(update={"samples": []}) for field in inventory.fields],
    })


saved = publish_discovery(
    result, InventoryRepository(Database()),
    prepare_inventory=withhold_samples,
    organization_id=authorized_organization_id,
    source_id=authorized_source_id,
    source_name="Orders",
    snapshot_id=candidate_snapshot_id,
    resource_id="orders",
    resource_name="Orders",
    resource_kind="collection",
)
print(saved.snapshot_id)
```

The example deliberately withholds all sample values. Real application composition should pass the agreed sample preparation/redaction policy; there is no default pass-through and no new redaction algorithm here. The callback receives the canonical inventory, must preserve its intended identity/structural evidence, and returns metadata safe for persistence. It runs before any repository call. A callback failure or repository error propagates to the caller rather than returning an apparent success. The repository revalidates shared contracts and owns publication transactions, scoped reads, fingerprint deduplication and immutability.

The returned inventory is the repository's published result. Identical prepared metadata for the same source may return an earlier snapshot ID instead of the candidate ID; use saved.snapshot_id for subsequent reads and routing. Changed metadata is a new immutable snapshot, and reusing an occupied ID for different content is a conflict. Existing snapshots and their field references are retained; this service does not update or delete mappings.

Repository fingerprinting applies to prepared inventory, including resource metadata, fields, samples and ambiguity, but excludes the candidate snapshot ID. If only withheld values or sample counts change, inventory may deduplicate. This is a metadata snapshot, not an uploaded batch identity or full data-version guarantee. Discovery sampling counts/method and any raw report must be retained separately; no sampling columns or latest-snapshot pointer are added here.

Use InventoryService(repository, organization_id=authorized_organization_id).get_inventory(saved.snapshot_id) for application reads. The global unscoped inventory helper is for trusted workers. Source authorization and choosing the correct organization's fixture remain the application's responsibility; the service is not a public HTTP boundary.

The persistence-only dependency retains Person A's original commits through 45e81f2. Its source repository, database adapter and migrations match the newer combined persistence branch at integration time, without importing that branch's LangGraph merge. Configure and migrate the control database using doc/us4-source-persistence.md; auth and control-plane migration histories remain separate. Neither importing nor calling this helper applies migrations automatically.

## Saved snapshot HTTP API

GET /api/sources/snapshots/<snapshot_id> uses the existing login_required helper and derives organization scope from g.user["organizationId"]. It never accepts organization identity from URL query/body fields. Unknown snapshots and snapshots belonging to another organization return the same404. Source registration creates a repository only when its DSN is configured, without connecting or applying migrations. The repository/service are reused unchanged.

Successful response:

```json
{
  "contract_version": "1",
  "inventory": {
    "snapshot_id": "orders-v1",
    "resources": [{"resource_id": "orders", "name": "Orders", "kind": "collection", "field_count": 0}],
    "fields": []
  }
}
```

Responses carry Cache-Control: no-store. Unauthenticated requests return the existing auth401 response. Missing storage configuration returns503 snapshot_not_configured; expected PostgreSQL/auth database errors return503 snapshot_unavailable with no DSN, credential or database exception text. Server logging records the exception class. Unexpected application errors retain normal failure behavior. The route is read-only, so it performs no CSRF-protected mutation or implicit publication.

The client sends credentials and validates the response's major contract version, requested snapshot ID, consumed field types/flags/samples, resource references/counts and uniqueness before rendering. It treats401 as an expired-session message and displays safe API error messages for other expected failures. The frontend makes no organization-identity claim.

### Control store configuration

Flask reads the existing GENLEDGE_DATABASE_URL and GENLEDGE_DATABASE_SCHEMA settings from its private .env or process environment, with process values taking precedence. The optional .env.example fields contain no credentials. Use the assigned developer database, a PostgreSQL/psycopg DSN with the required TLS settings, and the existing dedicated control schema (default genledge_control). No fallback to an unrelated auth/demo database is introduced.

Apply Person A's control-plane migrations separately before serving saved inventory. Its standalone migration command reads process environment, so export the settings as described in doc/us4-source-persistence.md; it does not automatically read Flask's .env. Auth tables/migrations remain separate. Startup does not create snapshots or seed another organization. A snapshot must have been published with the logged-in user's actual organization ID.

The existing auth HOST/PORT/DATABASE/USER/PASSWORD configuration and its known generic USER environment-name collision are unchanged by this feature. The isolated verification process used its own synthetic auth/control configuration, not the team's .env or normal launcher.
