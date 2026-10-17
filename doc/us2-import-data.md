# US2 — Import data

This is the single implementation and handoff guide for US2. The
[working plan](../plans/us2-import-data.md) tracks remaining work; shared manual
checks are in [smoke tests](../docs/smoke-tests.md).

## Current scope

Authenticated file validation/import, organization-scoped source listing, metadata,
PostgreSQL intake storage and the published-batch sample reader are implemented.
The web UI saves validated files and reloads published sources. Shared authentication
supplies organization identity; storage environment comes from server configuration.
Mapping persistence/reconciliation and PostgreSQL snapshot retention are implemented.
MongoDB/DocumentDB connections, discovery/mapping UI integration and deployment
verification remain outstanding. The web flow now uses intake tables
in the configured application PostgreSQL database. Local JSON Lines storage is
retained for compatibility/testing but is no longer selected by HTTP routes.

## Local setup and testing

Use the project virtual environment from `src/backend`; system Python may not
have the required packages. On a fresh checkout, create `.venv` with your installed
Python, then install the development requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If `.venv` already exists, reuse it. Run the parser and tests with that interpreter:

```powershell
.\.venv\Scripts\python.exe -m app.sources.connectors.files tests/fixtures/orders.csv
.\.venv\Scripts\python.exe -m pytest tests/test_import_workflow.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

The sample produces `status: validated`, `persisted: false`, one `orders`
collection and two records. Invalid files exit with code 1 and a validation
message. The historical pre-local-store run passed 17 workflow tests and 80
backend tests; see the verification records below for subsequent changes.
The optional `-p no:cacheprovider` avoids local pytest cache permission warnings
without changing test execution.

For the web flow, provision a real account using [the auth guide](auth-api.md).
Configure these settings in `src/backend/.env` (an existing private file; do not
commit credentials), or in the environment inherited by the backend:

```dotenv
GENLEDGE_INTAKE_ENVIRONMENT=development
```

Keep the existing HOST, PORT, DATABASE, USER, PASSWORD and TLS settings used by
authentication. Intake uses that same configured PostgreSQL engine, in separate
`intake_*` tables. GENLEDGE_INTAKE_ROOT is no longer read by the web application.
The intake environment defaults to APP_ENV. A non-PostgreSQL runtime or missing
migrations produces 503 on import/list; it never silently saves to local files.
SQLite remains available only in isolated tests (Flask TESTING=True).

From `src/backend`, apply migrations to your authorized developer database before
starting the server (this existing command applies all application migrations):

```powershell
.\.venv\Scripts\python.exe -m flask --app main auth-db-check
.\.venv\Scripts\python.exe -m flask --app main auth-init-db
```

Revision `0002_intake` follows `0001_auth_tables`; it creates intake tables and
preserves existing auth data. Startup/import requests do not automatically migrate.
Existing local files/catalogs are untouched and are not automatically imported.
Re-upload originals to populate PostgreSQL, or arrange a separate migration if old
batch IDs and their downstream references need to be preserved.

Run `src\start-app.bat`, sign in at http://127.0.0.1:5173, then choose Upload File,
Choose File and Import File. The server parses the complete file before writing,
reports success only after publication and refreshes the source list. Reloading the
page or restarting the backend retains sources when the same database/environment are
used. Same-filename imports update the source; old published batches remain readable.

## Code walkthrough

1. `connectors/files.py:parse_file(filename, stream)` bounds the file read and
   chooses a parser by extension. Text is decoded as UTF-8 with optional BOM.
2. Table parsers normalize headers and validate each data row. Document parsers
   preserve objects and arrays. A failure anywhere raises `FileValidationError`;
   callers never receive a partially validated workbook.
3. The result is a `ParsedFile` with `ParsedCollection` objects containing full
   records. The import service passes these to an intake writer after
   parsing returns successfully. Do not use the summary as the import payload.
4. `routes.py` verifies the shared revocable session and CSRF token. It derives
   organization from `g.user`, never submitted form fields, and calls `import_file`.
5. `UploadFileModal.tsx` shows publication results and header corrections; the source
   screen reloads saved manifests. Discovery/connect actions remain disabled until
   their actual integrations are implemented.

## API

Eight US2 endpoints are currently implemented on the Flask backend (default port
5000). The frontend uses relative `/api/...` URLs, proxied by Vite on port 5173.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/sources/uploads/csrf` | Obtain the session's upload CSRF token |
| POST | `/api/sources/uploads/validate` | Parse and validate one uploaded file without saving it |
| POST | `/api/sources/uploads` | Validate and publish a file import |
| GET | `/api/sources` | List this organization/environment's active published sources |
| GET | `/api/sources/<sourceId>/fields` | Active field identities, paths and observed types |
| GET | `/api/sources/<sourceId>/mappings` | Persisted mapping definitions and validity status |
| PUT | `/api/sources/<sourceId>/mappings/<mappingId>` | Save mapping work against an expected active batch |
| DELETE | `/api/sources/<sourceId>/mappings/<mappingId>` | Delete mapping work against an expected active batch |

