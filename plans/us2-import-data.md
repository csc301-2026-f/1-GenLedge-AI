# US2 - Import data status

Current contracts and setup: [US2 guide](../doc/us2-import-data.md).

- [x] Parse all six file formats, bounds, headers and nested document data.
- [x] Authenticated, tenant-scoped PostgreSQL import/list and upload UI.
- [x] Atomic same-filename refresh, stable metadata and pinned sample reads.
- [x] Mapping persistence/reconciliation and safe snapshot retention.
- [ ] Connected MongoDB/DocumentDB reads in place (excluded from this cleanup).
- [ ] Confirm shared scoped intake meets the client's database isolation requirement.
- [ ] Integrate discovery and Mapping Studio with real APIs (US3/US5).
- [ ] Verify deployed PostgreSQL/browser flow in the target environment.

Operational follow-ups: abandoned-stage reconciliation, explicit import
idempotency/retry policy, scheduled maintenance and metadata retention.
