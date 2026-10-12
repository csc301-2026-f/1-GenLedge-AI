# US2 — Import data

This is the single implementation and handoff guide for US2. The
[working plan](../plans/us2-import-data.md) tracks remaining work; shared manual
checks are in [smoke tests](../docs/smoke-tests.md).

## Current scope

File parsing/validation, the validation API/UI, metadata, the writer interface,
and import orchestration are implemented. The source list and database connection
flow remain prototypes. The web UI only validates: it does not save records,
create a source, or advance discovery. The import service is tested through a fake
writer confined to tests; it is not connected to an HTTP import route or database.
US2 is not complete until real storage and the remaining integrations are verified.

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

Neither the parser nor the current web API needs a database. Main's demo login
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

`POST /api/sources/uploads/validate`

- Signed-in demo session and `X-CSRF-Token` from
  `GET /api/sources/uploads/csrf` required. The token endpoint also requires a
  signed-in session. Both endpoints return `Cache-Control: no-store`.
- Tokens are stored under `sources_csrf_token` in the session; existing login
  and logout clear the session, invalidating the token for subsequent requests.
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
The storage adapter still chooses the authorized client's database; a safe name
is not an authorization check. No customer records are augmented with internal
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

There is intentionally no HTTP import route yet. Main's demo login cannot supply
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

When storage is ready, implement the Protocol, agree on exact filename identity,
and run integration tests against the chosen database for transactional publication,
durable acknowledgements, BSON/JSON key and size constraints, reader retention,
concurrent first imports, refresh conflicts and crash recovery. Then integrate
the authorized HTTP import route and persistence UI. Mapping reconciliation,
retry/idempotency, old-snapshot cleanup and MongoDB/DocumentDB connections that
read in place also remain outstanding; see the working plan for the checklist.

## Finalized plan and completed-work record

The completed phases were implemented in this order:

1. Build the six-format parser, validate all collections before returning, and
   add focused boundary/corruption tests.
2. Connect a protected validation-only endpoint and modal. Adapt the integration
   to main's demo authentication so US2 can progress independently of login work.
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
documentation consolidation extend the same US2 pull request (#15). Real database
integration remains follow-up work; this delivery does not merge the PR.
