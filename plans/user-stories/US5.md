# US5 — Review and modify mappings

**Status:** Proposed implementation plan — planning document only. Nothing in this file is implemented.
**Acceptance-criteria source:** `src/frontend/src/imports/GenLedge_Connector_MVP_User_Stories.pdf` (US1–US7), quoted not paraphrased.
**Shared design:** state, budgets, the graph, the phase gates and the D2 critical path are defined once in the master plan, [`../LANGGRAPH_HARNESS_PLAN.md`](../LANGGRAPH_HARNESS_PLAN.md). This file links to it instead of repeating it.

*PDF story:* "As a data reviewer, I want to review and modify source-to-warehouse mappings in order to ensure that my data is mapped correctly before it is loaded."

**Where the plan defines the shared parts:** master §4.3 (the edit→approve flow), §4.4 ("who may resume"), §5.2–§5.3 (state and contracts), §5.7 (edits as constraints), §5.9 (checkpointing and recovery), §6.2 (`await_human`, `revise`, `approved`), §6.4 (routing predicates and the `409` guards), §9.6 (the status vocabulary), §11.7 (R1/R5/R6), §12.2 (`proposal_edits`, `proposal_approvals`).

---

## 1. Acceptance criteria, status, and the tasks that close them

| AC | Acceptance criterion (source wording) | Current status (repository evidence) | Tasks | Blocking decision |
| --- | --- | --- | --- | --- |
| **US5-AC1** | Open a visual Mapping Studio for a pipeline | **Partial.** `MappingScreen.tsx` exists and is reachable from the sidebar, but it is addressed by nothing: its title string hard-codes `AMER_Orders_2026Q3.xlsx`, and it takes no pipeline or job identifier | `D2-FE-2`, `D2-BA-1` | — |
| **US5-AC2** | Display source fields and target warehouse columns | **Partial.** Both lists exist, but the source list comes from a *different screen's* private constant (`DiscoverScreen.tsx`'s `FIELD_DATA`), so the two sides are not guaranteed to agree | `D2-BA-1`, `D2-FE-2` | One package contract (master §5.3) must be the single source for both |
| **US5-AC3** | Create a mapping manually | **Missing.** `"Add Mapping"` is rendered with no `onClick` | `D2-FE-2`, `D2-BA-2` | — |
| **US5-AC4** | Delete a mapping | **Partial.** `deleteMapping` exists against component state | `D2-FE-2`, `D2-BA-2` | — |
| **US5-AC5** | Edit an existing mapping | **Partial, with a defect.** The `Edit Mapping` modal exists, but saving assigns `confidence: undefined`, silently discarding the AI's confidence — a direct contradiction of US4-AC7 once the proposal is real | `D2-FE-2`, `D2-BA-2` | — |
| **US5-AC6** | Persist mapping changes so they remain after leaving and reopening the studio | **Missing.** All edits live in component state; a reload discards them | `D2-PF-1`, `D2-BA-2`, `D2-FE-2` | **This is the criterion that makes persistence a D2 P0**; `DC-5` (tenancy for D2) |
| **US5-AC7** | Switch between sibling target tables using the studio tabs | **Partial.** Tabs for `fact_orders`, `fact_order_lines`, `dim_customers` exist over a fixture map | `D2-FE-2` | — |
| **US5-AC8** | Inspect and correct AI-generated mappings | **Partial.** Confidence is displayed for fixture rows; "correct" writes to component state | `D2-LG-1`, `D2-FE-2`, `D2-LG-4` | Requires a real proposal (`D2-LG-1`) to correct |
| **US5-AC9** | Identify unmapped source fields and unmapped target columns | **Partial.** `unmapped` counts come from fixtures in two screens; no coverage computation exists | `D2-DM-1`, `D2-FE-2` | — |
| **US5-AC10** | Use the AI mapping feature to suggest mappings with confidence, reasons, and gaps | **Partial (fixtures only).** Confidence and `reason` exist; "gaps" has no representation | `D2-LG-2`, `D2-DM-1` | `DC-2` (gap/reason vocabulary) |
| **US5-AC11** | Use the Mapping Assistant to make bounded natural-language mapping changes for the selected pipeline | **Not implemented.** `MappingScreen.tsx:59` echoes after 800 ms and states "This is a prototype demo." | **Post-D2** (`Q9`) | `D2-FE-7` keeps it honestly labelled; deferring it does not weaken AC3–AC9 |
| **US5 gap** | "Some mapping and transformation save failures are currently swallowed by the studio instead of being surfaced clearly to the reviewer." | **Current, as described.** Save handlers do not surface failure | `D2-BA-3`, `D2-FE-3` | — |

