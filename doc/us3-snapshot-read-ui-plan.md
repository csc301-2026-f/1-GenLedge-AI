# US3 saved snapshot API and UI plan

## Scope

Expose an authenticated, organization-scoped GET for saved inventory and replace the connected app's synthetic discovery host with a snapshot-loading container. Keep synthetic preview isolated. No ingestion, publication endpoint, resampling, migrations, routing jobs or auth-policy changes.

## Success criteria

- GET /api/sources/snapshots/<snapshot_id> uses login_required and server-derived organization identity; unknown and other-organization IDs return the same404.
- Reuse InventoryService/InventoryRepository and existing control DSN/schema names, loaded through Flask configuration. Missing configuration is an explicit503; startup does not connect or migrate.
- Return versioned inventory JSON with no-store headers and safe error messages. Expected database failures return503; unexpected errors are not swallowed.
- Validate consumed response fields, refs/counts and requested snapshot identity at the client boundary.
- Load/select resources and show fields, canonical types/native evidence, prepared samples, ambiguity and status. Never infer absent sample counts or invent raw types from native strings.
- Cancel stale requests, clear previous results when the input changes, and label reload as immutable-snapshot reading. Keep routing disabled until its separate integration.
- Inspect real login->snapshot GET->disposable PostgreSQL->browser rendering plus unauthorized/not-found/config/error cases. Typecheck/build/compile; document exact limits.

## Sequence

- [x] Inspect current auth, persistence, UI and configuration boundaries.
- [x] Add source blueprint/configuration and scoped snapshot GET.
- [x] Add typed client/display projection/container and connect App.
- [x] Inspect HTTP/browser flow using synthetic data in isolated local stores; clean up.
- [x] Finalize docs/plan, commit/push D and update PR16.

## Verification

- Real HTTP against an isolated Flask app with synthetic DB-backed application users and a disposable Unix-socket-only PostgreSQL 16.14 control store: anonymous401, own-snapshot200/version1/14fields, identical404 for missing and other-organization IDs, forged organization query still404, logout204 then401, and no-store headers. Multi-resource inventory returned8/6/4fields; empty resource returned0.
- Missing control configuration returned explicit503 in an isolated app. Stopping only the disposable control DB produced503 snapshot_unavailable and a safe OperationalError class log; restart recovered normal reads.
- Browser walkthrough with real auth cookies and API/database data showed14fields, date ambiguity, canonical/native type evidence and unknown status; LINES plus number filter produced one field; switching the three-resource snapshot to orders.lines[] showed6fields. Empty and404 states cleared old rows. Database-down503 and recovery worked in the browser.
- A separate known-synthetic sample snapshot displayed quoted leading-zero IDs, numbers, booleans and null without double quoting. Reload used the same saved ID, confirmed in server logs. No browser error/warn diagnostics were reported.
- Python compile, frontend TypeScript check, production build and whitespace checks passed. React review covered controlled state, stable keys, request cleanup and labels. The existing auth smoke navigation was adjusted for the new entry; it was not run and no new automated tests were added.
- Used only disposable synthetic auth/control data. The smoke process isolated its configuration from the team's .env and the existing generic USER collision. Normal launcher/team-host/PostgreSQL17, timeout/race fault injection, arbitrary malformed HTTP bodies and full backend test suite were not verified. No auth policy was changed.
- Temporary browser tab, Vite/Flask processes, PostgreSQL cluster and synthetic stores were closed/stopped/removed. A screenshot of the successful UI was retained outside the repository.

## Remaining work

Connect the displayed persisted snapshot ID to a fully composed routing runtime (E). Source listing/latest lookup, real sample reader/re-sampling, raw upload persistence, sample-count storage and reviewer-controlled ambiguity resolution remain separate work.
