# US3 — Source discovery

## Current scope

US3 contains structural discovery and comparison functions, date ambiguity evidence, an adapter to the shared InventoryView, a prepared snapshot publication helper, an authenticated saved-snapshot GET, an API-driven discovery screen, and a client-side routing handoff. The control database stores inventory metadata; raw upload persistence is not implemented by US3.

The connected frontend currently loads an already published snapshot by ID. It does not yet discover a real uploaded source or re-sample it. The routing client consumes the shared job-creation contract, but this branch has no mapping job endpoint or execution runtime.

The maintained [US3 plan](../plans/us3-discovery.md) tracks remaining work. [Smoke tests](../docs/smoke-tests.md) contain executable examples and manual procedures. The finalized implementation record and verification limits are at the end of this document.

## Entry point

`app.sources.discovery.discover_records(records, sample_limit=500)` performs structural discovery over parsed JSON-compatible records. The core needs no Flask context, database, credentials or LLM. It observes fields without converting values or modifying the input. Snapshot publication and authenticated reads use the existing shared persistence/authentication modules.

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

## Frontend presentation

The connected App now uses DiscoveryContainer to load a saved snapshot by ID from the authenticated API. It shows idle/loading/error/ready states, selects resources returned by that snapshot, clears stale results when the ID changes, cancels replaced/unmounted requests and bounds requests to 15 seconds. Reload snapshot re-reads the same immutable artifact; it does not sample a source or publish a new snapshot.

DiscoverScreen remains presentation-only. Its caller supplies sourceName, collectionName, a controlled DiscoveryState, and optional refresh/advance callbacks. The display model is separate from both raw DiscoveryResult and shared InventoryView: discoveryView renders raw samples as JSON literals; snapshotView displays canonical saved types and already prepared sample strings without quoting them twice. Native type evidence is shown separately, not parsed into invented raw types. Saved status is displayed as stored. Filters use the types/statuses present in the selected resource.

Raw previews can show sampledCount. Saved InventoryView has no sample count/method, so its screen explicitly says they were not recorded. No total record count is invented. A resource with zero fields displays an empty-resource message; changing snapshot/resource resets filters. An error never leaves the previous snapshot's fields visible.

DiscoveryPreview remains an isolated synthetic component using generated core payloads and initial/refreshed/empty/loading/error modes. It is no longer the connected App's default discovery host. The preserved standalone Frontend Demo is unchanged.

The live view submits the displayed persisted snapshot ID through the discovery-side routing handoff described below. It does not navigate to the mocked routing screen or render routing results.

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

`app.sources.snapshot_service.publish_discovery` connects an existing DiscoveryResult to the inventory adapter and the shared InventoryRepository. Supply the configured repository, server-authorized organization/source identity, candidate snapshot/resource metadata, and an explicit prepare_inventory callback. The function does not open a second storage implementation or infer identity from request data.

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

The shared contracts and persistence dependency were integrated with their original contributor history; no graph implementation is included. Configure and migrate the control database using [Source persistence](us4-source-persistence.md). Auth and control-plane migration histories remain separate. Neither importing nor calling this helper applies migrations automatically.

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

Apply the shared control-plane migrations separately before serving saved inventory. Its standalone migration command reads process environment, so export the settings as described in [Source persistence](us4-source-persistence.md); it does not automatically read Flask's .env. Auth tables/migrations remain separate. Startup does not create snapshots or seed another organization. A snapshot must have been published with the logged-in user's actual organization ID.

The existing auth HOST/PORT/DATABASE/USER/PASSWORD configuration and its known generic USER environment-name collision are unchanged by this feature. The isolated verification process used its own synthetic auth/control configuration, not the team's .env or normal launcher.


## Routing handoff

After loading a nonempty inventory, Submit snapshot to routing sends the shared CreateMappingJobRequest to POST /api/mappings/jobs. The request body is exactly:

```json
{"source_snapshot_id": "orders-v1"}
```

The ID comes from the loaded InventoryView, not from unsubmitted input text. Routing always receives the whole immutable snapshot; resource selection, search and type/status filters only change the displayed fields. No raw rows, sample values, organization identity, default snapshot or catalogue reference are submitted. Empty inventories cannot submit, including before any snapshot is loaded.

The discovery client first obtains the existing /api/auth/csrf token, then sends credentials, X-CSRF-Token and Idempotency-Key with the POST. It accepts only a 202 response containing a nonempty job_id and a canonical JobStatus. The UI shows that receipt and the status reported at handoff. It does not poll, execute a graph, infer completion, fetch a review package or advance to the mocked routing/review screens. A failed job status is displayed as returned; it is not converted into success.

A request is limited to 15 seconds across CSRF retrieval and job submission. Repeated clicks are guarded synchronously, and snapshot editing/loading/reloading is disabled during submission. Resources and filters remain usable because they do not change the snapshot. Network, authentication, API/configuration and malformed-response errors leave the discovered fields visible. A timeout may occur after the server created a job; cancellation never implies server rollback.

The container retains one request key per loaded snapshot and any accepted receipt in memory. Retrying after an error, reloading that immutable snapshot, or switching resources preserves the key while this container stays mounted. After a receipt is accepted, the same snapshot cannot submit again in that container. Leaving Discovery or refreshing the page resets this state; this increment does not provide cross-page job restoration or durable client-side retry identity. Downstream idempotency enforcement belongs to the job API.

