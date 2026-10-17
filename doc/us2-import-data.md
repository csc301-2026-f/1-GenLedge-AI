# US2 - Import data

Current implementation and handoff guide. See [smoke checks](../docs/smoke-tests.md)
for manual acceptance procedures.

## Scope and remaining gaps

File import supports CSV, TSV, XLSX, XLS, JSON and NDJSON, including MongoDB-shaped
Extended JSON. Connected MongoDB/DocumentDB in-place reads are not implemented.
Discovery and Mapping Studio still use separate prototype flows; saved mapping
work is supported through the API below, not the US5 UI.

Intake uses `intake_*` tables in the configured application PostgreSQL database.
Organization/environment scope isolates sources, records, fields and mappings.
This is logical tenant isolation, not a separate physical database per client;
confirm that interpretation of "client's intake database" before deployment.
SQLite is available only for isolated tests. There is no local-file fallback.
Previously saved local JSON Lines files are not migrated or deleted; re-upload
originals if needed. The obsolete local adapter has been removed.

## Setup and verification

From `src/backend`, reuse `.venv` or create it with `python -m venv .venv`, then:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m app.sources.connectors.files tests/fixtures/orders.csv
```

The CLI validates without storage and prints collection summaries, never records.
Invalid input exits nonzero. The automated suite uses disposable SQLite databases;
PostgreSQL variants require `TEST_DATABASE_URL` pointing to a developer-owned,
non-superuser database over TLS (`DB_SSLMODE`, optionally `DB_SSLROOTCERT`). They
create and remove isolated schemas. To run intake and mapping PostgreSQL cases:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_postgres_intake.py tests/test_mapping_retention.py -k "postgresql and not sqlite" -q -p no:cacheprovider
```

For the application, configure the existing PostgreSQL settings described in the
[auth guide](auth-api.md), provision an account and apply migrations through
`flask --app main auth-init-db` using the project interpreter and an authorized
database. Intake requires revisions `0002_intake` and `0003_mapping_retention`.
Requests never apply migrations. The app launchers check the database and prompt
before applying pending migrations.

Optional backend settings:

```dotenv
GENLEDGE_INTAKE_ENVIRONMENT=development
GENLEDGE_INTAKE_KEEP_PREVIOUS=1
GENLEDGE_INTAKE_GRACE_DAYS=7
```

Environment defaults to `APP_ENV`. Retention values are nonnegative integers.
Start `src/start-app.bat` or `src/start-app.sh`, sign in, choose Upload File,
select a file and click Import File. Successful publication refreshes the source
list; same-filename uploads update one source. Refresh Sources resolves an
uncertain network outcome before an explicit retry.

## Parsing and identity

- Maximum file size: 25,000,000 bytes inclusive, plus 1 MB multipart framing.
  Maximum records: 50,000 per collection, including each worksheet. The same
  bound applies to document/text formats; headers and blank table rows do not count.
- CSV/TSV use UTF-8 with optional BOM. The first nonempty row is the header;
  values remain strings, including leading zeros. Quoted delimiters/newlines work;
  ragged rows fail. Blank headers become `column_N`, whitespace is trimmed, and
  duplicates receive collision-safe suffixes. Metadata preserves original headings.
- Every XLSX/XLS worksheet, including hidden sheets, becomes a separate collection.
  Empty sheets fail; header-only sheets are valid. Missing trailing cells become
  null and dates/times become ISO strings. XLSX formulas/errors fail; XLS uses
  stored formula results from xlrd. No formulas are evaluated. Corrupt/encrypted
  workbooks fail. XLSX expanded archive contents are limited to 100 MB.
- JSON accepts an object or array of objects; NDJSON accepts one object per nonblank
  line. Nesting, arrays and Extended JSON objects such as `$oid` remain JSON.
  Empty datasets, duplicate keys and non-finite/overflowing numbers fail.
- Source identity hashes organization, environment and the exact basename; matching
  is case-sensitive. Collection identity uses source and original collection name.
  Intake names hash source, collection and batch, avoiding unsafe physical names.
  Each import has a new batch ID and UTC timestamp. Collection names must be unique.
- Parsing completes before staging. Records are bounded but held in memory; this
  is not a streaming ingestion worker. Deep nesting beyond parser limits fails.

## API

