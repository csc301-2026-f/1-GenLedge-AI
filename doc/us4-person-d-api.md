# US4 Person D: API and frontend integration

Branch: `us4/person-d-api-frontend`, based on `origin/us4/integration` at
`ca87e2a` (shared contract freeze). No A/B/C branches were merged by Person D.

## Current status

Implemented: the four HTTP endpoints, request validation and authentication,
job lifecycle orchestration, explicit worker dispatch, frontend HTTP client,
job restoration after refresh, and persisted package/decision rendering.
All domain types are imported from `app.agent.contracts`; the HTTP package
composition is in `app.common.api_schemas`.

**Not yet a runnable PostgreSQL/LangGraph integration.** The integration base has
no A repository/inventory, B graph, or C validator implementation. The service
uses explicit injected boundaries. Missing composition returns HTTP 503
`routing_not_configured`; it never substitutes a production in-memory repository
or fabricated routing results. Test doubles exist only under `tests/`.

## HTTP endpoints

All routes require the existing signed-cookie login and return `Cache-Control:
no-store`. Errors use `{error: {code, message, details}}`. Demo username scopes
reads/writes because the current auth system assigns the same `demo-user` ID to
every login. This is demo isolation, not production organization authorization.

| Endpoint | Request | Result |
| --- | --- | --- |
| `POST /api/mappings/jobs` | `Idempotency-Key` (1–200 characters), `{source_snapshot_id: string or null, catalog_ref?: string or null}` | `202 {job_id, status}`. Null snapshot uses the explicitly configured demo snapshot. Missing/empty/unknown inventory is rejected. |
| `GET /api/mappings/jobs/{job_id}` | Cookie session | Canonical job status, snapshot ID, resolved `fake`/`live` mode, safe failure information. |
| `GET /api/mappings/jobs/{job_id}/package` | Cookie session | `{payload, status, failure}`; payload is null until published. |
| `PUT /api/mappings/jobs/{job_id}/edits` | `{edit_id, target: table_id, decision: "accept" or "reject"}` | `Idempotency-Key` is required. Returns `202 {job_id, edit_id, status: "edit_requested", payload: null, replayed}`. The worker applies the decision and republishes; unrelated tables are preserved. |

Reusing a creation key with different inputs returns `409 idempotency_conflict`.
Exact edit replays return their original pending receipt (with `replayed: true`);
different input under either the same request key or edit ID returns `409
edit_conflict`. The repository stores both identifiers atomically. Replaying an
applied edit never resets status or applies it again. The client reads the latest
package and resumes polling after an edit receipt, so historical receipts cannot
hide newer decisions. While pending, the previous package remains visible.
Table decisions do not remove findings or authorize warehouse execution.

## Composition required from integration

`MappingService` in `app/mappings/service.py` accepts:

- `repository`: Person A adapter implementing `RoutingRepository` (see its
  atomicity requirements, especially `create_job`, `claim_job`, `publish`, and
  `request_edit`, `claim_edit`, and `publish_edit`). Storage must persist model/mapping revisions, findings,
  coverage, decisions, failure and status; ownership applies to every lookup.
- `inventory(owner, snapshot_id)`: authorize the immutable snapshot, then call
  A's inventory reader; return the canonical `InventoryView` or None.
- `run_graph(job_id, snapshot_id, catalog_ref)`: B's graph wrapper returning
  canonical `ModelDraft` or a safe `FailureInfo`. It must use the resolved mode,
  tool replay and budgets supplied by B. No request/session data goes to it.
- `project(draft, inventory, catalog_ref)`: C's projection/validation/redaction
  wrapper returning `RoutingReviewPackage`. It includes the safe model draft,
  mapping draft, findings, coverage, and C-computed `is_new` flags. Resolve an
  authorized catalogue before invoking C; do not invent business rules here.
- `resume_edit(job_id, package, edit)`: the review-workflow adapter, called only
  by `execute` on the worker. Consume the persisted edit, preserve unrelated valid
  tables, assign the new application-owned revision, and return the revised
  `ModelDraft` or safe `FailureInfo`. Projection/validation is rerun before
  `publish_edit` atomically publishes and marks the edit consumed. If the callback
  is absent, edit requests return 503 without recording an unprocessable edit.
- `model_mode`: B's resolved `fake` or `live` value, not the unresolved `auto`.
- `default_snapshot_id`: optional A-seeded demo snapshot identifier.

Configure a callable `MAPPING_SERVICE_FACTORY(app)` in Flask config, or set
`GENLEDGE_MAPPING_RUNTIME_FACTORY=your_module:build_service` to that callable.
The named module must exist in the integrated application; no placeholder module
is provided. It returns a fully composed `MappingService`.