**Status vocabulary:** **[Current]** exists in the tree · **[Gap]** described in a document but not implemented · **Partial** a UI affordance or fixture exists without the contract behind it. `US5-AC6` is the one criterion here that cannot be met by frontend work at all: it is the reason the D2 slice needs a real database, and the reason `D2-PF-1` is on the critical path rather than deferred.

---

## 2. Current implementation status, in detail

| Surface | Evidence | What it actually does |
| --- | --- | --- |
| `src/frontend/src/features/mappings/MappingScreen.tsx` | `INITIAL_MAPPINGS` keyed `fact_orders` (5 rows), `fact_order_lines` (4), `dim_customers` (2); row shape `{src, tgt, type, transform?, confidence?, ambiguous?}` | Renders fixtures from component state. Tabs, delete and the edit modal all mutate that state only. |
| `MappingScreen.tsx` — `Edit Mapping` save | assigns `confidence: undefined` | **Actively destructive**: it discards the AI's confidence on any edit, which contradicts US4-AC7 the moment the proposal is real. |
| `MappingScreen.tsx` — `"Add Mapping"` | rendered without `onClick` | An inert control: the AC's affordance is visible but not connected. |
| `MappingScreen.tsx` — Assistant panel | `MappingScreen.tsx:59` echoes the prompt after an 800 ms timer and prints "…This is a prototype demo." | The AC10 capability is explicitly a prototype; `D2-FE-7` must keep that label rather than let it drift into an implied feature. |
| `src/frontend/src/shared/ui.tsx` `STATUS_MAP` | keys are exactly `ready, success, active, connected, parked, pending, scheduled, failed, error, running, ingesting, processing, draft, manual, new, proposed`; `StatusPill` falls back to `'neutral'` | The review states this story needs — `awaiting_review`, `edit_requested`, `approval_requested`, `cancelling` — are not in the map, so they would render as neutral pills with no distinction. `D2-FE-5` fixes this against the master plan's canonical list. |
| `src/frontend/src/features/auth/client.ts` | the only HTTP client; 15 s `AbortController` | Nothing in the studio calls it. Every save is local. |
| `src/backend/app/mappings/` | `__init__.py` docstring only | No service, no routes, no models, no validation. |

---

## 3. Remaining work by layer

| Layer | What is missing | Tasks |
| --- | --- | --- |
| **Frontend** | The studio never fetches; edits live in component state; `Add Mapping` is inert; saving destroys confidence; the review states have no rendering; save failures are swallowed | `D2-FE-2`, `D2-FE-3`, `D2-FE-5` |
| **API** | No package endpoint, no edits endpoint, no approve/cancel endpoint, no `409` guards, no role check | `D2-BA-1` (cross-story), `D2-BA-2`, `D2-BA-3` (cross-story) |
| **Backend / domain** | No persistence of revisions or edits, no immutability rule, no coverage computation | `D2-PF-1` (cross-story), `D2-DM-1` (cross-story) |
| **LangGraph / model** | `await_human`, `revise` and `approved` do not exist; nothing can suspend or resume | `D2-LG-4` |
| **Persistence** | No control tables, no migration, no idempotency key column, no approval audit row | `D2-PF-1` (cross-story) |
| **Failure handling** | No failure envelope, no distinction between "blocked" and "broken", no reason rendering | `D2-BA-3`, `D2-DM-1` |
| **Deployment** | The review gate is not reachable without the D2 deployment target | `D2-D-1` (cross-story) |

---

## 4. Tasks owned by this story