Request order: fetch the auth CSRF token, sign in through the existing auth API,
fetch the rotated token, then upload using the same session cookie. The upload
CSRF route is an authenticated compatibility alias for the shared token.
There is no database-connection registration endpoint yet.

### POST /api/sources/uploads and GET /api/sources

Import accepts exactly one multipart `file`, with the shared X-CSRF-Token header.
It re-parses the uploaded bytes regardless of any earlier validation. Organization
and environment fields submitted by callers do not select storage scope.
Success is HTTP 201: `{"status":"imported","persisted":true,"source":{...}}`.
The source contains sourceId, batchId, filename, environment, format, sizeBytes,
uploadedAt (UTC ISO timestamp), and collections with collectionId, name, rowCount,
headers and warnings. No records, intake paths or credentials are returned.

Listing is HTTP 200: `{"sources":[...]}` using the same source representation,
newest upload first. It includes only active published batches, not staged/failed
imports or historical snapshots. An empty scope returns an empty list.
All routes require current authentication and return Cache-Control: no-store.

Import uses the validation error statuses below, plus 409 publication_conflict
and 503 for unavailable storage or import failures. A publication_unknown result
includes batchId because publication may have committed despite a lost acknowledgement.
Refresh the source list before retrying; requests are never retried automatically.
The UI likewise treats a timeout/network failure as an uncertain outcome.

### GET /api/sources/uploads/csrf

- Requires a signed-in session; no request body or CSRF header is needed.
- Returns 200 with `{"csrfToken": "<token>"}`, or 401 if signed out.
- Creates a token if the session has none; otherwise returns the existing token.
- Tokens are stored under `csrf_token` in the session. Existing login
  and logout clear the session, invalidating the token for subsequent requests.
- Returns `Cache-Control: no-store`.

### POST /api/sources/uploads/validate

- Signed-in authenticated session and `X-CSRF-Token` from
  `GET /api/sources/uploads/csrf` required. The token endpoint also requires a
  signed-in session. Both endpoints return `Cache-Control: no-store`.
- Multipart form with exactly one file in the `file` field.
- Do not set the multipart Content-Type manually in browser fetch; FormData
  provides the boundary.
- Response is not cached. Full records and credentials are not returned.

Example 200 response (abbreviated):

```json
{
  "status": "validated",
  "persisted": false,
  "filename": "orders.csv",
  "format": "csv",
  "sizeBytes": 20,
  "collections": [{
    "name": "orders",
    "key": "orders_1c168adb00d208e4",
    "rowCount": 1,
    "headers": [{"column": 1, "original": "id", "key": "id"}],
    "warnings": []
  }]
}
```

Errors contain `error` text and, for parser failures, a machine-readable `code`.
Statuses: 400 malformed request; 401 signed out; 403 invalid CSRF; 413 too large;
415 unsupported format; 422 invalid file. Requests without a signed-in session
return 401 before CSRF validation.

## Parsing rules and current decisions

- 25 MB means 25,000,000 bytes, inclusive; request framing gets an extra 1 MB.
- 50,000 records per collection, inclusive, across all six formats. Worksheet
  headers and blank rows do not count. This extends the worksheet rule to text
  and document formats until the team agrees on different limits.
- CSV/TSV: first nonempty row is the header. Fields stay strings (including leading
  zeros); quoted delimiters/newlines work. Ragged rows fail. Blank rows are ignored.
- Blank headings become `column_N`; whitespace is trimmed. Duplicate headings get
  suffixes without stealing another original heading: `name,name,name_2` becomes
  `name,name_3,name_2`. Original headings, column positions and corrections remain
  in metadata. PostgreSQL field identity uses the conservative rules in the mapping section below.
- XLSX/XLS: each worksheet becomes a collection, including hidden sheets. Empty
  sheets fail; header-only sheets are valid with zero records. Missing trailing
  cells become null; dates/times become ISO strings. XLSX formulas and Excel error
  cells fail with instructions to paste values. XLS uses stored formula results
  exposed by xlrd; neither parser evaluates formulas. Password-protected/corrupt
  workbooks fail. XLSX archive contents are limited to 100 MB expanded.
