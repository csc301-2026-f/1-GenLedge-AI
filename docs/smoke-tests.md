# Smoke Tests

## Import workflow contract (fake writer only)

- Action: From `src/backend`, run `.\.venv\Scripts\python.exe -m pytest tests/test_import_workflow.py -q -p no:cacheprovider`.
  Expected: Workflow tests pass without any database. They cover stable metadata,
  nested records, failed staging/writes, concurrent publication and uncertain
  publication outcomes. The fake is test-only; the UI still validates without saving.
- Contract and database adapter handoff: [US2 import guide](../doc/us2-import-data.md).

## File validation (US2, no intake database)

- Action: Install backend development requirements and run `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
  from `src/backend`.
  Expected: Parser and upload API tests pass with no database. API tests use
  main's existing demo login session.
- Action: From `src/backend`, run `.\.venv\Scripts\python.exe -m app.sources.connectors.files <file>`.
  Expected: A valid file prints collection summaries with `persisted: false`;
  an invalid file exits nonzero with a validation message. No database is needed.
- Action: Sign into the connected frontend, click Upload File, select a CSV, then
  Validate File. Repeat with a multi-sheet XLSX and nested JSON/NDJSON.
  Expected: Counts and any header corrections appear. Success says nothing is
  saved and does not navigate to discovery or add a source row.
- Action: Try an empty file, unsupported extension, file larger than 25 MB,
  malformed table row, or a sheet with more than 50,000 data rows.
  Expected: An actionable error appears; no success summary remains. A corrected
  file can be selected and validated without closing the modal.
- Action: Stop Flask, try validation, restart Flask and sign in again if needed.
  Expected: Failure is shown, and retry is possible.
- Action: Sign out and call `/api/sources/uploads/csrf` or submit an upload.
  Expected: 401. After signing in, an upload missing a valid `X-CSRF-Token` returns
  403. A token from before logout cannot be reused after signing in again.
- Action: With Playwright available, run `node tests/upload-validation-smoke.cjs`
  from `src/frontend` (optional `CHROME_BIN` specifies an installed browser).
  Expected: UI smoke passes against mocked API responses. Backend API behavior
  is covered independently by pytest.

## Development launchers

- Action: Run `./src/start-demo.sh` or `src\start-demo.bat` and open `http://127.0.0.1:5174`.
  Expected: The preserved standalone mock demo loads without requiring a Flask process.
- Action: Run `./src/start-app.sh` or `src\start-app.bat` and open `http://127.0.0.1:5173`.
  Expected: The connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite.
- Action: Stop each launcher with `Ctrl+C` on Unix or by closing its service window on Windows.
  Expected: The processes started by that launcher stop and the ports are released.


## Persistent local intake writer

Use a disposable absolute directory outside Git. Instantiate LocalIntakeStore with
trusted organization/environment and call the existing import_file with a
synthetic CSV or JSON stream, as shown in the US2 guide. These are manual
procedures, not a claim that all failure modes have been exercised.

- Action: Import nested JSON, reopen the store, and inspect active_snapshot.
  Expected: The complete metadata/IDs round-trip, raw records exist as JSON Lines,
  and strings/numbers/booleans/null/nesting retain their parsed values.
- Action: Import changed content under the same organization/environment/filename.
  Expected: Source and collection IDs remain stable, a new batch becomes active,
  and previous published files remain intact.
- Action: Stage an incomplete batch or use a stale expected batch during publish.
  Expected: Incomplete publication fails; stale publication raises
  PublicationConflict and does not replace the winner.
- Action: Write or discard a published batch; stage another scope's manifest.
  Expected: Explicit immutability/scope rejection, with existing data unchanged.
- Action: Discard an unpublished batch twice.
  Expected: Both calls finish; its catalog metadata is absent and its files are
  removed. A durable discarded-batch marker remains; staging the same ID again
  is rejected, including after reopening the store. Storage errors other than an
  already absent staging path propagate.
- Action: Discard an unknown batch ID, then attempt to stage that ID.
  Expected: Cleanup succeeds and staging is rejected by its retained tombstone.
- Action: On Windows, import and sample synthetic records using a disposable
  absolute root long enough that the resulting record path exceeds 260 characters.
  Expected: Import, catalog reopen and sampling work through the extended-length
  root. This checks path handling, not Windows power-loss recovery.

The web UI continues to return persisted:false. No database credentials, team
storage, HTTP import or source connector is needed for this internal adapter.


## Pinned intake samples for US3

Use the disposable LocalIntakeStore and returned SnapshotMetadata from the writer
steps above. Read published_snapshot(source_id, batch_id), then
read_sample(source_id, batch_id, collection_id, limit=500).

- Action: Reopen the store in a fresh Python process after an import/refresh.
  Expected: Metadata and old/new pinned samples remain readable. Reading an old
  published batch returns its own records even when a newer batch is active.
- Action: Import 501 synthetic JSON objects and request 500, then a smaller limit.
  Expected: The returned lists contain 500 and the requested smaller count. An
  invalid 501st line in a disposable copy is not parsed. Restore any modified data.
- Action: Import a header-only CSV.
  Expected: Its published collection returns an empty list, not invented fields.
- Action: Read with another organization/environment, wrong source, unknown
  collection or unpublished batch; request limits 0 or 501.
  Expected: IntakeNotFoundError for inaccessible artifacts or ValueError for limits.
- Action: Truncate or corrupt a sampled JSON line in disposable storage.
  Expected: A clear decode/row-count error, never a successful partial sample.
  Restore the data; do not perform this check on real storage.
- Action: Replace a sampled value in disposable storage with NaN, Infinity,
  -Infinity or 1e999, including a value nested in an object or array.
  Expected: Sampling rejects the non-finite value. Restore the synthetic data
  after each check; corruption beyond the requested sample is still not read.
- Action: Publish two staged batches against the same expected active version
  from separate processes, including a source that has no previous import.
  Expected: One wins; the other raises PublicationConflict and cannot clobber it.
- Action: Simulate a lost acknowledgement after publication, then refresh again.
  Expected: The old acknowledged-or-not published batch remains readable by its
  pinned ID. Checking only the latest pointer is not sufficient reconciliation.

These are documented manual checks. Recorded local observations and unverified
platform/crash/auth scenarios are listed in the guide. No real US3 discovery or
HTTP import is enabled by this storage adapter alone.
