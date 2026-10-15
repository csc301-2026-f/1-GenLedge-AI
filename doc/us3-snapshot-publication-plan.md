# US3 snapshot publication plan

## Scope

Connect one existing DiscoveryResult through the canonical inventory adapter and an explicit caller-owned preparation policy to Person A's InventoryRepository.save_snapshot. Reuse its transactions, organization scope, fingerprint deduplication and immutable snapshots. Add no schema, migration, HTTP, frontend or raw-data reader.

## Success criteria

- Require server-owned organization/source identity and caller-owned candidate snapshot/resource metadata.
- Require an explicit inventory preparation callback before storage; provide no implicit pass-through or independent redaction heuristics.
- Preserve discovery result semantics through the adapter and save only inventory metadata, not raw records or credentials.
- Return the inventory actually returned by the repository, including its canonical snapshot ID after deduplication.
- Let preparation/persistence failures propagate; publish nothing when preparation fails.
- Demonstrate real save/read, deduplication, changed snapshots, restart durability, organization isolation and immutability with synthetic data in disposable local PostgreSQL.
- Preserve dependency authorship and keep unrelated graph code out. Document checks and limitations precisely.

## Sequence

- [x] Inspect current persistence PR and confirm persistence-only commits match its latest source/database/migration files.
- [x] Integrate the original persistence-only dependency, retaining original authors and removing duplicated merged requirements.
- [x] Add publication orchestration and document caller policy/scope responsibilities.
- [x] Inspect behavior against disposable local PostgreSQL; finalize plan.
- [x] Commit/push C separately and update the PR description.

## Boundaries

This publishes one already-discovered resource. The callback must return inventory with the intended identities and evidence preserved, applying the application's agreed sample policy. Raw input reading, authorization decisions, sample-redaction algorithms, source listing/latest pointers, sampledCount/method persistence, reviewer resolution and downstream job orchestration remain outside this function. A successful callback is not proof of complete PII detection.

## Verification

- Reused the existing control migration and repositories in a newly initialized local PostgreSQL 16.14 cluster, reachable only by its private Unix socket with TCP disabled. No existing/team database, credentials or real source records were used.
- Published synthetic orders-v1: one resource and 14 fields, with original native type evidence and date ambiguity. The explicit example policy withheld all samples; the source discovery report retained its original samples. Scoped read matched the saved inventory.
- Retried identical metadata under orders-retry and received orders-v1; changed fixture produced orders-v2. Database inspection showed exactly those two snapshots; old paid and new currency fields remained independently readable.
- Another organization could neither read the snapshot nor publish under the same source. Reusing an occupied snapshot ID for changed content conflicted. Direct mutation of a sealed field raised PostgreSQL CheckViolation and left the original snapshot intact.
- A preparation callback failure propagated and created no source/snapshot. Re-read verified earlier data survived the rejected operations.
- A fresh Python process after database restart loaded the same inventory. Re-running the migration retained both snapshots and revision 001_us4_control_plane.
- Python compilation, frontend TypeScript check/Vite build and diff whitespace checks passed. Dependency repository/database/migration files remain unchanged from the original persistence commit.
- The disposable cluster was stopped and removed. No automated tests were added or run; inherited persistence tests were imported with their original commits. PostgreSQL 17, live application databases, HTTP, browser and model integration were not exercised.

## Dependency history

Merge 4aff77d integrates the original persistence-only history through 45e81f2. Its repository/database/migration files match the newer combined PR20 branch. Merged requirement duplicates were normalized while retaining main's stricter Alembic range. The US3 publication helper is delivered in a separate feature commit; graph code, HTTP and frontend behavior were not changed.
