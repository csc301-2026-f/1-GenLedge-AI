# US4 Person B — LangGraph Routing Workflow

Finalized plan and handoff for the Person B slice of US4 on branch
`us4/person-b-langgraph-model` (base `us4/integration`).

Authoritative references:

- `plans/user-stories/US4.md` §4 (graph), §5 (contracts, prompt boundary), §8 (tests)
- `plans/us4-four-person-task-split.md` §"Person B", §"Integration Gates"
- `plans/LANGGRAPH_HARNESS_PLAN.md` §5–§9
- `doc/agent-harness-architecture.md` (harness gate, line 238)
- `src/backend/app/agent/contracts.py` (frozen contracts — imported, never redefined)

## 1. What was built

```text
START -> context -> (propose | END)
propose -> (tool_call | END)
tool_call -> propose
```

Three nodes, exactly. No human node, no revision loop, no validation node — the
deterministic work after the graph is Person C's and Person D's.

| Module | Responsibility | Key interfaces |
| --- | --- | --- |
| `app/agent/state.py` | `RoutingJobState`, `replace_messages`, `validate_node_update`, `budget_exhausted` | `RoutingJobState`, `initial_state`, `NODE_WRITES` |
| `app/agent/errors.py` | Typed failure codes | `AgentFailure`, `InvalidModelOutputError`, `ModelConfigurationError` |
| `app/agent/graphs.py` | The **only** module that imports `langgraph`; carries the labelled local runner fallback | `graph_runtime`, `LocalStateGraph` |
| `app/agent/repositories.py` | Repository `Protocol` + in-memory doubles + the seeded orders fixture | `RoutingRepository`, `InMemoryRoutingRepository`, `seeded_repository` |
| `app/agent/tools.py` | Tool catalog, argument models, the dispatch contract, redaction | `TOOL_SPECS`, `ToolDispatcher`, `FakeConnector`, `redact_value` |
| `app/agent/prompts.py` + `prompts/*.md` + `prompts/manifest.json` | Versioned prompts, strict rendering, the projection allow-list | `render`, `proposal_prompt_variables`, `project_inventory` |
| `app/agent/models.py` | `ModelClient` protocol, `FakeModel`, `LiveModel`, mode resolution | `resolve_model_mode`, `build_model_client`, `startup_banner` |
| `app/agent/nodes.py` | `context`, `propose`, `tool_call` and the routers | `context_node`, `propose_node`, `tool_call_node`, `route_after_*` |
| `app/agent/graph.py` | Compile, run, budgets, startup banner | `build_graph`, `run_routing_job`, `graph_shape` |
| `app/agent/compat.py` | `StrEnum` for Python 3.10 | `StrEnum` |

## 2. Node behaviour, as implemented

**`context`** loads the frozen inventory for `source_snapshot_ids` and the optional
catalogue (`None` = cold start). No model call. An empty or missing inventory is a
typed `empty_inventory` failure routed straight to `END` — never an empty
proposal. It builds the `ToolDispatcher` for the run.

**`propose`** performs exactly one structured model call per invocation and never
executes a tool. Order of operations:

1. the model-call budget is checked against **both** the in-state counter and the
   durable `get_model_call_count` record, so a crash loop cannot re-spend it;
2. the token budget is checked;
3. the prompt is rendered from the projection allow-list only;
4. the model answers with tool requests, a `ModelDraft`, or a typed error;
5. a malformed answer gets **one** repair call (`repair@1`), itself budget-checked
   and charged; if the repair also fails the run ends `invalid_model_output` and
   **no** fabricated draft is produced;
6. `ModelDraft.revision` is overwritten from `revision_count` after validation, so
   a wrong echo cannot trip the staleness guard.

**`tool_call`** applies the seven-step dispatch contract per requested call:
validate arguments against the tool's own model → check the job's source/resource
scope → check the budget **before** dispatch → replay a recorded
`(job_id, tool_call_id)` → dispatch through the connector seam → validate the
result → redact, persist, and return a compact `ToolResultRef`. Every
model-authored problem is a typed `error` result the model reads, not an
exception. It clears `pending_tool_calls` and always returns to `propose`.

## 3. Graph, edges and loop bounds

