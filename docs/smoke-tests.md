# Smoke Tests

## Import workflow contract (fake writer only)

- Action: From `src/backend`, run `.\.venv\Scripts\python.exe -m pytest tests/test_import_workflow.py -q -p no:cacheprovider`.
  Expected: Workflow tests pass without any database. They cover stable metadata,
  nested records, failed staging/writes, concurrent publication and uncertain
  publication outcomes. The fake is test-only; database intake is covered by the import API tests.
- Contract and database adapter handoff: [US2 import guide](../doc/us2-import-data.md).

## File validation (US2, no intake database)

- Action: Install backend development requirements and run `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
  from `src/backend`.
  Expected: Parser tests pass without storage; API tests use disposable SQLite auth
  and database intake, with real password/session checks.
- Action: From `src/backend`, run `.\.venv\Scripts\python.exe -m app.sources.connectors.files <file>`.
  Expected: A valid file prints collection summaries with `persisted: false`;
  an invalid file exits nonzero with a validation message. No database is needed.
- Action: Sign into the connected frontend, click Upload File, select a CSV, then
  Import File. Repeat with a multi-sheet XLSX and nested JSON/NDJSON.
  Expected: Counts and corrections appear after publication and the saved source
  list refreshes. Discovery does not start automatically.
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
  Expected: A redacted database status summary appears first and the launcher pauses for confirmation. After confirmation, pending Alembic migrations apply; then the connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite. If the connection check or migration fails, neither service starts.
- Action: Initialize the auth database, provision a user, then sign in with an incorrect password and the correct password at port 5173.
  Expected: The incorrect password is rejected; the correct password opens Sources.
- Action: Copy `src/backend/.env.example` to `src/backend/.env`, fill in `HOST`, `PORT`, `DATABASE`, `USER`, and `PASSWORD`, then run `auth-db-check`.
  Expected: Flask reports the expected PostgreSQL role and database without printing the password; TLS reports the configured connection state.
- Action: Run `auth-init-db` against a fresh developer database.
  Expected: The initial Alembic migration creates the auth tables and records the migration revision.
- Action: Refresh after login, sign out, then refresh again.
  Expected: The session restores before logout and stays signed out afterward.
- Action: Send an auth POST without a valid `X-CSRF-Token`.
  Expected: Flask returns 403.
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

The internal adapter needs no external database credentials. The current web UI
uses authenticated HTTP imports; see the current flow at the end of this document.


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


## Authenticated file import (current web flow)

Use this flow for the integrated UI. Keep parser/validation endpoint checks for API regressions.
Configure your authorized PostgreSQL connection, run auth-init-db to apply intake
migrations, use a provisioned account, and start backend/frontend. Use disposable synthetic files only.

- Upload a valid CSV through Import File. Expect saved confirmation and a source row.
- Reload and restart the backend with the same database/environment configuration. Expect the row to remain.
- Upload changed data under the same filename. Expect one row with updated counts.
- Upload malformed data under that filename. Expect an error and unchanged saved data.
- Sign in as a user from another organization. Expect no access to the first organization's sources.
- With the published source/batch/collection IDs, call PostgresIntakeStore.read_sample;
  expect at most 500 records and stable reads of the old batch after refresh.
- Simulate unavailable storage or lost publication acknowledgement using disposable tests.
  Expect an explicit failure/uncertain outcome, no false success and no automatic retry.

Database connection and discovery buttons stay disabled until connected to their
real services. The automated browser smoke mocks HTTP; backend tests exercise actual auth/storage.
A separate disposable browser-to-Flask run also verified real login, import, reload,
same-filename refresh and invalid-upload preservation with SQLite auth/local intake.


## PostgreSQL intake migration

- Run auth-init-db twice against your developer database; expect the migration to
  be repeatable and existing accounts/sources to remain intact.
- Import synthetic nested JSON and inspect intake_records.payload. Expect records
  in PostgreSQL, no local JSON Lines writes, and an active batch in intake_sources.
- Change only GENLEDGE_INTAKE_ROOT; expect no effect on PostgreSQL intake.
- Configure no PostgreSQL connection; expect import/list 503 rather than local-file fallback.
- Run the opt-in disposable-schema tests described in the US2 guide. PostgreSQL
  concurrency and JSON edge-case checks are not covered by SQLite test results.


## Mapping preservation and snapshot retention

Apply 0003_mapping_retention in a disposable development environment. Use the
US2 guide's API examples with a real login/session and CSRF token.

- Upload orders.csv with id/name headings; GET its fields and save a mapping of
  name with a target/transform/note. GET mappings confirms status=valid.
- Reupload the same filename with reordered headings and different values. Expect
  stable field IDs, unchanged definition and a new validBatchId.
- Remove or rename the mapped heading, or change a nested JSON field's type.
  Expect needs_review, unchanged definition and the old validBatchId retained.
- Map one of two duplicate headings. Reupload: expect review rather than silently
  transferring the mapping to another generated column key.
- Submit malformed data and attempt a stale mapping PUT/DELETE. Expect no lost
  mappings; stale expectedBatchId returns 409. Missing CSRF returns 403. A second
  organization's session cannot read or change the first source's mappings.
- In disposable storage only, set GENLEDGE_INTAKE_KEEP_PREVIOUS=0 and
  GENLEDGE_INTAKE_GRACE_DAYS=0, restart and refresh a source. Unreferenced old
  payloads disappear; the new active batch remains readable. Restore defaults.
- A needs_review mapping protects its last-valid batch. Explicitly re-save against
  new fields or delete the mapping, then run intake-sweep for that org/source.
- Pin an old batch with the adapter before sweeping. It stays readable until the
  pin is released. After sweeping, its manifest remains and reading its payload
  raises SnapshotExpiredError rather than returning a different batch.
- Run tests/test_mapping_retention.py; select `postgresql and not sqlite` when
  running the disposable real-PostgreSQL variants. Row-lock races require PG.