For single-process D2 development, set `GENLEDGE_AGENT_INLINE_RUN=1` to opt into
the two-thread executor. The runtime enters the Flask application context in the
worker and logs only the resolved model mode. Graph work never runs in the
request thread. For an external worker, configure a quick durable queue callable
`MAPPING_DISPATCH(owner, job_id)` and invoke `service.execute(owner, job_id)` in
the worker. The repository claims queued jobs atomically before graph execution. For edits,
`request_edit` commits the audit row, original receipt and `edit_requested` state
before dispatch; `claim_edit` atomically moves it to `revising`. New edits while
pending/revising are rejected (exact replays remain valid). A dispatch failure
returns a safe 503 and retains the pending edit: retrying the same request
re-enqueues it. Multiple queue deliveries are safe because claiming is atomic.
The old package and unconsumed edit remain available if resume fails.

PostgreSQL migrations, connection variables and fixture setup remain Person A's
responsibility; this branch defines no replacement schema or database settings.
`GENLEDGE_MODEL_MODE=auto|live|fake` remains Person B's responsibility. The frontend
shows the persisted resolved mode without any provider configuration.

## Frontend behavior

Schema Discovery takes an explicit snapshot ID or the configured D2 default;
its existing discovery rows are visibly labelled illustrative. Clicking **Find
where this data belongs** creates the job and opens its status. The routing screen
polls active jobs and displays validated mappings, per-column confidence,
rationale, merge keys, new/reused flags, blockers, coverage and decisions. It has
loading, queued/running, awaiting-review, edit-pending/revising, blocked, failed,
retry and connection-error states. Lifecycle pills have deliberate colors and
readable labels. Decision controls are disabled until edits finish.
`ROUTE_DATA` is removed from the live routing screen. The standalone demo is intact.

Session storage contains job/request IDs scoped to the login, never review
packages. Refresh restores the job and reads its current server state. Network
retries retain idempotency IDs; a new decision intent receives a fresh edit ID.
If session storage is disabled, IDs survive only within the current page lifetime.
The US4 screen does not advance into the still-mocked US5 Mapping Studio.

## Verification

From `src/backend` with dependencies installed:

```sh
python -m pytest tests
```

From `src/frontend`:

```sh
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm build
pnpm exec tsc --noEmit
pnpm test:routing
```

Playwright is pinned in devDependencies and the lockfile. The install command
above downloads its compatible Chromium browser (Linux CI may need
`pnpm exec playwright install --with-deps chromium`). Alternatively, set
`CHROME_BIN` to an installed Chrome executable and skip the browser download.
It starts its own Vite server and uses intercepted HTTP responses.

Backend tests cover 202/non-inline creation, idempotency and conflicting keys,
snapshot validation, ownership, job claiming, concurrent requests, persisted
package/decision reads across fresh app instances, blocked/ready/failed states,
replay/conflicts, and safe errors. The repository is a serialized in-memory test
double: these tests do not prove durability across OS-process or database restarts.

Browser smoke covers login, network-retry request IDs, queued/running, confidence,
new/reused tables, ambiguous-date and invalid-reference blockers, rejection,
refresh restoration, replay without losing an unrelated accepted table, model
mode and failure/retry rendering.

## Remaining D2 limitations

- Full manual smoke, real persistence/restart visibility, actual fake-model tool
  loop, and live-provider behavior await A/B/C integration and composition.
- The opt-in thread executor is for D2 only: process crashes can strand jobs;
  durable queue/outbox dispatch, worker recovery and bounded admission need the
  integrated deployment path.
- Snapshot selection is explicit; live discovery/connector selection is not
  integrated on this contract-only base.
- US5 approval/revision and US6 warehouse execution/populated-table protection
  are outside this branch. Accept is a recorded review decision, not approval.

## Original Person D verification results (2026-10-13)

- Backend: `python -m pytest tests` — **43 passed**, including 13 new routing tests.
- Frontend: `pnpm build` — passed; `pnpm exec tsc --noEmit` — passed.
- Browser: `node tests/routing-smoke.cjs` with installed Chrome — passed using
  HTTP fixtures. This verifies UI behavior, not the real graph or PostgreSQL.
- `git diff --check` — passed.
- Full manual integration smoke — not run: A/B/C are absent from the integration
  base. The runtime factory and real adapters still need to be connected.

## PR #18 review follow-up (2026-10-14)

Addressed the five review requests: asynchronous edit_requested/resume lifecycle,
required edit Idempotency-Key validation and propagation, frontend retry headers,
pinned Playwright dependency plus reproducible setup, and distinct lifecycle pills.
The integration adapter now needs `request_edit`, `claim_edit`, `publish_edit`
and the `resume_edit` callback described above instead of synchronous save_decision.

Verification: 52 backend tests passed; TypeScript and production build passed;
updated HTTP-fixture browser smoke passed. A separate temporary frontend copy
with no node_modules passed `pnpm install --frozen-lockfile` and `pnpm test:routing`
using CHROME_BIN, without NODE_PATH or a globally resolved Playwright package.
Tests cover header/payload conflicts, pending state before worker consumption,
concurrent claim/replay, dispatch retry after app reconstruction, preservation of
unrelated tables and decisions, background-thread resumes, and refusing to mark
an edit applied if the workflow returns the old revision. Real persistence and
graph integration remain dependent on the adapters; these are boundary tests.