- JSON: one object or an array of objects. NDJSON: one object per nonblank line.
  Empty document datasets fail. Nested structures and MongoDB Extended JSON
  objects (such as `$oid`) are preserved as JSON, not interpreted as BSON.
  Duplicate object keys, non-standard numbers, and numeric overflow fail.
- Collection keys combine a safe slug and stable name hash, preventing collisions
  when different names normalize to the same slug. The future intake layer must
  also scope physical names by organization, source and batch.
- UTF-8 is required for text formats. There is no type inference or flattening.
- The implementation holds validated records in memory; it is a bounded-file MVP,
  not a streaming ingestion worker. Larger-scale ingestion needs its own resource
  budgets. Deeply nested documents that exceed the parser's recursion limit fail.

Excel parsing follows [openpyxl read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html)
and the [xlrd workbook API](https://xlrd.readthedocs.io/en/latest/api.html).

## Metadata

The frozen dataclasses in `app/sources/metadata.py` describe a complete snapshot.
They are application contracts, not SQL tables or MongoDB documents.

| Object | Fields and purpose |
| --- | --- |
| SourceIdentity | organization_id, environment, filename; derives stable source_id |
| SnapshotMetadata | source, unique batch_id, UTC uploaded_at, format, size_bytes, complete collection manifest |
| CollectionMetadata | stable collection_id, original name, batch-specific intake_name, row_count, headers, warnings |
| HeaderMetadata | original heading, normalized key, one-based column position |

Source identity uses the exact basename returned by the parser, scoped by
organization and environment. `orders.csv` and `Orders.csv` are distinct; changing
the filename extension creates a different source. Directory components supplied
by upload clients are stripped by the existing parser. These are explicit initial
product rules for the team to confirm before persistence is enabled.

Source IDs are SHA-256 hashes of unambiguous JSON-encoded identity components.
Collection IDs similarly combine source ID and exact worksheet/collection name.
They remain stable when data, row order or worksheet order changes. Renaming a
worksheet gives it a new collection ID. Batch IDs are fresh UUID hex strings.
Intake names are `intake_` plus a 64-character hex hash of source, collection and
batch IDs: bounded, deterministic for that tuple, and independent of raw names.
The storage adapter still chooses the authorized client's storage scope; a safe
name is not an authorization check. No customer records are augmented with internal
metadata, and original `_id`/nested keys must not be overwritten by the adapter.

Batch lifecycle is represented by staging/completion records and the active
manifest pointer, rather than a mutable status flag inside the snapshot object.
A previous published snapshot remains immutable and available to existing readers.

## Import service

`app/sources/service.py:import_file` accepts a binary stream, filename, trusted
organization/environment scope, and an `IntakeWriter` implementation:

```python
snapshot = import_file(
    filename, stream,
    organization_id=authorized_organization_id,
    environment=authorized_environment,
    writer=intake_writer,
)
```

The HTTP import route authorizes identity through shared login, selects server-side
scope and passes the actual uploaded bytes to this service. It never trusts a
browser validation summary as stored data.

The service performs these steps:

1. Parse and validate the entire file before any storage call.
2. Build source, batch and collection metadata and read the previous active batch.
3. Stage the new manifest and write every collection, including empty collections.
4. Publish with the expected old batch ID (or None for a new source).
5. Return the published metadata only after the writer acknowledges publication.

All worksheets are published together through one source manifest. Removed sheets
are absent from the new manifest; their old physical data remains in the retained
old batch. This avoids mixing old sheets with refreshed sheets.

## Writer obligations

`app/sources/writer.py` defines a Python Protocol with five methods:

| Method | Required behavior |
| --- | --- |
| active_snapshot(source_id) | Read the published manifest, never partial staging |
| stage(snapshot) | Create isolated staging; reject duplicate batch IDs |
| write_collection(batch_id, collection_id, records) | Write all records durably, then mark complete; verify manifest membership and row count; preserve nesting |
| publish(batch_id, expected_batch_id) | Check all completion markers and atomically compare-and-swap the active source manifest |
| discard_unpublished(batch_id) | Idempotent cleanup of staging only; refuse any previously published batch |

The real adapter must enforce source uniqueness and compare-and-swap, including
when two writers both see a missing source. `PublicationConflict` means another
import changed the active source. It must not silently overwrite the winner.
Counts alone cannot prove content correctness: the adapter must acknowledge every
write and durably record completion, not simply count partial data.

If metadata and intake records live in separate databases, do not assume a
cross-database transaction exists. Store immutable data first; make the metadata
pointer the publication boundary and reconcile abandoned staging separately.
Readers must resolve and pin one batch manifest for an operation. Old-snapshot
cleanup is separate from publication; the PostgreSQL adapter now implements the retention policy below.

## PostgreSQL intake writer (current HTTP storage)

`PostgresIntakeStore(engine, organization_id=..., environment=...)` implements the
same writer and read_sample/published_snapshot/list_sources methods. HTTP callers
use the shared authenticated organization; changing submitted organization or
environment fields does not change storage scope. Do not expose the adapter to
untrusted code or give end users direct database credentials: application scoping
is not PostgreSQL row-level security.

| Table | Contents |
| --- | --- |
| intake_sources | Scoped source identity and active published batch pointer |
| intake_batches | Immutable manifest, publication status, retained discard markers |
| intake_collections | Collection identity, row count and completion marker |
| intake_records | Parsed object per row, ordered by ordinal, in payload JSON |
| intake_fields | Per-batch field paths, stable IDs and observed non-null types |
| source_mappings | Definitions, validity and last-valid/last-checked batch references |
| intake_pins | Durable consumer pins preventing payload cleanup |

Each worksheet is a separate logical collection, not a dynamically named SQL table.
Use source/collection/batch IDs to group records. Published history is retained.
Data and metadata now live in PostgreSQL; no record files or local catalog are used.
The existing safe intake_name stays metadata rather than becoming a SQL identifier.

Records use PostgreSQL JSON rather than JSONB, with ASCII-escaped serialization,
to preserve parser-accepted Unicode escapes and numeric values. No JSON operators
or casts to JSONB are applied by the sample reader. Some PostgreSQL JSON processing
functions impose stricter Unicode rules; see [PostgreSQL JSON documentation](https://www.postgresql.org/docs/17/datatype-json.html).
Original keys, nested arrays/objects, leading-zero strings, null and booleans are
preserved. Non-finite values are rejected before commit. This stores parsed values,
not an exact copy of the uploaded file bytes.

Collection records are inserted in chunks inside one transaction and completion
is committed with them. Batch row locks serialize writing, publishing and discard.
Publication locks the source row (created during staging, including first imports),
checks expected_batch_id, then updates status and active pointer atomically. A
competing publisher receives PublicationConflict. Reads pin a published batch and
use ORDER BY ordinal LIMIT (at most 500). The read holds a shared batch lock through
record retrieval. Published manifests remain; eligible old record payloads may be swept.
Discard deletes only staged rows in one transaction and retains a batch tombstone;
reuse of a discarded ID fails. Acknowledgement loss after publication retains data
for reconciliation. No automatic import retry or orphan reconciliation worker is
introduced. After successful HTTP import, a separate retention sweep can remove
eligible superseded payloads. A failed sweep never rolls back a published import.

For database inspection, using your authorized database account:

```sql
SELECT scope_id, source_id, active_batch_id FROM intake_sources;
SELECT scope_id, batch_id, source_id, status FROM intake_batches;
SELECT collection_id, row_count, complete FROM intake_collections;
SELECT r.collection_id, r.ordinal, r.payload
FROM intake_records r
JOIN intake_sources s ON s.scope_id = r.scope_id AND s.active_batch_id = r.batch_id
ORDER BY r.batch_id, r.collection_id, r.ordinal
LIMIT 20;
```

These administrative queries can see all organizations accessible to that database
role. Application API queries always select the authorized organization/environment.

### Database integration tests

Run the normal suite without external services. For PostgreSQL-specific tests, set
TEST_DATABASE_URL privately to a developer-owned PostgreSQL URL (role name equals
database name, non-superuser) and use DB_SSLMODE=require/verify-ca/verify-full plus
DB_SSLROOTCERT where required. Never commit the URL. Then run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_postgres_intake.py tests/test_postgres_integration.py -q -p no:cacheprovider
```

The PostgreSQL fixtures create a random intake_test_* schema and drop only that
schema afterward. They test migrations, JSON edge cases, authenticated HTTP imports,
isolation, rollback, pinned sampling and concurrent first publication/refresh.
SQLite variants cover application behavior but do not establish PostgreSQL locking,
JSON compatibility or durability. Never point tests at a shared integration database.

## Persistent local writer (legacy internal adapter)

The following describes the retained local adapter, not the current web storage.



`app.sources.local_store.LocalIntakeStore` implements the existing IntakeWriter
contract using JSON Lines record files and a standard-library SQLite catalog.
The caller supplies an absolute storage root outside Git and a trusted
organization/environment. Construction initializes local directories/catalog;
importing the module or starting Flask does not initialize this adapter.

```python
import io
from pathlib import Path
from app.sources.local_store import LocalIntakeStore
from app.sources.service import import_file

store = LocalIntakeStore(
    Path.home() / ".local" / "share" / "genledge" / "intake",
    organization_id=authorized_organization_id,
    environment=authorized_environment,
)
manifest = import_file(
    "orders.json", io.BytesIO(b'[{"id":"001","lines":[{"sku":"A"}]}]'),
    organization_id=authorized_organization_id,
    environment=authorized_environment,
    writer=store,
)
print(manifest.source_id, manifest.batch_id)
```

The root contains a hashed directory per organization/environment. Each scope has
`catalog.sqlite3` and `records/<hashed-batch>/<hashed-collection>.jsonl`. Raw file
names, source IDs and batch IDs are never interpolated as filesystem paths.
On Windows, the absolute storage root is normalized to an extended-length path
before creating directories or opening SQLite and record files. This supports
the long paths produced by scoped hashes without shortening stable identities.
It does not establish Windows directory-flush or power-loss guarantees.
Stored JSON Lines contain parser-produced records, not a byte-for-byte archive of
the original upload. CSV values remain strings, header corrections remain in
metadata, and nested JSON values retain their types.

The catalog stores complete manifests, collection completion markers, durable
publication history and the current source pointer; it does not store raw rows.
`intake_name` remains metadata, not an externally supplied physical path.

The scope must come from an authorized server-side identity. Separate catalogs
isolate lookups, but constructing an adapter for any organization is possible to
trusted application code; this is not authentication or filesystem encryption.
New directories use private permissions where supported. The operator must keep
the root private and outside Git; do not serve it as static files.

### Publication and cleanup

- `stage` verifies scope and inserts the unpublished manifest/collections together.
  Duplicate batch/collection IDs fail through catalog constraints. Batch IDs in
  the catalog's `discarded_batches` tombstones cannot be staged again.
- `write_collection` checks membership, row count and unfinished state. It writes
  one JSON object per line to a partial file, flushes/fsyncs it, replaces the final
  path and only then commits the completion marker. Empty collections still
  produce a synced empty file and a completion marker. Parsed values/nesting and
  original keys are preserved; unsupported values and non-finite numbers fail
  during JSON serialization instead of being silently replaced.
- `publish` checks all completion markers and the expected old batch under one
  BEGIN IMMEDIATE transaction, then marks publication and updates the active
  pointer together. A competing publication raises the existing PublicationConflict.
  Published batches cannot be written again, re-published or discarded.
- `discard_unpublished` atomically records a durable `discarded_batches` tombstone
  and removes the unpublished manifest/completion rows, then removes its files.
  It also tombstones unknown batch IDs, preventing staging from racing their
  cleanup. Retaining the marker permanently prevents ID reuse while file deletion
  is pending or retried. Interrupted cleanup leaves unreachable staging files
  rather than a publishable manifest with missing records. Repeating cleanup is
  safe; real filesystem errors propagate. Old published batches remain immutable.

Existing catalogs gain the tombstone table on construction without changing
published records. Restart all workers with the updated adapter; older versions
do not check tombstones and must not share the catalog during cleanup.

Records and the catalog do not share one transaction. Files are completed before
the atomic catalog publication; readers must use published metadata only. A crash
before publication can leave unpublished batches or partial/orphan files. A crash
after publication retains the batch's published flag even after a later refresh
replaces its active pointer, supporting future reconciliation. This adapter does
not provide an automatic reconciliation/retention worker.

The SQLite catalog uses FULL synchronization. On POSIX the writer also syncs
record directories before acknowledging collection completion. Windows directory
flush behavior, machine power-loss recovery and disk/controller guarantees have
not been verified; process-restart persistence alone is not a power-loss test.
Use a single host with a local filesystem that supports SQLite locking, not a
network share. Writes in one organization/environment serialize through the
catalog lock, including collection I/O; this is a deliberate bounded-file MVP
trade-off. SQLite/storage errors propagate rather than silently retrying.

The local adapter itself requires no external database. HTTP integration now uses
shared authentication, configured intake storage and the endpoints described above.

### Published-batch reader

The same store exposes these internal interfaces:

| Method | Result |
| --- | --- |
| active_snapshot(source_id) | Current published SnapshotMetadata, or None for an unknown source in this scope |
| published_snapshot(source_id, batch_id) | That exact published manifest, including a superseded batch |
| read_sample(source_id, batch_id, collection_id, limit=500) | First N parsed records, with an integer limit from 1 to 500 |

Resolve the active batch once, then pin its ID throughout the operation:

```python
manifest = store.active_snapshot(authorized_source_id)
if manifest is None:
    raise LookupError("Source not found.")
collection = manifest.collections[0]  # Or an authorized collection selected by the caller.
records = store.read_sample(
    manifest.source_id, manifest.batch_id, collection.collection_id, limit=500,
)
# Pass records to US3 discovery once that application integration is connected.
```

Every read uses the constructor's organization/environment scope. Unknown or
foreign batches/sources, unpublished batches and collections absent from the
manifest raise IntakeNotFoundError. No unscoped lookup or caller-supplied path is
available. This scope must still be authorized by a future request/worker caller.
Published files are retained and never modified by this adapter, so a concurrent
refresh cannot redirect the pinned read to a different batch.

The reader consumes at most min(limit, manifest.row_count) JSON Lines; it does not
parse record 501 or scan the full collection. A header-only CSV collection returns
an empty list. Non-finite numbers (NaN, Infinity, -Infinity and exponent overflow
such as 1e999) are rejected when decoding sampled records. Malformed JSON/non-object
lines, missing files or truncation before
the expected sampled count fail explicitly instead of producing empty/partial
success. Corruption beyond the sample is not inspected. The manifest's row_count
is the full parsed batch count; len(records) is only the sampled count.

Upload batch IDs and US3 inventory snapshot IDs remain distinct. This adapter
provides parsed records plus stable source/collection/batch identity, not a
DiscoveryResult or an InventoryView. It does not publish discovery metadata,
run discovery itself. Source listing and upload UI integration are implemented by
the HTTP layer described above.

## Failure semantics

- Parsing or missing scope fails before storage calls. Active-snapshot read errors
  propagate without any attempted write.
- Staging/write failure triggers best-effort `discard_unpublished`. The service
  raises `ImportStorageError` with batch_id, phase="staging", and cleanup_failed.
  The original exception is retained as the cause; cleanup must not mask it.
- Publication failure raises `ImportStorageError` with phase="publication" and
  the batch ID. Its cause distinguishes `PublicationConflict` from other errors.
  No automatic cleanup runs after a publication attempt, even on a conflict.
- A publish timeout can mean publication succeeded and only the acknowledgement
  was lost. Reconcile the batch's durable state before retrying or deleting it.
  Checking only the current active pointer is insufficient if a later batch has
  already replaced it: keep publication history/status. Retry/idempotency APIs
  and a reconciliation worker are deferred until the storage design is known.

## Mapping boundary

Stable source/collection IDs give the mapping feature a durable reference across
refreshes. Header metadata and per-batch field profiles now support conservative identity and
type checks. PostgreSQL publication reconciles saved US2 mapping definitions in
the same transaction as the active-batch switch. Definitions are never rewritten
by refresh. See the mapping API contract below. The existing US5 Mapping Studio
still uses fixtures and must adopt this API; it is not connected automatically.

## Verification and database handoff

The fake writer verifies orchestration with fault injection: invalid later sheets,
partial writes, failed staging and cleanup, competing publishers, and lost publish
acknowledgements. It deep-copies records to model isolation and rejects incomplete
publication. It is a synchronous test double, not evidence of real database
atomicity, durability, crash recovery or thread/process safety.

The concrete local adapter is now available; the fake writer remains useful only
for orchestration checks. Filename identity, reader retention, reconciliation, retry/idempotency,
external source connections remain integration work. PostgreSQL mapping
preservation and snapshot retention are implemented below. Real multi-process contention and
crash/power-loss behavior require separate verification; the historical fake-writer
suite does not establish those properties for LocalIntakeStore.

## Finalized plan and completed-work record

The completed phases were implemented in this order:

1. Build the six-format parser, validate all collections before returning, and
   add focused boundary/corruption tests.
2. Connect a protected validation-only endpoint and modal. Adapt the integration
   to this branch's demo authentication so US2 can progress independently of login work.
3. Define immutable metadata and the writer Protocol. Implement isolated staging
   and source-level publication with an expected previous batch.
4. Exercise failure and concurrency scenarios with a fake writer, retaining
   uncertain publication outcomes for reconciliation rather than deleting data.
5. Consolidate the story's documentation into this guide and one working plan.

Verification recorded before the documentation consolidation:

- 80 backend tests passed, including 17 import workflow tests. The earlier
  validation-only phase passed 63 backend tests.
- TypeScript no-emit check, Vite production build, upload-validation browser smoke
  and existing auth browser smoke passed for the validation UI. The subsequent
  workflow-only changes did not alter frontend or HTTP behavior.
- The sample CSV CLI check passed without a database, and the user confirmed
  local UI validation works. The upload smoke also covered errors and retry.
- Code diff whitespace checks passed. No real database guarantees are claimed.

Documentation consolidation checks passed: local links resolve, code fences are
balanced, superseded document references were removed, and whitespace checks are
clean. Application tests were not rerun for this documentation-only change.

The validation phase was committed as `1d9e6fe`. Metadata/writer work and this
documentation consolidation extend the original US2 pull request (#15). The local
intake work extends its branch through a separate PR; no PR is merged by this work.


### Local intake implementation record

The implemented slice follows this sequence:

- [x] Implement the five existing writer operations with persistent JSON Lines and a scoped local catalog.
- [x] Provide exact published-batch metadata and a bounded sample reader for downstream discovery.
- [x] Keep parser/import orchestration unchanged and preserve the validation-only HTTP/UI boundary.
- [x] Document publication, scope, cleanup, retry/reconciliation and filesystem limits in this guide and the maintained story plan.

Historical manual inspection for the original local-intake delivery used a
disposable local root with synthetic data:

- Nested JSON, leading-zero strings, booleans, null and metadata round-tripped;
  a separate Python process read both old and refreshed published batches.
- Source/collection IDs stayed stable on refresh; old files and publication history
  remained readable. A header-only CSV returned an empty sample.
- A 501-record collection returned 500 records without parsing a deliberately invalid
  unsampled 501st line; smaller requested limits worked. The temporary corruption
  was restored before subsequent inspection.
- Other organizations/environments, wrong source, unpublished batches and unknown
  collections were rejected. Limits 0 and 501 were rejected.
- Published writes/cleanup, incomplete publication and a foreign-scope manifest
  were rejected. Unpublished cleanup was repeatable. A non-JSON serialization
  failure left the collection incomplete and could not publish.
- Two separate processes racing both a first import and an existing source refresh
  produced one winner and one PublicationConflict; the loser did not replace the
  active pointer. This is an exercised contention scenario, not a stress suite.
- A synthetic lost acknowledgement after committed publication propagated as an
  ImportStorageError; the published batch remained readable, including after a
  later refresh replaced the active pointer. No automatic cleanup removed it.
- Truncated and malformed sampled files failed explicitly; original synthetic data
  was restored. A complete but unpublished batch did not move the active pointer.

Compilation, diff/whitespace, existing local documentation links and request-scope
review passed. No automated tests were added/run for that delivery, and the old
80-test result above was not rerun. No HTTP/browser/auth integration, Windows,
network filesystem, forced process-kill, power-loss, disk-full or broader stress
verification was performed. Only disposable data was used; no team database,
credentials or existing local storage was accessed. Temporary inspection data
was removed after review.

### Local intake review-fix record

The follow-up fixes normalize Windows storage roots to extended-length paths,
retain durable discarded-batch tombstones to prevent reuse during cleanup, and
strictly reject non-finite sampled JSON numbers. Eight regression cases failed
before the fixes. All 91 backend tests now pass on Windows, including 11 tests in
`tests/test_local_store.py`. These cover long-path imports/reopening, a deterministic
cleanup/re-stage interleaving, interrupted cleanup/retry, unknown-ID tombstones,
existing-catalog upgrade, non-finite nested values and pinned finite data.
`git diff --check` passes. Earlier manual observations and test counts above
describe their respective deliveries, not these fixes.
Windows directory-flush and power-loss behavior remain unverified.


Publication uses [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
and its [atomic commit model](https://www.sqlite.org/atomiccommit.html); record
flushes follow [Python os.fsync](https://docs.python.org/3/library/os.html#os.fsync).
These references describe mechanisms, not verification of this application's
hardware or all crash scenarios.


## Historical local-adapter HTTP integration verification

Completed in order: shared authentication/CSRF (including removal of a stale merge
registration that prevented startup), import endpoint, published source listing,
UI integration, then workflow verification. Backend tests use actual password login,
revocable sessions, disposable SQLite auth and real local intake storage; they do
not mock the writer. They cover refresh identity, validation leaving old data intact,
organization isolation, restart/reopen persistence, pinned US3 reads, storage errors,
publication conflicts and lost publication acknowledgements.

Verification: 93 backend tests passed, 1 optional PostgreSQL test skipped. TypeScript
and production build passed. Browser smoke with mocked HTTP responses passed for
multipart/CSRF, file limits, errors, saved-list reload and no duplicate row. A separate real browser-to-Flask run using disposable SQLite auth/local intake
also passed login, import, reload, same-filename refresh and invalid-refresh preservation.
This is not a live team PostgreSQL test. No team credentials
or data were accessed. Discovery and Mapping Studio UI integration remain follow-up work.


## PostgreSQL implementation verification

The initial connection probe failed inside the restricted network sandbox. A
read-only probe outside that sandbox succeeded and confirmed a non-superuser
account in its own developer database. All 10 PostgreSQL intake integration tests
then passed using randomly named temporary schemas; fixture cleanup removed them.
They covered incremental/idempotent migration preserving auth data, JSON Unicode
edge cases, 500-record sampling, scope isolation, atomic write rollback, publication
conflicts, lost acknowledgements, concurrent first imports/refreshes and real
password-authenticated HTTP upload/list requests. Existing application tables and
local intake files were not migrated or modified by these tests.

The default local suite passed 102 tests with 12 environment-specific skips; SQLite
variants use the same database adapter, not LocalIntakeStore. The PostgreSQL test
run separately executed all 10 PostgreSQL variants. No power-loss or broad load test
was performed. Apply auth-init-db to the intended application schema before normal
use. The UI/API response contract is unchanged. Nothing was committed or pushed.


## Mapping preservation API and retention (revision 0003_mapping_retention)

Apply pending migrations with the existing `auth-init-db` command before starting
the updated backend. This adds intake_fields, source_mappings and intake_pins,
plus retired_at/purged on intake_batches. Existing records and accounts remain.
Previously superseded snapshots receive a retirement timestamp at migration time
so they get the full grace period. Field profiles for older active snapshots are
built lazily on first field/mapping access, under the source lock. New uploads
profile all records in the same transaction as collection completion.

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

### Safe snapshot cleanup

Defaults, optionally configurable in the existing private backend `.env`:

```dotenv
GENLEDGE_INTAKE_KEEP_PREVIOUS=1
GENLEDGE_INTAKE_GRACE_DAYS=7
```

Both are nonnegative integers. Active data is always protected. The newest N
superseded snapshots are kept regardless of age; additional snapshots become
eligible only after the grace period measured from supersession, not upload time.
A sweep runs after successful HTTP publication in a separate transaction. Its
failure produces an import-success response with a maintenance warning and a
server log entry; it does not report a failed upload. The current upload dialog
continues to show publication success. No scheduled background worker is installed.
For a source that receives no further uploads, an administrator can run:

```powershell
.\.venv\Scripts\python.exe -m flask --app main intake-sweep --organization ORG_ID --source SOURCE_ID
```

The command uses the configured environment and policy, and is intentionally
scoped to one organization/source. It requires trusted operator database access.
For a disposable test only, set both policy values to zero to make the first
superseded snapshot immediately eligible. This permanently removes its record
payloads; do not use that setting on data you need to retain.

A sweep takes the source lock, verifies the active batch, and attempts exclusive
locks on eligible old batches with SKIP LOCKED. read_sample holds a shared batch
lock from metadata validation through record retrieval, so active reads are never
truncated by cleanup. Sweeps skip busy batches and can retry on the next import or
maintenance invocation. SQLite tests cover behavior only, not these row-lock guarantees.

Longer workflows spanning multiple reads must pin before relying on old data:

```python
store.pin_snapshot(source_id, batch_id, "discovery-job-123")
try:
    snapshot = store.published_snapshot(source_id, batch_id)
    records = store.read_sample(source_id, batch_id, collection_id, limit=500)
finally:
    store.release_pin(batch_id, "discovery-job-123")
```

Use a unique pin ID per consumer. Pins are durable, scoped and idempotent; they do
not expire automatically. A crashed consumer's pin must be explicitly released
once the operator confirms its data is no longer needed. Pin acquisition and
cleanup serialize on the batch lock; pinning already expired data fails explicitly.
Mapping rows also protect their validBatchId. In particular, needs_review mappings
keep their last usable data until the mapping is explicitly updated or deleted.

Cleanup removes intake_records rows and sets purged=true, retaining manifests,
collection/field metadata, batch IDs and publication history. published_snapshot
can still return that metadata for reconciliation; read_sample and pin_snapshot
raise SnapshotExpiredError for expired payloads. They never silently redirect to
the current batch. Metadata continues to grow and is not swept in this slice.
The legacy LocalIntakeStore remains unchanged and retains its old file snapshots.
Abandoned staging reconciliation and automatic import retries remain separate work.


Mapping/retention verification (2026-10-17): the full backend run passed 112 tests
with 24 environment-specific skips and the existing development-secret warning.
After adding the scoped maintenance-command check and final request guards, the
focused mapping/configuration run passed 16 tests with 12 skips. All 20 real
PostgreSQL variants (10 intake, 10 mapping/retention) passed in disposable schemas,
covering existing-data migration, reader locks and publication racing with cleanup.
The first PostgreSQL test selection also selected a SQLite variant that hit a
Windows temporary-directory permission error; corrected PostgreSQL-only selection
passed. Test schemas were removed. Diff whitespace checks passed. No existing
application schema, private .env, or team data was changed; no commit/push occurred.
The US5 UI remains a separate integration task. The legacy local adapter is unchanged.
