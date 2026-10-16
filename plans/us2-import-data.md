# US2 — Import data work plan

Implementation details, decisions, test commands and the completed-work record
live in [the US2 guide](../doc/us2-import-data.md). Keep this file as the working
checklist for the whole story rather than duplicating the guide.

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
- [ ] Integrate real organization authorization and the HTTP import/persistence UI.
- [ ] Implement reconciliation, retry/idempotency and old-snapshot cleanup.
- [ ] Agree field identity with the mapping owner and preserve compatible mappings.
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
- Discard only unpublished batches, removing their catalog visibility before deleting files so cleanup interruption cannot make an incomplete batch publishable.
- Read only a published source/batch/collection in the adapter's scope. Sample at most 500 records from that pinned batch without consulting a moving active pointer again.
- Keep the web path validation-only. Real identity authorization and HTTP import remain separate integration work.

### Checklist

- [x] Inspect current US2 contracts and create an isolated feature branch from its current head.
- [x] Implement the persistent local writer and record its behavior/limits.
- [x] Add the scoped published-batch and bounded sample reader.
- [x] Inspect synthetic save/read, fresh-process reads, isolation, publication conflict and failure behavior; compile and review the diff.
- [x] Finalize the existing guide/plan/manual procedures for a PR targeting us2.

SQLite BEGIN IMMEDIATE serializes publication decisions for a scope; local writes also hold that lock through file completion. This trades write concurrency for a small, explicit publication boundary. Use a single host and local disk, not network/shared filesystems. Directory fsync is performed on POSIX; Windows directory/power-loss behavior is not claimed verified. No distributed transaction, reconciliation daemon or old published-batch deletion is added.


### Recorded local verification

Manual synthetic inspection covered old/new pinned reads in a fresh process,
empty collections, limits and the unparsed 501st record, organization/environment
isolation, incomplete/immutable publication, two-process first-import and refresh
conflicts, an acknowledgement lost after commit, retained publication history,
invalid serialization and truncated/malformed sampled files. Compilation and
whitespace checks passed. No automated tests were added/run; the earlier 80-test
result was not rerun. Windows, forced process-kill, power-loss, network filesystem,
HTTP/auth integration and broader crash/stress verification remain unverified.
See the finalized implementation record in the guide for details and limits.