| ID | Task | Layer | Priority | Depends on | Owner | Completion evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `D2-BA-2` | `PUT …/{id}/edits` (requires an `Idempotency-Key`), `POST …/{id}/approve`, `POST …/{id}/cancel`, with the `409 edits_pending` and `409 blockers_present` guards | API | **D2 P0** | `D2-BA-1` | `<backend-owner>` | Tests for a duplicate key, an approve-while-pending-edits and an approve-while-blocked |
| `D2-LG-4` | The human-edit resume: `decision="edit"` → `revise` with the edits as binding constraints, on a durable saver | LG / FH | **D2 P0** | `D2-BA-2`, `D2-PF-1`, `D2-LG-1` | `<agent-owner>` | An edited mapping is applied and observable after a reload; a second identical submission changes nothing |
| `D2-FE-2` | Wire `MappingScreen.tsx` to the package: source fields against target columns, unmapped lists, tabs across sibling tables, working create/edit/delete persisted through `PUT …/edits`, and a reload that restores the saved state | FE | **D2 P0** | `D2-BA-1`, `D2-BA-2`, `D2-LG-4` | `<frontend-owner>` | Add Mapping works; editing preserves confidence; a reload shows the saved mapping |
| `D2-FE-3` | Failure surfacing: replace the swallowed save failures, render invalid-reference and unmapped reasons, distinguish `409 edits_pending` from `409 blockers_present`, and carry the ambiguous-date badge through to the studio | FE | **D2 P0** | `D2-BA-3`, `D2-DM-1` | `<frontend-owner>` | A forced server error produces a visible message and a retry, not a silent no-op |

Shared tasks this story depends on, defined in master §16.5: `D2-PF-1` (control tables — **US5-AC6 is the criterion that makes it P0**), `D2-BA-1` (package endpoint), `D2-BA-3` (error envelope), `D2-DM-1` (validation, coverage, reasons), `D2-LG-1` (the proposal being reviewed), `D2-FE-5` (status vocabulary), `D2-TS-2` (contract tests), `D2-TS-4` (R1/R5 regressions).

**Post-D2 and deliberately not in the D2 slice:** the Mapping Assistant (`US5-AC11`, `Q9`), role-restricted approval if `DC-5` resolves to a single role, multi-process resume, the supersession-history view ("a running pipeline is unaffected by a later edit"), and R6's viewer-cannot-approve guard.

---

## 5. Contracts and data model

### 5.1 Review-package contracts

Defined in `app/agent/contracts.py` **[Proposed]**; the shared conventions (`StrictModel`, harness-assigned fields, versioning) are in master §5.3.

```python
class Critique:                 findings: list[CriticFinding]
class CriticFinding:            # MODEL-FACING: what a model can know
                                kind: str; target: Identifier; severity: Severity
                                message: str (1–500); material: bool
                                # NOTE: no `revision` field — a model cannot know it
class CriticFindingRecord(CriticFinding):   # STORED: adds the harness-owned key
                                revision: int   # assigned by semantic_review, never by the model
class ValidationFinding:        severity: Severity; code: str; target: Identifier
                                message: str; revision: int   # assigned by the producing code
                                source: "validation"
class HumanEdit:                edit_id: str        # server-assigned idempotency key
                                kind: EditKind; target: Identifier
                                payload: dict; note: str | None
                                # reviewer identity lives in proposal_edits, not in state
class FailureInfo:              code: str; message: str; retryable: bool
                                detail: dict
```

