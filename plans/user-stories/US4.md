# US4 — Automatically map / route data

**Status:** Proposed implementation plan — planning document only. Nothing in this file is implemented.
**Acceptance-criteria source:** `src/frontend/src/imports/GenLedge_Connector_MVP_User_Stories.pdf` (US1–US7), quoted not paraphrased.
**Shared design:** state, budgets, contracts, the graph, phase gates and the D2 critical path are defined once in the master plan, [`../LANGGRAPH_HARNESS_PLAN.md`](../LANGGRAPH_HARNESS_PLAN.md). This file links to it instead of repeating it.

*PDF story:* "As a data owner, I want GenLedge to automatically determine where my source data belongs in the warehouse in order to reduce the amount of manual data engineering required."

**Where the plan defines the shared parts:** master §2.4a (catalogue pre-existence), §3.1–§3.5 (ownership split, anti-duplication rules), §4 (API/worker/resume flows), §5 (state and boundary contracts), §6 (`discover`, `design_schema`, `map_sources`, `tool_call`, `validate`), §7 (prompt construction and the projection allow-list), §8 (model adapter, tools, no-side-effect rule), §9.3–§9.4 (injection and secret boundaries).

---

## 1. Acceptance criteria, status, and the tasks that close them

AC identifiers are this plan's; they exist so one criterion can be referenced unambiguously from the task tables and from the master plan. "Tasks" are defined once — see §5 here and the cross-story table in master §16.5.

| AC | Acceptance criterion (source wording) | Current status (repository evidence) | Tasks | Blocking decision |
| --- | --- | --- | --- | --- |
| **US4-AC1** | Allow the user to select "Find where this data belongs" | **Partial.** `DiscoverScreen.tsx` renders a `Run AI Routing` button whose handler is `onAdvance()` — a screen change, no request. The AC's literal label differs from the UI's | `D2-FE-1` | `DC-4` (label) |
| **US4-AC2** | Provide the AI with discovered source fields and the existing warehouse table catalogue | **[Gap].** No model call exists anywhere in `src/`. Projection is specified in master §5.5, the catalogue question in master §2.4a | `D2-LG-1`, `D2-LG-2`, `D2-PF-2` | `Q1` (catalogue), `Q2` (provider) |
| **US4-AC3** | Allow AI to reuse an existing warehouse table or propose a new table | **Partial (affordance only).** `RouteScreen.tsx`'s `ROUTE_DATA` carries `isNew: false` for `fact_orders`/`dim_customers` and `isNew: true` for `fact_order_lines`; no contract field or check backs it | `D2-LG-3` (cold start **P0**; reuse path **P1**) | `Q1` |
| **US4-AC4** | Allow one source collection to route into multiple warehouse tables | **Partial.** The fixture routes one collection (`orders`) into three tables, so the surface exists; no contract or check enforces it | `D2-DM-1` | — |
| **US4-AC5** | Allow AI to propose target columns and a merge key | **Partial.** `mergeKey` exists per fixture table; nothing validates that it is non-empty, unique, or a real column | `D2-LG-3`, `D2-DM-1` | — |
| **US4-AC6** | Use field names, types, descriptions, sample values, and repeating structure when deciding where data belongs | **[Gap], with a contract hole.** The UI's discovered-field shape is `{path, type, nullable, repeating, samples[], status, ambiguous?}` and master §5.5's projection allow-list is field paths, types, repeating status and ≤3 samples. **Neither carries a field *description***, which this criterion names as an input | `D2-PF-2`, `D2-LG-2` | `DC-1` |
| **US4-AC7** | Return confidence and a human-readable reason for the routing decision | **Partial (fixtures only).** `RouteScreen.tsx` shows `92%`/`87%`/`78%` and a `reason` string; no contract requires either to be present or non-empty | `D2-LG-1`, `D2-DM-1` | — |
| **US4-AC8** | Validate all AI-generated table and field references before applying them | **[Gap].** `app/mappings/validation.py` is planned (master §4.2, §12.2) and does not exist | `D2-DM-1` | Contract freeze (master §12.3 Phase 1) |
| **US4-AC9** | Report invalid references and unrouted fields with reasons | **[Gap].** An `unmapped` count comes from a fixture; no reason vocabulary exists anywhere in the repository | `D2-DM-1`, `D2-FE-1` | `DC-2` (reason-code vocabulary) |
| **US4-AC10** | Do not automatically alter a populated warehouse table; hold new columns for human approval | **[Gap].** No target warehouse exists to alter, so the rule has no enforcement point | `D2-DM-3` | **Not fully demonstrable in D2** — the demo target is created fresh, so "did not alter a populated table" is shown by the executor's write path and its tests, not by a live before/after comparison. Report as structurally demonstrated |
| **US4-AC11** | Preserve successful tables/pipelines even when one mapping operation fails | **[Gap].** Per-table accept/reject exists in the fixture only; master §9.1's failure matrix does not yet define partial success for this case | `D2-DM-1`, `D2-LG-1` | `DC-3` |
| **US4 boundary** | "The model receives field paths, inferred types, repeating status, and limited sample values plus the target-table catalogue. Whole rows, database IDs, connection strings, client name, and existing mappings are not sent as model input." | **[Gap] as a guarantee.** Master §5.5 specifies the allow-list and §11.4 the sentinel tests, but no code enforces either — and `RouteScreen.tsx`'s own alert currently asserts this as if it were already true | `D2-LG-2`, `D2-TS-1` | `Q2` (provider data handling) |