Use the existing auth session and `GET /api/auth/csrf`. Login/logout rotate the
session token; obtain it again after login. All source routes require a current
session, derive organization from it and return `Cache-Control: no-store`.
POST/PUT/DELETE require `X-CSRF-Token`; submitted tenant/environment fields cannot
change storage scope. The redundant upload-specific CSRF and validation routes
have been removed; imports always perform full validation.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/sources/uploads` | Validate and publish exactly one multipart `file` |
| GET | `/api/sources` | List active published sources in the current scope |
| GET | `/api/sources/<sourceId>/fields` | Field identities, structural paths and observed types |
| GET | `/api/sources/<sourceId>/mappings` | Saved definitions and validity |
| PUT | `/api/sources/<sourceId>/mappings/<mappingId>` | Save against an expected active batch |
| DELETE | `/api/sources/<sourceId>/mappings/<mappingId>` | Delete against an expected active batch |

Import returns 201 with `status: imported`, `persisted: true`, `source` and
`warnings`. Source metadata contains sourceId, batchId, filename, environment,
format, sizeBytes, uploadedAt and collections (collectionId, name, rowCount,
headers, warnings). Records, storage paths and credentials are never returned.
Listing returns `{sources: [...]}`, newest first, excluding staged/historical data.

Errors: 400 malformed request; 401 signed out; 403 invalid CSRF; 413 too large;
415 unsupported format; 422 invalid file; 409 publication conflict; 503 unavailable
storage/import failure. `publication_unknown` includes batchId: publication may
have committed despite a lost acknowledgement. Refresh before retrying. Neither
the server nor UI automatically retries an uncertain import.

## Publication, mappings and retention

`service.import_file` parses the whole file, stages a new immutable manifest and
writes every collection before publishing. PostgreSQL atomically checks the
expected active batch, reconciles mappings and updates the active pointer.
Partial writes never replace active data. Staging failures attempt cleanup;
uncertain publication retains its batch for reconciliation. Batch IDs remain
reserved after discard. Automatic retry/idempotency and abandoned-stage cleanup
are not implemented.

### Field identity and saved work

Fetch `GET /api/sources/<sourceId>/fields` using an authenticated session. The result
contains sourceId, batchId and fields. Each field has fieldId, collectionId, path,
kinds and matchable. Path segments are exact JSON object keys; null denotes any
array element. For example `["lines", null, "sku"]` is different from a literal
key `["lines[].sku"]`. Types are string, number, boolean, object and array; null
adds no observed type. Integers and floating-point values share number.

IDs use stable collection identity and structural path. Unique spreadsheet/CSV
headings use their trimmed original name, so column reordering preserves identity.
Blank or duplicate headings are ambiguous: their field IDs include the batch and
cannot be automatically matched on refresh, even if parser-generated names look
identical. They can still be explicitly mapped within the current batch.
JSON keys preserve their exact spelling. Matching fields must have unchanged
observed non-null types; new null-only data is allowed, while unknown-to-known or
changed/mixed types require review. Renames are not guessed.

Save a mapping with PUT, the session cookie and X-CSRF-Token:

```text
PUT /api/sources/<sourceId>/mappings/customer-name
```

```json
{
  "expectedBatchId": "<batchId returned with fields>",
  "collectionId": "<collectionId>",
  "fieldIds": ["<fieldId>"],
  "definition": {
    "target": "customer_name",
    "transform": {"operation": "uppercase"},
    "humanNote": "Keep the reviewer decision"
  }
}
```

Mapping IDs accept 1-128 letters, digits, underscores or hyphens. Supply 1-1000
distinct field IDs, all from the same current collection. definition is a nonempty
JSON object limited to 100 KB. It is stored verbatim as JSON data, not interpreted
or executed. The mapping feature must list every source-field dependency in
fieldIds and validate its own target/transform language. Cross-collection joins
and approved model-version semantics are outside this small US2 persistence API.

GET `/api/sources/<sourceId>/mappings` returns batchId and mappings with mappingId,
collectionId, fieldIds, definition, status, validBatchId and checkedBatchId.
On refresh, matching fields keep definition unchanged and move validBatchId to the
new batch. Removed, ambiguous or incompatible fields become needs_review; their
original definition and last valid batch remain. checkedBatchId identifies the
latest refresh. A field restored with a compatible identity can validate again.
Downstream execution must use only mappings with status=valid and matching
checkedBatchId/validBatchId for its chosen batch; this API does not execute them.

PUT explicitly saves/reviews the mapping against the latest batch. DELETE uses
the same URL and a JSON body containing only expectedBatchId; both require CSRF.
Stale-batch writes/deletes return 409, unknown or foreign-scope sources return 404,
and malformed definitions/references return 400. Concurrent mapping edits on the
same batch use last-write-wins semantics. US5's fixture UI is not connected to this
API yet, and existing browser-only fixture edits are not migrated into it.

Publication locks the source and reconciles mappings in the same transaction as
the active pointer change. Failed parsing, staging or publication leaves the old
snapshot and mappings intact. Mapping definitions do not automatically change
when data changes. There is no full schema-discovery or mapping assistant here.

### Snapshot cleanup and reads

A sweep runs after successful HTTP publication, in a separate transaction. It
always protects active data, the newest configured number of previous snapshots,
and snapshots still inside the grace period measured from supersession. Durable
pins and mapping validBatchId references also prevent payload deletion. A cleanup
failure returns import success with a maintenance warning and logs the failure.
The upload UI currently displays publication success and header corrections only.

There is no scheduled sweeper. An authorized operator can retry for one source:

```powershell
.\.venv\Scripts\python.exe -m flask --app main intake-sweep --organization ORG_ID --source SOURCE_ID
```

`PostgresIntakeStore.published_snapshot(source_id, batch_id)` reads the manifest;
`read_sample(source_id, batch_id, collection_id, limit=500)` reads up to 500 records
from that exact published batch. Wrong scope, source or collection is rejected.
Readers hold a shared batch lock; sweeps skip busy batches. Longer consumers must
call `pin_snapshot(source_id, batch_id, pin_id)` before relying on old data, then
`release_pin(batch_id, pin_id)` in a finally block. Pins do not expire automatically.

Sweeps remove record payloads only, retaining manifests, fields and publication
history. Expired samples/pins raise `SnapshotExpiredError`; they never redirect to
the active batch. Metadata growth and abandoned-stage reconciliation remain
operational follow-up work. PostgreSQL lock guarantees require real PostgreSQL
verification; SQLite tests do not establish concurrency behavior.
