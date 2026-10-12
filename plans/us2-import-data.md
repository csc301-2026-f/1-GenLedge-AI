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
- [ ] Implement the real writer and test durability, concurrency and crash recovery.
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