### Downstream dependency

[PR18](https://github.com/csc301-2026-f/1-GenLedge-AI/pull/18), inspected at 79265992, defines the downstream job-creation endpoint. This branch does not register it, so submission here alone reports an unavailable API. US4 must supply compatible login/organization authorization, mutation CSRF protection and a configured runtime before a real job can be created. The US3 client does not implement that endpoint, a graph or a mock server.


## Integration dependencies and remaining work

| Boundary | Required interface or decision | Current US3 behavior |
| --- | --- | --- |
| US1 identity | Authenticated user, organization scope, CSRF and agreed roles | Reuses login_required/g.user and CSRF; does not change role/session policy |
| US2 source access | Authorized bounded reader; stable source/resource identifiers and pinned batch/version | Accepts parsed records internally; no real reader, source listing or fresh-discovery endpoint |
| Raw storage | US2 persists the upload and can read the requested batch | Control PostgreSQL holds inventory metadata, not the source records |
| Snapshot identity | Associate upload batches and previous observations with discovery metadata | Returns the repository's actual saved ID; no batch association or latest pointer is added |
| Re-sampling/drift | Reader, previous-version association and retained observation evidence | Pure comparison and presentation exist; real refresh/publish workflow is not wired |
| Sample exposure | Agreed organization access and sample preparation policy | Explicit preparation callback required; scalar discovery samples are not inherently redacted |
| US4 field semantics | Agree resource grain, repeating-array extraction and downstream literal-key/Unicode path support | Preserves canonical paths in one caller-scoped resource; does not silently relabel/split them |
| US4 execution | Authenticated, organization-scoped/CSRF-protected job API and configured runtime | Client request/receipt handling only; no polling, review UI or graph integration |
| US5/US6 review and execution | Reviewer chooses date interpretation and downstream applies approved rules | Reports ambiguity without resolving it or changing source values |

Next US3 implementation should connect the agreed US2 reader to discover_records, preparation and publish_discovery, return the saved ID to the UI, then add authorized re-sampling and drift display. An upload batch manifest and a schema snapshot are different artifacts. Stable identity must not be derived from row position or sample values, and refresh must retain prior snapshot/mapping references.

## Finalized implementation plan

The implemented slice follows this sequence; outstanding integration remains in the dependency table above and the maintained plan.

- [x] Observe bounded parsed records and compare canonical field/type observations.
- [x] Preserve structural values/types, flag narrow slash-date ambiguity, and adapt to the shared InventoryView.
- [x] Require explicit sample preparation and publish metadata through existing immutable scoped persistence.
- [x] Expose authenticated saved-snapshot reads and render actual API data with resource selection, filters and safe errors.
- [x] Submit only the loaded snapshot ID through the routing contract, retaining request identity while the discovery container stays mounted.
- [x] Consolidate the task-level plans into one maintained story plan and this finalized technical record; retain manual procedures separately.

No complete upload-to-discovery or routing-execution workflow is claimed by this slice. Each component's behavior and limits are documented above. Earlier task plans and their implementation history remain available in Git.

## Verification record

These are previously performed checks, not tests rerun during documentation consolidation.

| Area | Recorded evidence | Limits |
| --- | --- | --- |
| Original discovery/comparison | 44 backend tests passed, including 26 US3 cases; synthetic orders produced 14 fields and refresh showed currency added, paid missing and total type changes | Predates the latest main/dependency synchronization; not a current full-suite result |
| Inventory/date evidence | Manual mixed/null-only/nullable type projection, sample JSON distinctions, literal-key paths, shared-contract round-trip, valid/invalid date cases, ambiguity beyond three display samples and unread 501st record | Synthetic parsed inputs, without live source readers or reviewer resolution |
| Snapshot publication | Disposable Unix-socket-only PostgreSQL 16.14 save/read, canonical-ID deduplication, immutable new versions, scoped read/write rejection, occupied-ID conflict, sealed-field rejection, preparation failure, restart read and repeat migration | Synthetic local metadata; no team database or real raw storage |
| Snapshot HTTP/UI | Real browser login through Vite proxy to Flask and disposable PostgreSQL; 14 fields, date warning, canonical/native types, prepared samples, search/filter, multi-resource 8/6/4 fields, empty/error states, immutable reload and database 503/recovery | Isolated synthetic users/data; normal team launcher/host and PostgreSQL 17 were not verified |
| API access/errors | Anonymous 401, own 200, identical missing/cross-org 404 including forged organization query, logout then 401, no-store and missing-configuration 503 | Unexpected network bodies and timeout/race fault injection were not exercised |
| Routing client | TypeScript check, Vite production build, source/contract review and whitespace check | No browser/HTTP job success, real execution or timeout fault injection; no downstream endpoint in this branch |

Python compilation and frontend TypeScript/build checks passed during the relevant implementation work. The full automated suite was not rerun after the original core stage; later work did not add or run new automated tests. Temporary databases, servers and synthetic users used for manual inspection were cleaned up; no team credentials or existing databases were used. Existing tests/fixtures and repeatable manual procedures are linked from [Smoke tests](../docs/smoke-tests.md).

Documentation consolidation changes no runtime code. Its checks cover Markdown references, whitespace, current status consistency and the documentation-only Git diff.
