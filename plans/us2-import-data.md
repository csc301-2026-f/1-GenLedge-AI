# US2 — Import data work plan

Implementation details, decisions, test commands and the completed-work record
live in [the US2 guide](../doc/us2-import-data.md). Keep this file as the working
checklist for the whole story rather than duplicating the guide.

## Mapping preservation and snapshot retention

User approved a small US2 mapping persistence API because US5 is currently a mock.

- [x] Add per-batch field identity metadata and scoped mapping persistence/API.
- [x] Reconcile mappings atomically with publication; retain definitions and flag incompatible fields.
- [x] Add retention migration, reader locks, durable pins, automatic post-import sweep and a scoped maintenance command.
- [x] Verify preservation, failed imports, scope/CAS, retention and PostgreSQL read/publish races; update guide and smoke checks.

Default retention: active plus one previous snapshot, seven days after supersession.
Keep publication manifests; sweep record payloads only. Mappings requiring review
retain their last valid batch. Durable pins protect longer-running consumers.

## Local intake review fixes (completed)

- [x] Reproduce Windows long-path import failure, discarded-batch reuse during
  cleanup, and non-finite sampled JSON numbers with regression tests.
- [x] Normalize Windows storage roots to extended-length absolute paths.
- [x] Retain durable discarded-batch tombstones and reject reuse before staging,
  including IDs first seen through cleanup.
- [x] Reject NaN, Infinity and overflowing numeric exponents in sampled records.
- [x] Run focused and backend tests, review the diff, and record results in the
  US2 guide. Windows power-loss behavior remains outside this verification.

Verification: eight regression cases failed before the fixes. All 91 backend
tests now pass on Windows, including 11 local-store tests. Diff whitespace checks pass.

## PostgreSQL intake migration (implemented and tested)

- [x] Add versioned intake tables and database-backed writer/reader.
- [x] Switch HTTP import/list to the configured application database; no local-file fallback.
- [x] Test data preservation, isolation, publication, cleanup and HTTP flow.
- [x] Document deployment migration, existing-local-data boundary and verification limits.

Preserve all existing working changes, including the user's deleted .env.example.
Do not commit or push. Do not apply migrations to shared databases automatically.

Verification: 102 tests passed in the local suite (12 environment-specific skips).
All 10 PostgreSQL intake tests passed separately in disposable developer-owned schemas,
including row-lock publication races and the authenticated HTTP flow. Test schemas
were removed. Existing application schema migration remains a deployment step.

## Authenticated file import integration (historical local-storage phase)

- [x] Replace demo upload authentication and CSRF with shared auth.
- [x] Configure scoped local storage and add POST /api/sources/uploads.
- [x] Add GET /api/sources for published active snapshots.
- [x] Connect import UI and persistent source list with explicit error states.
- [x] Verify actual login/import/list/refresh/isolation/sample flow and frontend behavior.

That initial slice used local intake; MongoDB/DocumentDB, Mapping Studio UI integration and
final deployment verification remain separate. No commits or merges requested.

## Completed implementation

- [x] Parse and validate CSV, TSV, XLSX, XLS, JSON and NDJSON.
- [x] Enforce limits; preserve nesting; handle BOMs and duplicate/blank headers.
- [x] Add the session/CSRF-protected validation API, CLI and upload UI.
- [x] Keep integration independent of the unfinished login branch.
- [x] Define source, collection and batch metadata and the intake writer contract.
- [x] Implement validate → stage → publish orchestration.
- [x] Test refresh identity, isolation, partial writes, competing publication and
  uncertain publication outcomes with a test-only fake writer.

## Documentation consolidation

- [x] Inspect existing guides/plans and preserve uncommitted implementation work.
- [x] Combine the two guides and completed-work records in the US2 guide.
- [x] Update shared smoke-test references and remove six superseded files.
- [x] Verify links, stale references and whitespace.

## Remaining US2 work

- [ ] Agree with the database owner on storage locations, filename identity rules,
  atomic publication, durable completion markers and reader retention.
