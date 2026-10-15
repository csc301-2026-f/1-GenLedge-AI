# Smoke Tests

## Development launchers

- Action: Run `./src/start-demo.sh` or `src\start-demo.bat` and open `http://127.0.0.1:5174`.
  Expected: The preserved standalone mock demo loads without requiring a Flask process.
- Action: Run `./src/start-app.sh` or `src\start-app.bat` and open `http://127.0.0.1:5173`.
  Expected: The connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite.
- Action: Stop each launcher with `Ctrl+C` on Unix or by closing its service window on Windows.
  Expected: The processes started by that launcher stop and the ports are released.

## US4 routing (Person D)

Prerequisite: wire A/B/C through the runtime factory described in
[`doc/us4-person-d-api.md`](../doc/us4-person-d-api.md), run A's migrations and
seed, and start the worker. Without this wiring, expect a clear 503 routing error.
The automated `src/frontend/tests/routing-smoke.cjs` exercises the UI with HTTP
fixtures; it is not evidence of the real database/model smoke below.

- Action: Sign in, open Schema Discovery, enter a persisted snapshot ID and click
  **Find where this data belongs**.
  Expected: A 202 response opens the job; queued/running states appear, then the
  saved proposals (very fast jobs may finish before the first poll).
- Action: Inspect proposals and findings.
  Expected: Confidence, rationale, merge keys, new/reused flags, coverage,
  ambiguous-date blocker, and resolved fake/live mode come from API responses.
- Action: Reject one table and refresh.
  Expected: The job first shows Edit requested/Revising with disabled decision
  controls and the previous package. After worker processing, the same job reopens
  with the applied rejection and other tables intact.
- Action: Submit the same decision again.
  Expected: The same Idempotency-Key header and edit ID are replayed safely; an
  already-submitted notice appears, no extra revision is produced, and the latest
  package still contains decisions for other tables.
- Action: Interrupt the network during creation or an edit, reconnect and retry.
  Expected: The original request ID is reused; no duplicate job or edit results.
- Action: Inspect a failed job and click Retry routing when available.
  Expected: A new job is created for the same snapshot; the failed job is retained.

Execution on the Person D branch: automated HTTP-fixture browser flow passed;
full manual PostgreSQL/LangGraph flow is blocked by unmerged A/B/C dependencies.

Browser setup from `src/frontend`: `pnpm install --frozen-lockfile`, then
`pnpm exec playwright install chromium` and `pnpm test:routing`. An installed
Chrome may instead be selected with `CHROME_BIN`; no global Playwright package
or NODE_PATH is required.
