# US4 Person A execution plan

Branch: `us4/person-a-source-persistence`, based on the fetched `us4/integration`.

## Scope

Implement immutable PostgreSQL source inventory and persistence adapters for the
US4 graph and application service workstreams. Use `app.agent.contracts` only;
leave graph nodes, adapters, routes, UI, and proposal validation to their owners.

## Decisions

- Alembic/SQLAlchemy manage versioned migrations, as required by the harness plan.
- Capability repositories use psycopg transactions and a dedicated control schema.
- Constraints/triggers protect immutable snapshots; locks and unique keys serialize
  job, revision, tool, and edit replay across processes.
- The synthetic fixture stores field metadata and up to three safe samples only.
- PostgreSQL tests use disposable local schemas and a separate test DSN.
- Document public interfaces and a runnable function smoke test for Persons B/D.

## Checklist

- [x] Read required plans, architecture, contracts, and repository guidance.
- [x] Fetch and verify the base and create the requested branch.
- [x] Implement the control schema and Alembic migration entrypoint.
- [x] Implement inventory persistence, fixture, and inventory service.
- [x] Implement catalogue/job/revision/finding/coverage/tool/edit repositories.
- [x] Test limits, immutability, concurrent replay, and cross-process visibility.
- [x] Document setup and function examples; run `python -m pytest tests`.
- [x] Review implementation and finalize this plan in `doc/`.

## Verification

Final full test run: `python -m pytest tests` from `src/backend`: **65 passed**,
no skips or warnings, against isolated local PostgreSQL 17.6 (Python 3.13.5).
The test schemas were automatically removed after each test.

Verified `python -m app.common.migrations`, fixture seeding, and standard Alembic
upgrade/current commands; Alembic reports `001_us4_control_plane (head)`.
Ran `python -m scripts.smoke_persistence` in two separate Python processes:
both saw three resources, 18 fields, the same job/revision, and the reject edit.
The second reported `created=False`, `tool_replayed=True`, `factory_calls=0`.
`git diff --check` passed. No README, shared contract, route, graph, model adapter,
frontend, or deterministic proposal validator was modified.

## Delivery

Commit message: `feat(us4): add source inventory persistence`. Commit identity and
push result are reported with delivery rather than embedded in its own contents.
The function guide and limitations are in `doc/us4-source-persistence.md`.