| Edge | When |
| --- | --- |
| `START → context` | always |
| `context → propose` | an inventory was projected |
| `context → END` | empty or missing inventory → `empty_inventory` |
| `propose → tool_call` | the model requested tools and the tool budget has head-room |
| `propose → END` | a schema-valid draft, or a terminal typed failure |
| `tool_call → propose` | always |

Bounds: `max_tool_calls` and `max_model_calls` are checked **before** the work they
bound and each ends the run with its own code (`tool_budget_exhausted`,
`model_call_budget_exhausted`). `recursion_limit` is derived
(`2·max_tool_calls + 2·max_model_calls + 12`, ×1.4, floored at
`AgentBudgets.recursion_limit`) so the semantic budgets always fire first.

## 4. Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `GENLEDGE_MODEL_MODE` | `auto` | `auto` \| `live` \| `fake` |
| `GENLEDGE_LLM_PROVIDER` | `anthropic` | provider id; its presence also counts as provider configuration |
| `GENLEDGE_LLM_MODEL` | `claude-opus-5-5` | model id |
| `GENLEDGE_LLM_EFFORT` | `medium` | reasoning effort, recorded per call |
| `GENLEDGE_LLM_MAX_OUTPUT_TOKENS` | `16000` | per-call output cap |
| `GENLEDGE_LLM_TIMEOUT_SECONDS` | `300` | per-request timeout |
| `GENLEDGE_LLM_MAX_RETRIES` | `2` | provider transport retries |
| `GENLEDGE_LLM_API_KEY` | unset | provider key (falls back to `ANTHROPIC_API_KEY`, then `OPENAI_API_KEY`) |

`auto` uses `fake` when no provider variable is present. `live` without provider
configuration raises a typed `model_configuration_error`. Startup output is
`agent_runtime=<langgraph|local-fallback> model_mode=<fake|live> provider=<p> model=<m>`
— the mode, provider and model, and never a secret. `log_resolved_mode()` reports a
half-configured live deployment as a warning instead of crashing the process that
merely imported the package.

## 5. Prompt boundary

`app/agent/prompts.py` is the only path from the process to a prompt. The
projection functions are typed against `InventoryView`, `CatalogueView` and
`ToolResult` — never the graph state, a `dict`, or `Any` — so passing a raw row, a
connector payload or an ORM object into a prompt takes a deliberate type change
rather than an oversight.

The allow-list is: snapshot id, resource ids and kinds, field paths, types,
nullability, repeating status, ≤3 samples per field, the ambiguity marker, the
field status, the catalogue's table and column names and types, the recorded tool
results, the frozen budgets, and `ModelDraft.model_json_schema()`. Field
descriptions are deliberately **not** projected (`DC-1` is undecided).

Never present: whole rows, database ids, connection strings, credentials, the
client name, pre-existing mappings, the organization id, reviewer identity. The
organization id is replaced by an opaque `job_id[:8]` reference; every
source-derived string is emitted inside `<untrusted_source_data>` /
`<untrusted_tool_data>`; credentials, DSNs, e-mail addresses and card-like runs are
replaced with `[redacted]` at the tool layer before persistence **and** again at
the projection boundary; oversized inputs degrade deterministically with explicit
`… and N more` / `[…truncated]` markers.

## 6. Tests and verification

Run from `src/backend`:

```text
python -m pytest tests
```

Written for this slice, under `tests/agent/`:

| Module | Covers |
| --- | --- |
| `test_graph_shape.py` | exactly three nodes; the declared edges; recursive-limit derivation; LangGraph introspection when installed |
| `test_fake_model_tool_loop.py` | one `sample_rows`/`profile_resource` call on `orders.lines[]`, then a schema-valid `ModelDraft`; refs not payloads; cold start vs catalogue reuse |
| `test_budget_exhaustion.py` | tool, model and token budget exhaustion each with its own typed code; durable call count; row/byte caps; no framework error |
| `test_repair_path.py` | one repair attempt, then `invalid_model_output`; refusal is not substituted; the state-write guard |
| `test_duplicate_tool_replay.py` | replay by `(job_id, tool_call_id)` with ≤1 connector call; refusals are re-reported, not replayed; scope and argument errors |
| `test_adapters_and_modes.py` | `auto`/`live`/`fake` resolution; startup banner has no secret; both adapters satisfy one contract and both end with a schema-valid draft |
| `test_prompt_safety.py` | sentinel values, whole rows, descriptions, sample caps, page caps, untrusted-block containment, prompt digests |