**Status vocabulary used above:** **[Current]** exists in the tree · **[Gap]** described in a document but not implemented · **Partial** a UI affordance or fixture exists without the contract behind it. Every `[Gap]` and `Partial` row must be built or explicitly reported as unmet; none may be reported as complete because a fixture renders something similar.

---

## 2. Current implementation status, in detail

| Surface | Evidence | What it actually does |
| --- | --- | --- |
| `src/frontend/src/features/discovery/DiscoverScreen.tsx` | `Run AI Routing` button, handler `onAdvance()` | Changes the screen. No fetch, no job, no routing. |
| `DiscoverScreen.tsx` field tree | local `FIELD_DATA` keyed `'orders' \| 'order_lines' \| 'customers'`, shape `{path, type, nullable, repeating, samples[], status, ambiguous?}` | A module constant. It is the only description of the discovered-field shape in the repository, which is why `DC-1` is about *this* shape. |
| `src/frontend/src/features/mappings/RouteScreen.tsx` | module constant `ROUTE_DATA`, 3 proposals (`fact_orders` 92 %, `fact_order_lines` 87 % `isNew`, `dim_customers` 78 %), each `{table, isNew, confidence, mergeKey, reason, fields[]}` | Renders fixtures. `accept`/`reject` write to component state. The page's trust-boundary alert states the US4 boundary as fact. |
| `src/backend/app/mappings/` | `__init__.py` docstring only | No service, no validation, no routes. |
| `src/backend/requirements.txt` | `Flask>=3.1,<4` | No `langgraph`, `pydantic`, or provider SDK is declared. |
| Repository-wide search for `langgraph\|langchain\|anthropic\|openai\|llm\|prompt` under `src/` | no matches | No model call, prompt file, or adapter exists. |

Nothing in US4 is implemented. The three `RouteScreen.tsx` proposals are the *shape* the product expects, not evidence of a routing capability.

---

## 3. Remaining work by layer

| Layer | What is missing | Tasks |
| --- | --- | --- |
| **Frontend** | `RouteScreen.tsx` never fetches; the routing trigger is a screen change; confidence, reason, merge key, `isNew`, invalid references and unrouted fields are all fixtures | `D2-FE-1`, `D2-FE-3` |
| **API** | No `/api/mappings/jobs` create/status/package endpoints; no error envelope reuse beyond `auth/routes.py`'s convention | `D2-BA-1` (cross-story), `D2-BA-3` (cross-story) |
| **Backend / domain** | No deterministic reference validation, coverage computation, reason codes, or merge-key check | `D2-DM-1` (cross-story) |
| **LangGraph / model** | No graph, no node, no prompt file, no provider adapter | `D2-LG-1`, `D2-LG-2`, `D2-LG-3` |
| **Persistence** | No control tables, no schema, no migration, no seeded snapshot or inventory | `D2-PF-2`; `D2-PF-1` (cross-story) |
| **Deployment** | Nothing in US4 is user-visible without the D2 deployment target | `D2-D-1` (cross-story) |

---

## 4. Tasks owned by this story