The split between `CriticFinding` and `CriticFindingRecord` is not stylistic. Routing filters findings by the revision they reviewed (`master §6.4`'s `blockers_for_current`, regression R3); a model-writable `revision` would let a model defeat that filter, and a model-*invisible* one has to be assigned somewhere — so the model-facing type simply has no such field, and the stored type requires it. `Critique.model_json_schema()` is what the prompt injects, so harness-owned fields stay out of the model's view automatically.

**[Proposed] `EditKind`** — the plan's own rules and tests imply at least: retarget a mapping, rename a target, set or clear an operation, remove a mapping or table, and withdraw a previously submitted edit (master §5.7). The **exact enum is part of the Phase-1 contract freeze**; it is enumerated here rather than silently invented, and `DC-2`'s reason-code work is the natural place to close it, since an inapplicable edit must produce a stated reason.

### 5.2 Job and revision status (canonical list: master §9.6)

Eleven job statuses exist. The five this story's surface must render correctly, and why:

| Status | Why the studio must distinguish it |
| --- | --- |
| `awaiting_review` | The only state in which approve is even attempted; it is **not** the same as "the job is fine" — blockers may still be present |
| `edit_requested` | An edit is persisted but the graph has not consumed it yet. Without this state, "the reviewer clicked save and nothing happened" is silent |
| `approval_requested` | An approval was accepted and the node's own re-validation is running; if the process dies here, the durable claim + stale-heartbeat path resumes it |
| `cancelling` | A stop was requested but has not taken effect — distinct from `cancelled` so an operator can tell the two apart |
| `blocked` | **Not a failure.** The harness worked and the proposal is not yet good enough; the reviewer's routes are edit or abandon |

---

## 6. Rules this story must not weaken

### 6.1 The edit-delivery contract (master §5.7, six steps)

| Step | Owner | Rule |
| --- | --- | --- |
| 1 | Reviewer | `PUT /api/mappings/jobs/{id}/edits` with an `Idempotency-Key` header and one or more edits |
| 2 | API | Validate the **role**; validate each edit's shape against its `kind`; compute `before_hash`/`after_hash` against the current revision; insert `proposal_edits` rows keyed by `(job_id, edit_id)`; set the job row to `edit_requested`; return `202`. A repeated `Idempotency-Key` returns the original result and inserts nothing |
| 3 | Worker | Claim and resume the graph on the job's thread with the edit decision |
| 4 | `await_human` | Append the edits to `human_edits` — deduplicated by the `append_unique_edits` reducer — and route to `revise` |
| 5 | `revise` | Apply them as **binding constraints** and persist revision *n+1*; the job returns to `awaiting_review` |
| 6 | Reviewer | Approve — and the request is **refused with `409 edits_pending`** while an edit exists that the current revision does not incorporate |

Step 6 is the load-bearing one. Both `MappingScreen.tsx` and `RouteScreen.tsx` are edit-then-approve screens, so without the guard the natural UI flow would record the edits and then approve the **unedited** revision — producing an immutable version that contradicts the reviewer's explicit decision, with no error anywhere, because both requests succeeded. That is the guarantee this story exists to protect.

### 6.2 Corrections that must survive into the studio

- **Editing must not destroy confidence.** US5-AC5's current implementation sets `confidence: undefined`; `D2-FE-2`'s evidence explicitly requires that editing preserves it.
- **Edits go through validation like any other change.** An edit is never written into the draft directly, so "changing a target schema field invalidates its dependent mappings and checks" is enforceable: an edit that changes the model draft bumps `model_draft.revision`, `mapping_draft.based_on_model_revision` no longer matches, and the router sends the job to `map_sources` instead of leaving stale mappings in place (master §4.5, §5.7).
- **An inapplicable edit is never dropped.** A `remove` of a table that mappings depend on, or an edit with an unknown target, is recorded and returned to the reviewer as an unresolved item on the next revision. It keeps blocking approval until it is applied or explicitly withdrawn — a reviewer never silently loses a correction.
- **`revise` may not contradict an edit.** If the model proposes something a human edit forbids, the edit wins and the contradiction is recorded as an unresolved item; the package is not marked clean.
- **Edits are append-only.** The audit trail is `human_edits` plus `proposal_edits` (reviewer, role, timestamp, idempotency key, before/after hashes). Nothing is mutated in place.
- **Approval is idempotent and re-validated.** `approved` re-runs the deterministic checks itself; if a blocker is now present it records `review_decision`/`rejected_by_guard`, leaves `approval_ref` unset, and returns to `await_human` **with the new blocker list in the payload** so the reviewer is told why rather than shown an identical screen.

---

## 7. Error paths, security constraints and recovery

| Situation | Required behaviour |
| --- | --- |
| Save fails (the US5 gap) | A visible error with a retry. `D2-BA-3` gives every 4xx/5xx a `{"error": {"code", "message"}}` body (the envelope `app/auth/routes.py` already returns); `D2-FE-3` renders it. A swallowed failure is an AC failure |
| Approve with unapplied edits | `409 edits_pending`, **the graph is never resumed**, and the response names the pending edit ids |
| Approve with blockers | `409 blockers_present`, with the blocker codes |
| A blocker appears between the API's check and the node's re-validation | The node records `rejected_by_guard` and re-interrupts with the blocker list; the job does not end `approved` |
| Duplicate edit submission | One `proposal_edits` row and one `edit_applied` event per `edit_id`; `human_edits` holds one entry; the second resume is a no-op or `409`; exactly one revision is produced |
| Viewer attempts to edit or approve | `403` before any graph call; no approval row; no resume. `reviewer_role` is stored on the audit rows so the check is attributable |
| Two actors approve concurrently | `(revision_id, reviewer, decision)` is unique; the second approval returns the existing version |
| Cancel races a resume | Both are conditional status updates on the same row: whichever commits first wins, the loser sees zero rows updated and returns `409`. A winning cancel ends the run at the next node boundary |
| Checkpoint lost before a resume | Reconstruction from the control DB, re-entry at `await_human` on a **fresh** thread, `proposal_jobs.active_thread_id` repointed. Reviewer decisions recorded before the loss are still present |
| Prompt injection reaches the reviewer's screen | Untrusted source text is delimited and rendered as data; the reviewer is the last line of defence, which is why an unapplied edit and a visible blocker list matter more here than anywhere else |

**Recovery boundary specific to this story:** the durable package is what makes a multi-day review pause survivable, so the *review package must be readable without the graph*. A reviewer opening the studio after a restart reads persisted rows; only the resume needs the checkpointer. If the D2 slice runs without a durable saver, that must be labelled as debt (`DC-7`), because it removes the property this story is about.

---

## 8. Tests and observable pass criteria

| Test | Assertion (from the master plan's R1/R5/R6 and the AC list) |
| --- | --- |
| `test_path_human_edit_not_lost` (**R1**) | With the job `awaiting_review`, submit an edit and then approve as the same actor: approve is refused `409 edits_pending` (or the API forces the edit resume first); the persisted revision contains the reviewer's value; `proposal_edits` shows `edit_applied`, not merely `edit_received` |
| `test_path_duplicate_edit_submission` (**R5**) | The same body with the same `Idempotency-Key` twice, then the same body with a different key: one row and one `edit_applied` per `edit_id`, one `human_edits` entry, exactly one revision, and the second resume refused or a no-op |
| `test_path_viewer_cannot_approve` (**R6**) | `POST /approve` and `PUT /edits` as a viewer return `403`; no approval row; no resume; no `review_decision` written at all, because no decision was accepted |
| `D2-FE-2` reload test | Edit a mapping, reload the page, and the saved value — **including confidence** — is still shown |
| `D2-BA-2` contract tests | Duplicate key, approve-while-edits-pending, approve-while-blocked; the error envelope shape for each class; no model call and no network |
| `D2-FE-3` failure test | A forced server error on save produces a visible message and a retry |
| Master §11.3 graph-integration cases | Reviewer edits then approves in the same round → the edit is applied by a resume before approval is considered; approve with blockers → `409`; re-validation failure after an accepted approval → back to `await_human` with `rejected_by_guard`; cancel mid-run → `cancelled`; the graph never ends `approved` without a human decision |

Run with `py -3 -m pytest tests` from `src/backend/` (`python` is not on `PATH` — master §14.4). **No CI exists in this repository today**, so no criterion here may cite "CI enforces it" until `D2-TS-3` lands.

**Explicitly not claimed:** none of these tests has been written or run; no graph has ever suspended or resumed; no reload has preserved anything.

---

## 9. Demonstration script for US5

Steps 6–9 of the master plan's end-to-end scenario; step 7 is a *deliberate* failure demonstration.

| Step | Action | Observable result | ACs |
| --- | --- | --- | --- |
| 6 | Open the repeating array's proposal from the routing results | Target column, merge key and any candidate date operation are shown, and the ambiguous-date marker survives into the studio | AC8, AC10 (partially — "gaps" needs `DC-2`) |
| 7 | Try to apply a `date_format` while the field is still flagged ambiguous | The attempt is **blocked, with an explanation**. This is the expected result, not a bug: the product rule is that an ambiguous date stays text until its interpretation is known | AC8 |
| 8 | Correct the mapping manually and save | The correction is saved; a page reload still shows it; the source-side unmapped list and the target-side unmapped columns both update | AC3, AC4, AC5, AC6, AC9 |
| 9 | Submit the same edit twice | The second submission changes nothing and reports success | AC6 (idempotency) |

Step 8 is also where the US5 swallowed-failure gap is demonstrated as closed: a save failure must show a visible error and a retry. The script must say that the Mapping Assistant is **not** implemented (AC11) and that the schedule modal does nothing — `D2-FE-7` exists so that no screen claims a capability the code does not have.

---

## 10. D2 scope, and what is out

| Horizon | Content |
| --- | --- |
| **D2 P0** (by 2026-10-23) | AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9 and the swallowed-failure gap, via `D2-BA-2`, `D2-LG-4`, `D2-FE-2`, `D2-FE-3` plus the shared `D2-PF-1`, `D2-BA-1`, `D2-BA-3`, `D2-DM-1`, `D2-FE-5`, `D2-TS-2` |
| **D2 P1** | `D2-TS-4`'s R1/R5 regressions; the supersession-history view |
| **Not met in D2** | AC10's "gaps" until `DC-2` is decided; AC11 (Post-D2 by decision, not by omission) |
| **Post-D2** | the Mapping Assistant as a bounded second graph; role-restricted approval and R6 if `DC-5` resolves to one role; multi-process resume; "a running pipeline is unaffected by a later edit" |

Cut order, if the schedule slips (master §17.2): `D2-FE-5` and the supersession history first (cosmetic). **No cut in this story may remove the `409 edits_pending` guard or the edit idempotency key** — those are the two mechanisms that make the review gate honest, and both are named as required in master §12.4.

---

## 11. Unresolved questions, owners, deadlines, consequences

| # | Question | Owner | By | If unresolved |
| --- | --- | --- | --- | --- |
| `DC-5` | Persistence and tenancy for D2: the control tables, and whether the demo is single-organization with a single role | `<backend-owner>` + `<product-owner>` | Oct 13 | AC6 is undemonstrable and the review gate cannot persist. R6 becomes a documented deferral: the test is marked skipped with this as its reason, and **no phase may claim the "approval by a viewer is impossible" guarantee** |
| `DC-2` | The reason-code and gap vocabulary for invalid references, unmapped fields and AI-proposed "gaps" | `<product-owner>` + `<backend-owner>` | Oct 13 | `D2-DM-1` emits free text: AC9 and AC10 are met in substance but not machine-checkably, and the studio can only render prose |
| `DC-3` | Partial-success semantics when one table's proposal fails | `<product-owner>` + `<backend-owner>` | Oct 14 | Step 5 of the demo is dropped and US4-AC11 is reported as not demonstrated |
| `Q5` | Is the `origin/feature-login` persistence (SQLAlchemy + psycopg + `Organization`) reinstated, and do US1's admin/viewer roles exist with them? | `<backend-owner>` + `<security-owner>` | Phase 0 to decide; **Phase 6** to have in place | Contracts keep `organization_id` and `reviewer_role`, backed by one seeded organization and one role in development. The tenant check is then **present but untested**; approval records cannot be attributed to a role — an audit gap rather than a functional one, but a real one |
| `Q9` | Is the Mapping Assistant in scope for this iteration? | `<product-owner>` | Phase 6 | It stays deferred; the structured-edit flow — the part AC5/AC6/AC8 actually need — is unaffected |
| Phase-1 contract review | The exact `EditKind` enumeration and the `409` guard's precedence when edits *and* blockers are present | `<agent-owner>` + `<backend-owner>` | Phase 1 | Both are implemented as written here; a later change is a contract version bump plus a migration for persisted edits |

No question in this table is decided by this document. Each has an owner slot, a deadline, and a stated consequence, so shipping without an answer is a visible, accepted risk rather than an accidental one.