### Verification performed on the development machine

- `python -m mypy --check-untyped-defs app/agent tests/agent` — clean (the
  authoritative entrypoint is `python -m pytest tests`; mypy is a supplementary
  check).
- The 86 `tests/agent` cases were **executed** with the suite unmodified through a
  temporary pytest-compatible runner against Python 3.10 + pydantic 2.11.9:
  `passed=86 failed=0 skipped=2`.
- `python -m pytest tests` **could not be run to completion**, because this machine
  has no network access and neither the 3.13 interpreter nor any reachable image has
  `pydantic`, `flask` or `langgraph` installed. Every suite in the repository
  (`test_app.py`, `test_auth.py`, `test_api_schemas.py`, `test_contracts.py`) fails
  at collection for the same pre-existing reason. **This is a reported limitation,
  not a met gate.**

## 7. Provider limitations and known gaps

1. **`langgraph` is not installed here.** The graph code is written once against the
   real `StateGraph` API; `app/agent/graphs.py` falls back to a labelled local
   runner so the nodes stay testable offline. The two assertions that inspect the
   *compiled LangGraph* structure are skipped when the package is absent; the node
   set and edges are asserted unconditionally against the declared shape
   (`graph_shape()`), which is the same source `build_graph()` uses. Install
   `langgraph>=1.2,<2` (added to `requirements.txt`) and the two tests run.
2. **The live adapter is exercised against an SDK stub, not a real provider.** No
   key, no network, no eval baseline. `LiveModel` sends `system`, `messages`, bound
   tools with `tool_choice: auto`, and native structured output
   (`output_format: json_schema`); those are the *intended* call shapes and remain
   `[Unverified]` against the real SDK, which `plans/LANGGRAPH_HARNESS_PLAN.md`
   already records as E-2/E-6.
3. **No checkpointer.** `run_routing_job` invokes the graph once and returns; the
   harness gate's "resume from a checkpoint" half needs the Postgres saver that
   Person A's persistence unblocks. The gate's other half — start a job, complete a
   tool call, persist a result, end with schema-valid output, with no real source
   and no live provider — is met by `test_fake_model_tool_loop.py`.
4. **Tool replay is in-memory.** `RoutingRepository` is the declared seam; Person A's
   adapter replaces `InMemoryRoutingRepository` without changing this package.
5. **The fake model is deterministic, not intelligent.** It reuses a catalogue table
   id when the catalogue names one; it does not verify that every proposed attribute
   exists in the reused table's columns. Catalogue reuse remains D2 P1 per
   `D2-LG-3`.
6. **`contracts.py` gained one import** (`from app.agent.compat import StrEnum`) so
   the package imports on Python 3.10. The field set, validators and
   `CONTRACT_VERSION` are unchanged; the file's contract surface is still Person C's.
7. **`propose` writes `status: "awaiting_review"`** when it accepts a draft, because
   `US4.md` §4.2 gives `propose` the `status` write and the graph ends there.
   Person D may prefer `running` until the package is persisted; that is a one-line
   change in one node and does not affect routing, which never reads `status`.

## 8. Handoff

**Consumes:** the frozen contracts in `app/agent/contracts.py`; Person A's
persistence through the `RoutingRepository` protocol; the seeded fixture shape.

**Produces:** `build_graph()`, `run_routing_job(...) -> RoutingRunResult`
(`final_state`, `model_draft`, `failure`, `status`, `mode`, `model_responses`),
`resolve_model_mode()`, `TOOL_SPECS`, `PROMPTS_DIR`/`manifest()`.

**Fake boundaries for Gate 1:** `seeded_repository()`, `empty_inventory_repository()`,
`FakeConnector`, `FakeModel`, and `tests/agent/doubles.py`'s `ScriptedModel` and
`GreedyModel` (the latter drives the tool budget to its bound, which a cooperating
model would never do).