- [x] Implement the local writer; complete additional concurrency/crash verification separately.
- [x] Integrate real organization authorization and the HTTP import/persistence UI.
- [x] Implement PostgreSQL old-snapshot cleanup with reader and mapping protection.
- [ ] Implement abandoned-staging reconciliation and automatic retry/idempotency.
- [x] Add conservative field identity and preserve definitions through the approved US2 mapping API.
- [ ] Integrate the mapping UI/owner workflow with the US2 API.
- [ ] Add MongoDB/DocumentDB connections that read source data in place.
- [ ] Run end-to-end acceptance checks against real storage before marking US2 done.

## Verification status

Before this documentation consolidation: 80 backend tests passed, including 17
workflow tests; the validation UI type check, build and both browser smoke tests
also passed. Consolidation checks passed: local Markdown links resolve, code fences
are balanced, no superseded document paths remain in the searched repository
content, and `git diff --check` is clean. No code changed or tests rerun in this
documentation-only step.

## Local intake delivery

Implement the existing writer contract and a batch-pinned sample reader without changing authentication, HTTP import/UI, source parsers or US4. Records are JSON Lines files under an explicit absolute storage root outside Git. A Python-standard-library SQLite catalog in that root tracks immutable manifests, collection completion, publication history and the active pointer. This is a local adapter, not an external database or a substitute for the control warehouse.

### Success criteria

- Bind each adapter to a trusted organization/environment; isolate catalogs and hashed filesystem paths by scope.
- Stage new batches without exposing them; flush and sync each collection before recording completion. Preserve parsed values/nesting and reject incomplete/duplicate writes.
- Publish only complete batches using one SQLite compare-and-swap transaction against the expected active batch. Retain old published batches and their publication history.
- Discard only unpublished batches, retaining durable tombstones and removing catalog visibility before deleting files so cleanup interruption cannot make an incomplete batch publishable or permit batch-ID reuse.
- Read only a published source/batch/collection in the adapter's scope. Sample at most 500 records from that pinned batch without consulting a moving active pointer again.
- Keep the web path validation-only. Real identity authorization and HTTP import remain separate integration work.

### Checklist

- [x] Inspect current US2 contracts and create an isolated feature branch from its current head.
- [x] Implement the persistent local writer and record its behavior/limits.
- [x] Add the scoped published-batch and bounded sample reader.
- [x] Inspect synthetic save/read, fresh-process reads, isolation, publication conflict and failure behavior; compile and review the diff.
- [x] Finalize the existing guide/plan/manual procedures for a PR targeting us2.

SQLite BEGIN IMMEDIATE serializes publication decisions for a scope; local writes also hold that lock through file completion. This trades write concurrency for a small, explicit publication boundary. Use a single host and local disk, not network/shared filesystems. Directory fsync is performed on POSIX; Windows directory/power-loss behavior is not claimed verified. No distributed transaction, reconciliation daemon or old published-batch deletion is added.


### Historical local-delivery verification

Manual synthetic inspection covered old/new pinned reads in a fresh process,
empty collections, limits and the unparsed 501st record, organization/environment
isolation, incomplete/immutable publication, two-process first-import and refresh
conflicts, an acknowledgement lost after commit, retained publication history,
invalid serialization and truncated/malformed sampled files. Compilation and
whitespace checks passed. No automated tests were added/run; the earlier 80-test
result was not rerun. Windows, forced process-kill, power-loss, network filesystem,
HTTP/auth integration and broader crash/stress verification remain unverified.
See the finalized implementation record in the guide for details and limits.

Integration verification: 93 backend tests passed, 1 optional PostgreSQL test skipped.
TypeScript/build and mocked browser import smoke passed. A disposable real browser-to-Flask import flow also passed. Live team database
verification remains outstanding; see the guide.

Current storage: PostgreSQL via revision 0002_intake. Existing local imports are
not automatically migrated. No commit/push performed.


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