Priority: **D2 P0** = in the frozen deployed snapshot, or the demonstration cannot run · **D2 P1** = lands only if P0 is safe · **Post-D2** = explicitly out (master §17.2). Owners are placeholder slots filled in the Phase 0 ADR.

| ID | Task | Layer | Priority | Depends on | Owner | Completion evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `D2-LG-1` | The graph subset for a D2 routing job: `discover(fixture) → design_schema → map_sources → validate → await_human → approved`, built on the master plan's state and contracts | LG | **D2 P0** | `D2-PF-1`, `D2-PF-2`, `DC-7` | `<agent-owner>` | The gate already written in `doc/agent-harness-architecture.md` line 238 — start a job, complete a tool call, persist a result, resume from a checkpoint, end with a schema-valid structured output — against fixtures, with no real source and no live provider |
| `D2-LG-2` | The `design_schema` and `map_sources` prompts plus the projection allow-list, so **the US4 safety boundary is executable code** rather than a UI claim | LG | **D2 P0** | `D2-LG-1`, `DC-1` | `<agent-owner>` | A sentinel test asserting that no whole row, connection string, client name or pre-existing mapping reaches the rendered prompt |
| `D2-LG-3` | Catalogue handling and the reuse-vs-new decision: `catalog_ref`, a per-table `isNew` flag, a proposed merge key | LG | **D2 P0** (cold start) / **D2 P1** (reuse) | `D2-LG-2`, `Q1` | `<agent-owner>` | A `catalog_ref=None` run produces a proposal whose new tables carry `isNew: true`; the reuse path additionally needs a *second* seeded catalogue, which is why it is P1 |
| `D2-FE-1` | Wire the routing screen to the package: live per-table confidence, reason, merge key, `isNew`, accept/reject, invalid references and unmapped fields; make the routing action the job-creation trigger | FE | **D2 P0** | `D2-BA-1`, `D2-LG-3` | `<frontend-owner>` | Live values replace the `ROUTE_DATA` constant, and the page's boundary alert becomes true rather than aspirational |
| `D2-PF-2` | Seed one deterministic demo source — a small orders fixture including one `lines[]` array and one ambiguous `order_date` — plus its snapshot and discovered-field records, ≤3 samples per field | BD / P | **D2 P0** | `D2-PF-1` | `<backend-owner>` | A fields endpoint returns the seeded inventory; a test asserts sample counts and that no whole row is stored in the projection |

Shared tasks whose outcome US4's criteria depend on, defined in master §16.5 and not repeated here: `D2-PF-1` (control tables), `D2-BA-1` (job create/status/package), `D2-BA-3` (error envelope), `D2-DM-1` (deterministic validation, coverage, reason codes, merge-key check), `D2-DM-3` (executor — US4-AC10's only enforcement point), `D2-FE-3` (failure surfacing), `D2-TS-1`/`D2-TS-2` (tests), `D2-D-1` (deployment).

