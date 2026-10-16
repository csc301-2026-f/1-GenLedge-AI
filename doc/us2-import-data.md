# US2 — Import data

This is the single implementation and handoff guide for US2. The
[working plan](../plans/us2-import-data.md) tracks remaining work; shared manual
checks are in [smoke tests](../docs/smoke-tests.md).

## Current scope

File parsing/validation, the validation API/UI, metadata, import orchestration and
a concrete local intake writer and published-batch sample reader are implemented. Internal callers can persist
parsed records using LocalIntakeStore and read a pinned published batch. The web UI remains validation-only: it does
not call the import service, save records, create a source, or advance discovery.
The source list/database connection flow remain prototypes. Real authorization,
HTTP import/UI and US3 discovery integration are still required for complete US2.

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
message. The workflow suite has 17 tests; the full backend suite has 80 tests.
The optional `-p no:cacheprovider` avoids local pytest cache permission warnings
without changing test execution.

For the web flow, run `src\start-app.bat` from the repository root, open
http://127.0.0.1:5173, and sign in with a nonempty email/password (demo login).
Choose Upload File → Choose File → Validate File and use the sample CSV. Success
shows counts and corrections and explicitly says nothing is saved.

Neither the parser nor the current web API needs a database. This branch's demo login
stores a user in the signed session cookie; it is not production credential
validation or organization authorization. There are no imports from the
unfinished `feature-login` branch.

## Code walkthrough

1. `connectors/files.py:parse_file(filename, stream)` bounds the file read and
   chooses a parser by extension. Text is decoded as UTF-8 with optional BOM.
2. Table parsers normalize headers and validate each data row. Document parsers
   preserve objects and arrays. A failure anywhere raises `FileValidationError`;
   callers never receive a partially validated workbook.
3. The result is a `ParsedFile` with `ParsedCollection` objects containing full
   records. The import service passes these to an intake writer after
   parsing returns successfully. Do not use the summary as the import payload.
4. `routes.py` checks the demo session, verifies its upload-specific CSRF token,
   and returns `summary()`. Its session check is the boundary to update when the
   shared authentication helper lands; no parser changes should be necessary.
5. `UploadFileModal.tsx` displays validation progress, errors, counts and corrections.
   It does not navigate or add a fake saved source on success.

## API

Two US2 endpoints are currently implemented on the Flask backend (default port
5000). The frontend uses relative `/api/...` URLs, proxied by Vite on port 5173.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/sources/uploads/csrf` | Obtain the session's upload CSRF token |
| POST | `/api/sources/uploads/validate` | Parse and validate one uploaded file without saving it |

Request order: sign in through the existing auth API, fetch the upload token,
then send the file with that token using the same session cookie. There is no
HTTP endpoint for persisting imports or registering database connections yet;
the writer interface is an internal Python contract, not an HTTP API.

### GET /api/sources/uploads/csrf

- Requires a signed-in session; no request body or CSRF header is needed.
- Returns 200 with `{"csrfToken": "<token>"}`, or 401 if signed out.
- Creates a token if the session has none; otherwise returns the existing token.
- Tokens are stored under `sources_csrf_token` in the session. Existing login
  and logout clear the session, invalidating the token for subsequent requests.
- Returns `Cache-Control: no-store`.

### POST /api/sources/uploads/validate

- Signed-in demo session and `X-CSRF-Token` from
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
  in metadata. These are parser keys, not a finalized mapping identity contract.
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

There is intentionally no HTTP import route yet. This branch's demo login cannot supply
real organization authorization. The eventual route must authorize scope before
calling this function and must parse the actual uploaded bytes again rather than
trusting an earlier browser validation summary.

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
cleanup needs reader retention rules and is not part of this service.

## Persistent local writer

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
  Duplicate batch/collection IDs fail through catalog constraints.
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
- `discard_unpublished` first removes the catalog manifest/completion rows, then
  removes its files. Interrupted cleanup leaves unreachable staging files rather
  than a publishable manifest with missing records. Repeating cleanup is safe;
  real filesystem errors propagate. Old published batches remain immutable.

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

No external database, new runtime dependency, Flask configuration or HTTP endpoint
is added. This branch still uses its old demo authentication for validation;
current shared authentication must be integrated before enabling web persistence.

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
an empty list. Malformed JSON/non-object lines, missing files or truncation before
the expected sampled count fail explicitly instead of producing empty/partial
success. Corruption beyond the sample is not inspected. The manifest's row_count
is the full parsed batch count; len(records) is only the sampled count.

Upload batch IDs and US3 inventory snapshot IDs remain distinct. This adapter
provides parsed records plus stable source/collection/batch identity, not a
DiscoveryResult or an InventoryView. It does not publish discovery metadata,
provide source-listing endpoints or change the upload UI.

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
refreshes. Header metadata is retained for later field matching. This does not
implement field discovery, stable duplicate-header identity, type compatibility,
or mapping reconciliation. Those rules must be agreed with the mapping owner;
the import service does not delete or rewrite mappings.

## Verification and database handoff

The fake writer verifies orchestration with fault injection: invalid later sheets,
partial writes, failed staging and cleanup, competing publishers, and lost publish
acknowledgements. It deep-copies records to model isolation and rejects incomplete
publication. It is a synchronous test double, not evidence of real database
atomicity, durability, crash recovery or thread/process safety.

The concrete local adapter is now available; the fake writer remains useful only
for orchestration checks. Filename identity, reader retention, authenticated HTTP
import/UI, reconciliation, retry/idempotency, mapping preservation and external
source connections remain integration work. Real multi-process contention and
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

Recorded manual inspection used a disposable local root with synthetic data:

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
review passed. No automated tests were added/run for this delivery, and the old
80-test result above was not rerun. No HTTP/browser/auth integration, Windows,
network filesystem, forced process-kill, power-loss, disk-full or broader stress
verification was performed. Only disposable data was used; no team database,
credentials or existing local storage was accessed. Temporary inspection data
was removed after review.


Publication uses [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
and its [atomic commit model](https://www.sqlite.org/atomiccommit.html); record
flushes follow [Python os.fsync](https://docs.python.org/3/library/os.html#os.fsync).
These references describe mechanisms, not verification of this application's
hardware or all crash scenarios.
