# US4 persistence function audit

## Objective

Exercise every Person A public function and its meaningful failure paths using
local PostgreSQL. Commit reproducible errors and regression tests first, then
fix them in a separate commit. Preserve shared contracts and ownership boundaries.

## Steps

- [x] Inspect the clean task branch, implementation, existing tests, and guidance.
- [x] Run the existing suite and measure persistence function/branch coverage.
- [x] Add tests for uncovered public operations, malformed input, replay identity,
  rollback, isolation, and migration behavior; reproduce failures before fixes.
- [x] Record all reproduced errors and commit the tests/error report.
- [x] Fix reproduced defects; no schema change or migration is needed.
- [x] Run the full suite, smoke commands, and coverage; document results.
- [x] Finalize this plan under `doc/` for the separate fix commit.

## Constraints

Use the existing isolated local PostgreSQL test cluster. Do not push without
explicit user authorization: the prior automatic approval review rejected that
publication action. Do not modify README files, shared contracts, routes, graphs,
model adapters, or proposal validation rules.

## Verification

Baseline: 65 passed; original persistence modules show 95% combined line/branch
coverage. Added audit suite: 20 failed, 30 passed before fixes. Five reproduced
defects are recorded in `doc/us4-persistence-function-audit.md`. Read-only parallel
root-cause reviews confirmed schema/container boundary mistakes and JSON replay
comparison issues.

Error/test commit: `9bf95e1`. Fixes change only database configuration validation,
catalogue container checks, and normalized JSON replay comparison. No migration
or shared-contract change is needed.

Final suite: **115 passed** (50 new audit cases). Test-only combined coverage is
99%; including actual migration, fixture, and two smoke CLI invocations yields
**100% statement and branch coverage** across eight persistence/smoke modules
(423 statements, 106 branches). Both smoke processes read the same job and
revision; the second replays the committed tool result without invoking its
factory. Diff whitespace checks pass. Full details and reproduction commands are
in `doc/us4-persistence-function-audit.md`.

Fix commit message: `fix(us4): harden persistence validation and replay identity`.
Commit identity is recorded in Git and the delivery response. The temporary
PostgreSQL test server is stopped after verification.