**Post-D2 and deliberately not in the D2 slice:** the revision loop and `revise` (master's US5 plan), the real connector/discovery layer that would supply a live inventory (US2/US3), the catalogue-reuse path's second seeded catalogue, the eval suite and prompt baselines, and any handler that lets the model author SQL or a join without `compare_fields` evidence.

---

## 5. Inputs, outputs and the data model

### 5.1 What the model receives, and what it must never receive

The projection is the only path from the process to a prompt (master §5.5). For this story it is:

| Variable | Origin | Bounded how |
| --- | --- | --- |
| `{{job_ref}}` | `job_id[:8]` | Opaque prefix; the organization id is **never** rendered |
| `{{inventory}}` | the seeded inventory record, projected | one line per resource/field; page-capped; `… and N more` marker |
| `{{catalog}}` | `catalog_ref`, or the literal `No existing warehouse catalogue. Propose a new model.` | table/column names and types only |
| `{{tool_results}}` | recorded tool results from the current step | JSON, redacted, delimited as untrusted, ≤3 sample values per field |
| `{{budgets}}` | frozen `AgentBudgets` | one line per budget |
| `{{output_schema}}` | `ModelDraft.model_json_schema()` / `MappingDraft.model_json_schema()` | schema only |

Must never appear: whole rows, database IDs, connection strings, credentials, the client name, pre-existing mappings, the organization id, or reviewer identity. Enforcement is a projection allow-list plus the sentinel tests in master §11.4 — not a prompt instruction.

### 5.2 The proposal contract (boundary models)

Defined in `app/agent/contracts.py` **[Proposed]**. These are the fields US4's criteria refer to; the full contract set, the shared conventions and the validation boundaries are in master §5.

```python
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.\[\]-]*$")]

class Disposition(str, Enum):   REPRESENTED | RAW_ONLY | EXCLUDED | SENSITIVE | UNRESOLVED
class SourceType(str, Enum):    TEXT | NUMBER | BOOLEAN | TIMESTAMP | DATE | JSON
class Severity(str, Enum):      BLOCKER | WARNING | INFO

class EvidenceRef:              resource_id: str; field_path: str | None; profile_ref: str | None
class Attribute:                id: Identifier; type: SourceType; nullable: bool
                                evidence: list[EvidenceRef]          # min_length=1 — no uncited attribute
                                confidence: float                    # 0.0 … 1.0
                                ambiguity: str | None                # e.g. "date_format_ambiguous"
class Relationship:             from_ref: Identifier  (alias "from"); to_ref: Identifier
                                cardinality: one_to_one | one_to_many | many_to_one | many_to_many
                                evidence: list[EvidenceRef]          # min_length=1
class Table:                    id, name: Identifier
                                kind: entity | event | reference
                                grain: str (1–300)                   # min_length=1 — an explicit grain
                                key: list[Identifier]                # min_length=1 — the merge key
                                attributes: list[Attribute]
                                relationships: list[Relationship]
                                rationale: str (1–1000)
class SourceCoverage:           field_path: str; resource_id: str
                                disposition: Disposition; reason: str (1–500)
class ModelDraft:               revision: int
                                tables: list[Table]
                                source_coverage: list[SourceCoverage]
                                unresolved: list[str]; notes: str | None
class Mapping:                  target: Identifier
                                sources: list[Identifier]            # min_length=1
                                operations: list[TransformOp]        # US6's closed vocabulary only
                                join_path: list[str]
                                confidence: float; rationale: str | None
class MappingDraft:             revision: int
                                based_on_model_revision: int
                                mappings: list[Mapping]
                                unmapped_targets: list[Identifier]; unresolved: list[str]
```

Three conventions that make these usable here (master §5.3):

1. **Anything a model produces is checked against a model-facing contract containing only what a model can know.** Harness-owned fields — `MappingDraft.based_on_model_revision`, `CriticFindingRecord.revision`, `HumanEdit.edit_id` — are absent from the model-facing shape and assigned afterwards.
2. **`ModelDraft.revision` and `MappingDraft.revision` are *overwritten* by the harness** from `revision_count` after validation, so a wrong echo cannot trip the staleness guard.
3. Every contract is `extra="forbid", frozen=True, strict=True`: invented fields, invented enum members, and `"3"` for an `int` are validation failures rather than silent coercions.

**Where US4's criteria land in these models:** AC5's merger key is `Table.key`; AC7's confidence is `Mapping.confidence` and its human-readable reason is `Mapping.rationale`/`Table.rationale`; AC9's unrouted fields are `SourceCoverage` rows with a `Disposition` of `RAW_ONLY`/`UNRESOLVED` plus `MappingDraft.unmapped_targets`; AC4 needs no new field — one `Table` per target and one source collection per several rows is already the shape.

### 5.3 The catalogue decision (`US4-AC3`)

Master §2.4a's decision: the catalogue is an **optional graph input** (`catalog_ref: str | None`). `None` reproduces the architecture document's cold-start behaviour; a reference reproduces US4's reuse wording. This keeps US4 and `doc/agent-harness-architecture.md` both true without editing either. **It is still a team question (`Q1`)** and the reuse path cannot be demonstrated in D2 without a second seeded catalogue — so D2 shows cold start plus a proposed new table, and the demo script must say that, not gloss it.

---

## 6. Validation rules, error paths, security constraints and recovery

| Rule | Enforced by | On failure |
| --- | --- | --- |
| Every AI-proposed table and field reference exists in the draft or the catalogue | `D2-DM-1` (`mappings/validation.py`, pure functions over the contracts) | `ValidationFinding(severity=blocker, code=invalid_reference, target=…)`; approval blocked; the reason is rendered to the reviewer |
| Identifier legality (pattern, reserved words, duplication) | `D2-DM-1` | blocker, with the offending name |
| Every target attribute is mapped or explicitly unresolved | `D2-DM-1` | blocker or `unmapped_targets` entry |
| A merge key is present, and is a real column of its table | `D2-DM-1` | blocker — US6 depends on this key for merge behaviour |
| A cross-source join cites a `compare_fields` result | `D2-DM-1` | blocker when the join crosses sources, has no declared key, or disagrees on cardinality |
| `operations` contains only `TransformOp` members | `D2-DM-1` | blocker; US6's vocabulary is closed and is defined in [`US6.md`](US6.md) |
| A `date_format` operation on a field still flagged `ambiguous` | `D2-DM-1` | **blocker, not a warning** — US3's rule is that `03/04/2026` stays text until the interpretation is known |
| More than one repeating field expanded for one target table | `D2-DM-1` | blocker (`multiple_repeating_expansions`) |
| Every discovered field carries exactly one `Disposition` | `D2-DM-1` | blocker; a field is never silently dropped |
| A model output that fails its contract | `llm.py` after the call | one `repair.md` attempt, then `invalid_model_output` — never a fabricated draft |
| A tool the connector cannot serve | `tools.py` capability check | an `unsupported` result the model must adapt to, not retry |
| Tool arguments naming a source outside the job's tenant scope | `tools.py` authorization | `unauthorized_source`, not retried, recorded as a security event |
| A job interrupted before its proposal is persisted | master §5.9's recovery path | resume at a named node from the control database; **never** a silent re-run of discovery and design |

Recovery boundary specific to this story: the proposal is persisted by the node that produces it, so a lost checkpoint never loses a proposal. The D2 slice may use `InMemorySaver`, in which case a process restart loses the *in-flight* run and the reviewer re-issues the job — a legitimate D2 simplification, but one that must be labelled as debt rather than presented as the §5.9 design (`DC-7`).

---

## 7. Tests and observable pass criteria

| Level | Test | Pass criterion |
| --- | --- | --- |
| Unit | table-driven conformance test over the frozen vocabulary and the AC list | every §5.2 constraint rejects what it must: unknown field, `evidence=[]`, `confidence=1.4`, an invented operation, `"3"` for `int` |
| Unit | one test per validation rule in §6 | each rule produces its declared `code`, and `validation` never raises — findings are data |
| Unit | projection and sentinel tests (`D2-LG-2`) | a sentinel organization id and a sentinel password are absent from every rendered prompt; every source-derived string sits inside an untrusted-data block; ≤3 samples per field |
| Integration | a routing job against the seeded fixture (`D2-LG-1`) | a job starts, reaches a schema-valid `ModelDraft` and `MappingDraft`, persists a revision, and suspends awaiting review — with no real source and no live provider |
| Integration | invalid reference path | a proposal naming a nonexistent column reaches review **with the blocker visible** and cannot be approved |
| Integration | ambiguity path | the seeded ambiguous `order_date` yields an `ambiguity` marker or an unresolved item, never a silent `date_format` |
| Contract | `POST /api/mappings/jobs` and `GET …/package` (`D2-BA-1`) | `202 {job_id}` and a schema-valid package body; no model call in the request path |
| Frontend | routing screen against a live package (`D2-FE-1`) | confidence, reason, merge key, `isNew`, invalid references and unrouted fields all come from the API; the fixture constant is gone |

Run with `py -3 -m pytest tests` from `src/backend/` (`python` is not on `PATH` on the development machine — master §14.4). **No CI exists in this repository today**, so no criterion here may cite "CI enforces it" as its evidence until the `D2-TS-3` workflow exists.

**Explicitly not claimed:** no test in this file has been written or run, and no model call has been made. The assertions above are what the tests must prove once they exist.

---

## 8. Demonstration script for US4

Steps 3–6 of the master plan's end-to-end scenario (master §18). The scenario's points that belong to this story:

| Step | Action | Observable result | ACs exercised |
| --- | --- | --- | --- |
| 3 | Open the seeded source and proceed to discovery | collections, document count, a field tree with dotted paths and `[]` notation, a type and ≤3 samples per field, and an ambiguity marker on `order_date` | AC6 (input side) |
| 4 | Select **Find where this data belongs** (labelled per `DC-4`) | a pending state, then proposed target tables with confidence, a human-readable reason, a merge key, and which tables are new | AC1, AC2 (cold start), AC5, AC6, AC7 |
| 5 | Inspect one proposal and reject one table | the rejected table leaves the loaded set; the others remain | AC11 — **only if `DC-3` is decided**; otherwise this step is dropped from the script rather than faked |
| 6 | Open the repeating array's proposal | the target column, merge key and any candidate date operation are shown, and the ambiguity marker survives into the studio | AC6, and US5's correction path |

Failure reporting is part of the script: a model or validation failure must surface a typed code and a retry, never an empty result; and step 3's empty tree is a seed failure (`D2-PF-2`), reported as a data problem rather than as a discovery result.

**What the script must say out loud, because D2 cannot demonstrate it:** AC3's reuse path (no second catalogue — P1); AC10's "did not alter a populated table" (the demo target is created fresh, so this is shown structurally, not by comparison); AC6's "descriptions" (the contract carries none until `DC-1` is decided); and, if `DC-7` selects a recorded response, that the routing result is a replay and not a live model call.

---

## 9. D2 scope, and what is out

| Horizon | Content |
| --- | --- |
| **D2 P0** (by 2026-10-23) | AC1, AC2, AC4, AC5, AC7, AC8, AC9 and the boundary criterion, via `D2-LG-1`, `D2-LG-2`, `D2-LG-3` (cold start), `D2-FE-1`, `D2-PF-2`, and the shared `D2-PF-1`, `D2-BA-1`, `D2-BA-3`, `D2-DM-1`, `D2-TS-1`, `D2-TS-2`, `D2-D-1` |
| **D2 P1** | AC3's reuse path (`D2-LG-3`), which needs a second seeded catalogue |
| **Not demonstrable in D2** | AC10 (fresh target — structural evidence only), AC11 if `DC-3` is not decided, AC6 in full until `DC-1` is decided |
| **Post-D2** | the revision loop; real ingestion and discovery (US2/US3); the eval suite; a live provider if `DC-7` chose a replay; drift, lineage and the retention sweep |

Cut order, if the schedule slips (master §17.2): the reuse path first, and if the graph itself must go, `D2-LG-1` runs the same node functions through a plain runner — a legitimate D2 simplification only if labelled, because it makes the demo a product demo rather than a harness demo.

---

## 10. Unresolved questions, owners, deadlines, consequences

| # | Question | Owner | By | If unresolved |
| --- | --- | --- | --- | --- |
| `DC-1` | Does the discovered-field contract carry a **field description** (AC6 names "descriptions"; neither the UI shape nor the projection has one)? | `<product-owner>` + `<agent-owner>` | Oct 13 | The projection stays as specified and AC6 is reported as partially met; adding it later is a projection change, not a UI tweak |
| `DC-2` | The **reason-code and gap vocabulary** for invalid references and unrouted fields (AC9) | `<product-owner>` + `<backend-owner>` | Oct 13 | `D2-DM-1` emits free text; the AC is met in substance but not machine-checkably, and conformance testing is impossible |
| `DC-3` | **Partial-success semantics** when one table's proposal fails (AC11) | `<product-owner>` + `<backend-owner>` | Oct 14 | Step 5 is dropped from the script and AC11 is reported as not demonstrated |
| `DC-4` | The literal user-facing label for AC1: source says "Find where this data belongs", the UI says "Run AI Routing" | `<product-owner>` + `<frontend-owner>` | Oct 14 | The demo uses the UI wording and the criterion is noted as met in substance; a marking reviewer comparing text sees a difference |
| `DC-7` | Whether the model is live against the synthetic fixture or a recorded, labelled response | `<agent-owner>` + `<product-owner>` | Oct 13 | D2 ships a recorded response; AC2/AC7 are then a claim about a recorded proposal and **must be labelled as such** in the UI and the script |
| `Q1` | Does a warehouse catalogue pre-exist (`Uas4-AC3` reuse) or does the first job start from nothing? | `<product-owner>` + `<partner-liaison>` | Phase 0 | Cold-start default stands; the reuse path stays untested and AC3 is partially met |
| `Q2` | Which provider, and are its data-handling terms acceptable for redacted samples? | `<product-owner>` + `<partner-liaison>` | Phase 0 | D2 runs against synthetic fixtures only, with redaction mandatory, and the "works on a real estate" claim stays unproven |

None of these is decided by this document. Each has an owner slot, a date, and a stated consequence — so shipping without an answer is a visible, accepted risk rather than an accidental one.
