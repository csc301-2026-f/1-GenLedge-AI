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
- [ ] Record all reproduced errors and commit the tests/error report.
- [ ] Fix reproduced defects; add a new migration if schema changes are needed.
- [ ] Run the full suite, smoke commands, and coverage; document results.
- [ ] Finalize this plan under `doc/` and commit the fixes separately.

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
comparison issues. No production implementation has been modified yet.
