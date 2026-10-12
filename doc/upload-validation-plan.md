# US2: file parsing and validation

## Scope
Implement database-independent parsing for CSV, TSV, XLSX, XLS, JSON and
NDJSON, a protected validation-only API, and a working upload-validation UI.
No intake persistence, source replacement, mapping changes or database connectors.

## Decisions
- File limit: 25,000,000 bytes. Record limit: 50,000 per collection for all formats.
- JSON accepts one object or an array of objects. NDJSON accepts objects per line.
- Preserve JSON nesting. Text tables retain strings. Blank rows are ignored.
- Normalize duplicate/blank headers deterministically, retaining header metadata.
- Validation returns summaries only; full records remain an internal parser result.
- Target branch is `us2`, based on `main`, independently of unfinished `feature-login`.
- Use main's demo session check at the sources boundary. Uploads own their CSRF
  token endpoint. No database or changes to the auth module are needed.

## Main-branch adaptation
- [x] Resolve the three stash conflicts while retaining main's authentication.
- [x] Replace feature-login dependencies and adapt API/browser tests.
- [x] Run checks on us2 and update the documentation and final plan copy.

## Steps
- [x] Inspect current code and authentication integration.
- [x] Add parser and focused tests, including boundaries and corrupt inputs.
- [x] Add authenticated, CSRF-protected multipart validation endpoint.
- [x] Connect upload modal to validation with clear unsaved-state messaging.
- [x] Run backend tests, frontend checks and UI smoke tests.
- [x] Document API, manual verification, decisions and remaining US2 work.

## Verification
- Backend on us2: 63 tests passed, including all existing demo auth tests and
  token/session lifecycle coverage. No database is needed by these tests.
- Frontend: TypeScript no-emit check and Vite production build passed.
- New upload browser smoke passed using installed Edge and bundled Playwright.
  Verified multipart/CSRF, client limits, summaries, header corrections, failed
  requests, retry, and no navigation. Inspected the resulting screenshot.
- CLI successfully parsed `tests/fixtures/orders.csv` without any database.
- Both `git diff --check` and `git diff --cached --check` passed.
- Existing `auth-smoke.cjs` passed on main's demo authentication contract.
- Git reports no unmerged files. The three resolved conflict paths were staged;
  the auth client now matches main exactly. No commits or pushes were made.
- us2 starts at f0ad114, the current local main/origin-main commit; feature-login
  commits were not included. Parsing and validation remain independent of that branch.

## Delivery
- Implementation and API walkthrough: `doc/upload-validation.md`.
- Final plan copy: `doc/upload-validation-plan.md`.
- Intake persistence and the remaining US2 integration are intentionally deferred.
