# US6 — Transform and load data

**Status:** Proposed implementation plan — planning document only. Nothing in this file is implemented.
**Acceptance-criteria source:** `src/frontend/src/imports/GenLedge_Connector_MVP_User_Stories.pdf` (US1–US7), quoted not paraphrased.
**Shared design:** the graph, state, budgets, the phase gates and the D2 critical path are defined once in the master plan, [`../LANGGRAPH_HARNESS_PLAN.md`](../LANGGRAPH_HARNESS_PLAN.md). This file links to it instead of repeating it.

*PDF story:* "As a data reviewer, I want GenLedge to transform and load mapped source data into the warehouse in order to produce clean, structured data for analytics."

**Where the plan defines the shared parts:** master §3.1 and §3.5 rule 6 (the execution boundary — `runs` must never import `app.agent`), §4.2 (module responsibilities), §5.3 (the contracts the executor consumes), §6.2 (`validate`'s two US6 blockers), §12.2 (`proposal_versions` — the immutable approved version), §12.3 Phase 7.

**This story has no model in it.** Every step below — compile, expand, coerce, merge, count — is deterministic code. US6-AC8's merge behaviour and US6-AC9's runner/Glue parity are only meaningful if the path is reproducible, so a model anywhere in it is a defect, not an optimisation.

---

## 1. Acceptance criteria, status, and the tasks that close them

| AC | Acceptance criterion (source wording) | Current status (repository evidence) | Tasks | Blocking decision |
| --- | --- | --- | --- | --- |
| **US6-AC1** | Allow a reviewer to run a pipeline immediately | **Missing.** `RunScreen.tsx`'s `Run Now` calls `runNow()`, which appends to a scripted log array on `setTimeout` timers | `D2-BA-4`, `D2-FE-4` | `D2-DM-3` |
| **US6-AC2** | Read the configured source and apply saved mappings and transformations | **[Gap].** No executor exists; `app/runs/__init__.py` is a docstring | `D2-DM-3` | `D2-DM-2`, `D2-PF-1` |
| **US6-AC3** | Write clean, typed records into the client's warehouse schema | **[Gap].** No target warehouse, no DDL path, no type coercion | `D2-DM-3` | Target schema created from the approved version |
| **US6-AC4** | Record extracted and loaded row counts | **Partial (cosmetic).** The scripted log prints `Est. Source Documents: 48,203`; nothing is counted | `D2-DM-3`, `D2-BA-4`, `D2-FE-4` | Counts must be **persisted**, not logged |
| **US6-AC5** | Allow one source document to produce multiple warehouse rows when repeating data is expanded | **[Gap].** US3's known gaps note that "leaves and whole arrays are the usable mapping units", so `orders.lines[]` is expressible but nothing expands it | `D2-DM-3`, `D2-DM-1` | `DC-3` (partial-success and repeating-field rules) |
| **US6-AC6** | Support the documented transformation rules: the 12 operations listed in §2 of this file | **Missing.** `RunScreen.tsx`'s `TRANSFORMS_LIST` renders four rule strings; no operation is implemented or testable | `D2-DM-2` | The vocabulary is already frozen (§2 here) — **do not redefine it** |
| **US6-AC7** | Use predictable behavior for unmapped/optional target fields | **Undefined.** No document states whether an unmapped nullable target is `NULL`, dropped, or defaulted. The `null_if`/`default_value` operations imply the mechanism but not the rule | `D2-DM-4` | **Decision** `DC-6`, owned by the product owner |
| **US6-AC8** | Use the target merge key so repeat loads do not unintentionally duplicate logical records | **Missing, and the current gap is on record.** US6's own gaps say "the current row runner appends instead of merging on the merge key"; `doc/backend-architecture.md` requires staging and merge | `D2-DM-3` | `D2-DM-1` must first validate that a merge key exists |
| **US6-AC9** | Keep repeating-field semantics consistent between the application runner and the Glue execution path | **Not demonstrable.** No Glue path exists, and `doc/backend-architecture.md` keeps it "a future option, not an MVP dependency" | `D2-DM-4` (specification only) | **D2 must report this AC as specified, not demonstrated** |
| **US6-AC10** | Prevent more than one repeating field from being expanded for a single target table | **Missing.** No check exists | `D2-DM-1` | — |

**Three current-implementation gaps the PDF names explicitly** — the source text is US6's own known-gaps list, and each must be reported as it stands, never as fixed:

| Gap | D2 status |
| --- | --- |
| A **500-document cap** on the row runner | A **fixture-size** non-issue for D2 (the seeded source is smaller). It must **not** be reported as fixed |
| **Appending instead of merging** on the merge key | `D2-DM-3`'s core work. Reproducing it is a hard failure — the demo's step 12 exists to show the row count does not grow |
| A Glue path that will support staging plus merge while the application row runner does **not** match | `D2-DM-4` (specification) and Post-D2 for the implementation |

**Status vocabulary:** **[Current]** exists in the tree · **[Gap]** described in a document but not implemented · **Partial** a UI affordance or fixture exists without the contract behind it. Two criteria here (`US6-AC9`, and `US6-AC10`'s check) have **no code path to demonstrate at all**; neither may be reported as met because a related prototype renders something similar.

---

## 2. The canonical transformation vocabulary

This section is the single definition of `TransformOp` in the plan; nothing else may restate it. US6's source lists exactly these twelve operations.

| # | Operation | Semantics |
| --- | --- | --- |
| 1 | `uppercase` | Text to upper case |
| 2 | `lowercase` | Text to lower case |
| 3 | `trim` | Remove leading/trailing whitespace |
| 4 | `date_format` | Parse a source date string under an **explicit** format and emit a typed date |
| 5 | `concat` | Concatenate two or more source fields into one target field |
| 6 | `default_value` | Substitute a literal when the source value is null/absent |
| 7 | `strip_currency` | Remove a currency symbol/formatting and yield a number |
| 8 | `null_if` | Force null when a condition matches (e.g. a sentinel like `"N/A"`) |
| 9 | `replace` | Literal find-and-replace within a value |
| 10 | `split_take` | Split a delimited value and take one part |
| 11 | `map_values` | Map a closed set of source values onto target values |
| 12 | `round_number` | Round a numeric value to a given precision |

```python
class TransformOp(str, Enum):
    UPPERCASE = "uppercase"; LOWERCASE = "lowercase"; TRIM = "trim"
    DATE_FORMAT = "date_format"; CONCAT = "concat"; DEFAULT_VALUE = "default_value"
    STRIP_CURRENCY = "strip_currency"; NULL_IF = "null_if"; REPLACE = "replace"
    SPLIT_TAKE = "split_take"; MAP_VALUES = "map_values"; ROUND_NUMBER = "round_number"
```

### 2.1 The three-way vocabulary conflict, and how it is resolved

Three vocabularies exist in the repository and they do **not** agree:

| Source | Vocabulary |
| --- | --- |
| `doc/agent-harness-architecture.md` (its illustrative example at line 149, e.g. `"operations": ["parse_timestamp"]`) | A **structural** vocabulary: `cast`, `normalize`, `parse_timestamp`, `deduplicate`, `join`, `flatten`, `derive` |
| The US6 source (this story) | The twelve operations above |
| `src/frontend/src/features/runs/RunScreen.tsx`'s `TRANSFORMS_LIST` | Four free-text rule strings |

`TransformOp` is fixed to US6's twelve, and the architecture document's vocabulary is mapped onto it by the **normative translation table** below. This is not a preference: the document's own example JSON is not implementable as written, so a plan that claimed it validated would either fail permanently or force `TransformOp` to adopt terms no other component uses.

| Architecture-document term | Expressed as | Note |
| --- | --- | --- |
| `cast` | The **target attribute's `SourceType`**, plus type coercion at load | Not an operation: a cast is a property of the target column, not a step in a pipeline |
| `normalize` | Partially: `trim`, `lowercase`, `uppercase`, `map_values`, `default_value` | The document's single term is several distinct operations; the parts are what is implementable |
| `parse_timestamp` | `date_format` | Identical intent; the plan's name is the one the product source uses |
| `deduplicate` | `Table.key` + a validation **warning** | Deduplication is a consequence of declaring and merging on a key, not a per-value operation |
| `join` | `Mapping.join_path` | A join is a mapping-level decision with evidence requirements, not a value transform |
| `flatten` | A **separate table** with an explicit grain | Deliberate and lossy in the general case; it is a modelling decision the reviewer makes, not a transform the model applies |
| `derive` | **Not expressible — by design** | There is no operation that computes a new value from other values. A derived column is either a `concat`, a `map_values`, or a modelling problem the reviewer must resolve |

**Guard against drift:** the conformance test (master §11.8) asserts that this table is **exhaustive and total** — every transform name appearing in `doc/agent-harness-architecture.md`, in the frontend fixtures and in `TransformOp` maps to a row, each row names its target representation, and the non-expressible cases (`derive`, and the lossy `flatten`) are marked as such rather than silently dropped. The test fails when a new vocabulary term appears anywhere without a documented translation. It deliberately does **not** assert that the architecture document's example JSON validates.

Two rules that follow from the table, both enforced in `validate` (master §6.2):

- **An operation outside the twelve is a blocker**, not a warning: a model that writes `flatten` or `parse_timestamp` gets a `ValidationFinding`, and the package cannot be approved with it.
- **A `date_format` on a field still flagged `ambiguous` is a blocker.** The product rule is that `03/04/2026` stays text until its interpretation is known — US3 detects the ambiguity, US4 accounts for it, US5 lets the reviewer correct it, and US6 applies the explicit format only once that has happened.

---

## 3. Current implementation status, in detail

| Surface | Evidence | What it actually does |
| --- | --- | --- |
| `src/frontend/src/features/runs/RunScreen.tsx` | `TRANSFORMS_LIST` (four rule strings); `runNow()` appends to a scripted log array on `setTimeout` timers; the log prints `Est. Source Documents: 48,203` | A simulated run. No HTTP, no executor, no count. `Run Now` reports success because the script says so. |
| `src/backend/app/runs/` | `__init__.py` docstring only | No routes, no execution module, no worker, no scheduler. |
| Target warehouse | no DDL path, no staging, no merge, no connection | Does not exist. |
| `src/backend/tests/` | 6 test functions / 18 collected items, all auth/app | Nothing covers transforms, loading, counts or merge behaviour. |

---

## 4. Remaining work by layer

| Layer | What is missing | Tasks |
| --- | --- | --- |
| **Frontend** | `Run Now` is a simulation; progress, counts and failure states are scripted; the transform list is copy | `D2-FE-4` |
| **API** | No `POST /api/runs`, no run read endpoint, no counts in a response, no failure semantics | `D2-BA-4` (cross-story), `D2-BA-3` (cross-story) |
| **Backend / domain** | The whole deterministic core: compiler, executor, coercion, expansion, merge, counts | `D2-DM-2`, `D2-DM-3`, `D2-DM-4` |
| **LangGraph / model** | **Nothing** — deliberately. The only graph-side work is the approved-version handover, which is `D2-LG-4`/`D2-LG-1`'s approval step | — |
| **Persistence** | Run records, count storage, the immutable `proposal_versions` row the executor reads | `D2-PF-1` (cross-story) |
| **Deployment** | The target schema must exist in the deployed snapshot | `D2-D-1` (cross-story) |

---

## 5. Tasks owned by this story

| ID | Task | Layer | Priority | Depends on | Owner | Completion evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `D2-DM-2` | The transform compiler and the twelve operations of §2, as pure functions | BD | **D2 P0** | — | `<backend-owner>` | One unit test per operation plus a table-driven conformance test over §2's list and the translation table |
| `D2-DM-3` | The D2 executor: read the seeded source, apply the approved mappings, expand exactly one repeating field, coerce types, write to the target schema, merge on the merge key, count extracted/loaded rows, and make a re-run idempotent | BD | **D2 P0** | `D2-BA-4`, `D2-DM-1`, `D2-DM-2` | `<backend-owner>` | A re-run of an unchanged run leaves the row count unchanged and produces no duplicate logical rows |
| `D2-DM-4` | The unmapped/optional-target rule and the Glue-parity specification, written once and shared | BD | **D2 P0** (rule only) | `DC-6` | `<product-owner>` + `<backend-owner>` | A written rule with a test for each case (`NULL`, defaulted, dropped); the Glue half is a specification, **not** code |
| `D2-BA-4` | `POST /api/runs` → `202 {run_id}`; `GET /api/runs/{id}` → status, extracted/loaded counts, and an actionable error | API | **D2 P0** | `D2-PF-1` | `<backend-owner>` | A test that a run reports counts and **never reports `success` for a failed load** |
| `D2-FE-4` | Wire `RunScreen.tsx` to `POST /api/runs`: real progress, real extracted/loaded counts, honest statuses, and a failure state; delete the scripted log | FE | **D2 P0** | `D2-BA-4`, `D2-DM-3` | `<frontend-owner>` | Counts match the target table's contents after a run |

Shared tasks this story depends on, defined in master §16.5: `D2-DM-1` (the merge-key-presence check and the one-repeating-field blocker), `D2-PF-1` (run and version persistence), `D2-BA-3` (the error envelope), `D2-TS-1` (the backend suite), `D2-D-1` (deployment).

**Post-D2 and deliberately not in the D2 slice:** the Glue executor and `US6-AC9`'s parity claim (specification only — `doc/backend-architecture.md` keeps Glue a future option behind the executor boundary); staging at scale; the 500-document cap's fix; drift detection; lineage from source field to target column.

---

## 6. The execution path, and its boundaries

### 6.1 Boundary rules (master §3.1, §3.5 rule 6)

| Rule | Why |
| --- | --- |
| `runs` must **never** import `app.agent` | The only thing the harness hands to execution is one approved version ID, read from persistence. A test scanning imports enforces this (master §12.3 Phase 7) |
| The model authors no SQL, no Python, and no DDL | Execution reads no model output as instructions. The approved version contains only declarative operations from the closed §2 vocabulary |
| Only an approved version may execute | A draft, a blocked revision or an unapplied edit must not be loadable. This is `doc/agent-harness-architecture.md` line 169 and the reason approval produces an **immutable** `proposal_versions` row |
| The target warehouse is separate from the control database | The control DB holds proposals, findings and approvals; the target holds analytics-ready output. Pipeline writes use staging and merge (`doc/backend-architecture.md`) |
| Counts are persisted, never inferred from a log | US6-AC4's "record" means a durable row the API returns and the reviewer can compare against the target |

### 6.2 What the executor does, in order

1. Read the approved version: target tables, mappings, operations, the merge key, and the snapshot ids it was approved against.
2. Read the configured source **at that snapshot** — a drifted source must fail the run rather than silently load newer data.
3. Compile each mapping's operations into a per-row pipeline; reject anything outside §2's vocabulary (which `validate` should already have caught).
4. Expand **exactly one** repeating field per target table, producing one target row per element and recording the expansion in the run's provenance.
5. Apply the unmapped/optional-target rule from `DC-6` for every target column that no mapping populates.
6. Coerce to the target attribute's declared type; a value that will not coerce is a row-level failure recorded with its source path.
7. Stage and merge on `Table.key`, so a re-run of unchanged data leaves the row count unchanged.
8. Record extracted and loaded counts, and a status that is never `success` when the load failed.

---

## 7. Validation rules, error paths and recovery

| Rule or failure | Required behaviour |
| --- | --- |
| Merge key absent or not a real column | `validate` blocks approval (`D2-DM-1`) — the executor never has to guess a key |
| More than one repeating field expanded for one target table | `validate` blocks (`multiple_repeating_expansions`). The executor expands exactly one, by construction |
| An operation outside the twelve | `validate` blocks; if one reaches the executor, the run fails with a typed code rather than a silent skip |
| `date_format` on an ambiguous field | Blocked before execution (master §6.2). Execution never applies a format the reviewer has not confirmed |
| A value that will not coerce | Row-level failure with the source path and the target column; the run's counts distinguish read, loaded and rejected rows — a rejected row is never counted as loaded |
| A failed load | Recorded `failed` with an actionable message, and **never** reported as success (`doc/backend-architecture.md` requires this explicitly) |
| A re-run of unchanged data | Idempotent: the counts are reported again and the target row count is unchanged |
| A run interrupted mid-load | Staging plus merge means a partial load is re-runnable; the run record states what completed, and merge makes the retry safe |
| Source drift between the approved snapshot and the run | The run fails explicitly, rather than loading a different dataset under an approved mapping |

**Deliberate failure in the demo:** step 12 presses **Run Now** twice with no changes. A growing row count is the US6 "appends instead of merges" gap reproduced live — a hard failure, not a cosmetic one.

---

## 8. Tests and observable pass criteria

| Test | Pass criterion |
| --- | --- |
| Per-operation units (`D2-DM-2`) | Twelve tests, one per §2 operation, each with a null/absent case and a malformed-input case |
| Conformance / translation test (master §11.8) | Every transform name in the architecture document, in the frontend fixtures and in `TransformOp` maps to a documented row; `derive` and `flatten` are marked non-expressible/lossy; adding an untranslated term fails the test |
| Repeating expansion (`D2-DM-3`) | One document with `lines[]` yields two `order_lines` rows in the target, and the expansion is recorded |
| Re-run idempotency (`D2-DM-3`) | Running the same approved version twice leaves the row count unchanged and creates no duplicate logical rows |
| Merge-key enforcement (`D2-DM-1`) | A proposal with no merge key, or a key that is not a column, cannot be approved |
| One-repeating-field blocker (`D2-DM-1`) | Two repeating fields targeting one table produce `multiple_repeating_expansions` |
| Optional-field rule (`D2-DM-4`) | One test each for `NULL`, defaulted and dropped, matching the written rule |
| Failed load is never success (`D2-BA-4`) | A forced load failure returns `failed` with a message; no response reports `success` |
| Counts match data (`D2-FE-4`) | The counts displayed equal the target table's actual row count |

Run with `py -3 -m pytest tests` from `src/backend/`. **No CI exists today**, so no criterion here may cite CI as its evidence until `D2-TS-3` lands. **Explicitly not claimed:** no executor, transform, load or count exists; no test in this file has been run; no warehouse has been written to.

---

## 9. Demonstration script for US6

Steps 7, 10, 11 and 12 of the master plan's end-to-end scenario.

| Step | Action | Observable result | ACs |
| --- | --- | --- | --- |
| 7 | In the studio, try to apply a `date_format` while the field is still flagged ambiguous | Blocked with an explanation — a **deliberate** failure demonstration | AC6, AC7 (the rules that protect execution) |
| 10 | Open Transform and Load and press **Run Now** | A run is created; extracted and loaded counts are displayed; the run ends `success` | AC1, AC2, AC3, AC4 |
| 11 | Query the target table (out of band) | Two `order_lines` rows from the one document; the date column is a real date, not text | AC5, AC6 |
| 12 | Press **Run Now** again with no changes | The counts are reported again and the target row count is **unchanged** | AC8 |

A mismatch between step 10's counts and step 11's rows is a `D2-DM-3` failure. The script must also state, out loud, that **US6-AC9 is specified and not demonstrated** (there is no Glue path) and that the 500-document cap is neither exercised nor fixed.

---

## 10. D2 scope, and what is out

| Horizon | Content |
| --- | --- |
| **D2 P0** (by 2026-10-23) | AC1, AC2, AC3, AC4, AC5, AC6, AC8, AC10 via `D2-DM-2`, `D2-DM-3`, `D2-DM-4` (rule only), `D2-BA-4`, `D2-FE-4`, plus the shared `D2-DM-1`, `D2-PF-1`, `D2-BA-3`, `D2-TS-1`, `D2-D-1` |
| **Specified only** | AC7's rule (`DC-6`) is written and tested; AC9's Glue half is a specification with no code |
| **Post-D2** | the Glue executor and parity; staging at scale; the 500-document cap; lineage; drift |
| **Not met in D2** | AC9's "consistent between runner and Glue" cannot be demonstrated at all, because one of the two paths does not exist |

Cut order, if the schedule slips (master §17.2): **`D2-DM-3`'s merge behaviour is the one cut this plan does not recommend.** Appending instead of merging contradicts a named current gap in the US6 source, so cutting it makes the demo reproduce the defect rather than the fix. If time runs short, cut US6-AC5's repeating expansion first — but disclose it, because the repeating case is US6's headline example.

---

## 11. Unresolved questions, owners, deadlines, consequences

| # | Question | Owner | By | If unresolved |
| --- | --- | --- | --- | --- |
| `DC-6` | Unmapped/optional target-field behaviour (AC7): `NULL`, defaulted, or dropped | `<product-owner>` + `<backend-owner>` | Oct 14 | `D2-DM-3` picks `NULL` for nullable targets and reports the choice **as an assumption**; AC7 is met by convention rather than by decision |
| `DC-3` | Partial-success and repeating-field semantics when one table's proposal fails (AC5, AC10) | `<product-owner>` + `<backend-owner>` | Oct 14 | The demo shows the happy path only, and US4-AC11 is reported as not demonstrated |
| `Q1`/`DC-2` | Whether the catalogue pre-exists, and the reason vocabulary a rejected proposal uses | `<product-owner>` + `<partner-liaison>` | Phase 0 | Execution is unaffected; the review surface's reasons are free text |
| Phase-7 gate | The forbidden-dependency test (`runs` must not import `app.agent`) and the import scan that enforces it | `<backend-owner>` | Phase 7 | The boundary is a documented convention rather than an enforced one — the exact failure mode master §12.3 Phase 7 exists to prevent |
| `Q4` | Whether execution runs inline (background thread) or from the claimed worker path | `<backend-owner>` | Phase 3 | D2 runs the executor inline with the same limitation as the graph: a run cannot be resumed by a separate process, and that must not be presented as the production design |

No question here is decided by this document. Each carries an owner slot, a deadline, and a stated consequence.
