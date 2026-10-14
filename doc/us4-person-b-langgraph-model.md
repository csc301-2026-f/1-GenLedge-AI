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
| `app/agent/state.py` | `RoutingJobState`, `replace_messages`, the node-write table, `budget_exhausted` | `RoutingJobState`, `initial_state`, `NODE_WRITES`, `validate_node_update` |
| `app/agent/errors.py` | Typed failure codes | `AgentFailure`, `InvalidModelOutputError`, `ModelConfigurationError` |
| `app/agent/graphs.py` | The **only** module that imports `langgraph`; carries the labelled local runner and the node-write guard | `graph_runtime`, `guarded`, `LocalStateGraph` |
| `app/agent/repositories.py` | Repository `Protocol` + in-memory doubles + the seeded orders fixture | `RoutingRepository`, `InMemoryRoutingRepository`, `seeded_repository` |
| `app/agent/tools.py` | Tool catalog, argument **and result** models, the dispatch contract, redaction | `TOOL_SPECS`, `ToolDispatcher`, `FakeConnector`, `redact_value` |
| `app/agent/prompts.py` + `prompts/*.md` + `prompts/manifest.json` | Versioned prompts, single-pass strict rendering, the projection allow-list | `render`, `proposal_prompt_variables`, `repair_prompt_variables`, `project_inventory` |
| `app/agent/models.py` | `ModelClient` protocol, `FakeModel`, `LiveModel`, mode resolution | `resolve_model_mode`, `build_model_client`, `startup_banner` |
| `app/agent/nodes.py` | `context`, `propose`, `tool_call` and the routers | `context_node`, `propose_node`, `tool_call_node`, `route_after_*` |
| `app/agent/graph.py` | Compile, run, budgets, startup banner | `build_graph`, `run_routing_job`, `graph_shape` |
| `app/agent/compat.py` | `StrEnum` on Python 3.10 | `StrEnum` |

## 2. Node behaviour, as implemented

**`context`** loads the frozen inventory for `source_snapshot_ids` and the optional
catalogue (`None` = cold start). No model call. An empty or missing inventory is a
typed `empty_inventory` failure routed straight to `END` — never an empty proposal.
A `catalogue_ref` that cannot be resolved is a typed `catalogue_not_found` failure:
a reviewer who asked for reuse is not silently handed a cold-start proposal. It
builds the `ToolDispatcher` for the run.

**`propose`** performs exactly one structured model call per invocation and never
executes a tool. Order of operations:

1. the model-call budget is checked against **both** the in-state counter and the
   durable `get_model_call_count` record, so a crash loop cannot re-spend it;
2. the token, wall-clock and cost budgets are checked;
3. the prompt is rendered from the projection allow-list only; a render fault is a
   typed `prompt_render_failed` failure, never an escaping exception;
4. the tools from `TOOL_SPECS` are bound to the call, so a live provider can
   actually request one;
5. the model answers with tool requests, a `ModelDraft`, or a typed error;
6. each call (and the repair) is recorded through `record_model_call`, which is the
   durable count the budget reads;
7. a malformed answer gets **one** repair call carrying the evidence, the previous
   response and the validation errors; if that also fails the run ends
   `invalid_model_output` and **no** fabricated draft is produced;
8. `ModelDraft.revision` is overwritten from `revision_count` after validation, so
   a wrong echo cannot trip the staleness guard.

**`tool_call`** applies the dispatch contract per requested call:

1. validate arguments against the tool's own model;
2. check the job's source and resource scope (an out-of-scope source is also recorded
   as a security event);
3. **replay** a recorded `(job_id, tool_call_id)` — before the budget check, so a
   replay can never double-count a call;
4. check the tool-call budget **before** dispatch;
5. dispatch through the connector seam;
6. validate the connector's answer against the tool's declared **result** model, and
   enforce `max_tool_bytes` and `max_tool_rows`;
7. redact, persist, and return a compact `ToolResultRef`.

Every model-authored problem is a typed `error` result, and those errors are
projected into the next prompt as data (`"<tool> FAILED: {error_code, message}"`) so
the model can adapt instead of re-requesting blind. It clears `pending_tool_calls`
and always returns to `propose`.

## 3. Graph, edges and loop bounds

| Edge | When |
| --- | --- |
| `START → context` | always |
| `context → propose` | an inventory was projected |
| `context → END` | empty inventory, missing inventory, or an unresolvable catalogue |
| `propose → tool_call` | the model requested tools and the tool budget has head-room |
| `propose → END` | a schema-valid draft, or a terminal typed failure |
| `tool_call → propose` | always |

Bounds, each checked **before** the work it bounds and each with its own code:
`max_tool_calls` → `tool_budget_exhausted`, `max_model_calls` →
`model_call_budget_exhausted`, `max_tokens` → `token_budget_exhausted`,
`max_wall_clock_seconds` → `wall_clock_budget_exhausted`, `max_cost_usd` →
`cost_budget_exhausted` (evaluated from a configured price; with no price the
ceiling is reported as unevaluable rather than guessed), `max_tool_bytes` and
`max_tool_rows` → a typed `budget_exhausted` tool result. `recursion_limit` is
derived (`2·max_tool_calls + 2·max_model_calls + 12`, ×1.4, floored at
`AgentBudgets.recursion_limit`) so the semantic budgets always fire first; a
runtime that does hit it is mapped to `recursion_limit_exceeded` rather than
escaping as a framework error.

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
— the mode, provider and model, and never a secret. `main.py` calls `init_agent(app)`
once, so the banner is emitted at process start; a half-configured live deployment is
logged as a warning instead of crashing the process. `app/__init__.py` deliberately
does **not** import `app.agent` or Flask at module scope, so importing the harness
never requires a web framework.

## 5. Prompt boundary

`app/agent/prompts.py` is the only path from the process to a prompt. The
projection functions are typed against `InventoryView`, `CatalogueView` and
`ToolResult` — never the graph state, a `dict`, or `Any` — so passing a raw row, a
connector payload or an ORM object into a prompt takes a deliberate type change
rather than an oversight.

The allow-list is: snapshot id, resource ids and kinds, field paths, types,
nullability, repeating status, ≤3 samples per field, the ambiguity marker, the field
status, and the native type; for the catalogue, an opaque `catalog_ref` plus table
and column names and types; for tool results, the redacted recorded payloads capped
at three rows at any depth; plus the frozen budgets and `ModelDraft.model_json_schema()`.
Field descriptions are deliberately **not** projected (`DC-1` is undecided).

Never present: whole rows, database ids, connection strings, credentials, the client
name, pre-existing mappings, the organization id, reviewer identity. The organization
id is replaced by an opaque `job_id[:8]` reference; every source-derived string is
emitted inside `<untrusted_source_data>` / `<untrusted_tool_data>`; credentials,
DSNs, e-mail addresses and card-like runs are replaced with `[redacted]` at the tool
layer before persistence **and** again at the projection boundary; oversized inputs
degrade deterministically with explicit `… and N more` / `[…truncated]` markers.

Rendering is single-pass. A source value containing `{{budgets}}` is emitted
literally inside the untrusted block — it can neither crash the renderer nor splice
another prompt block into itself.

## 6. Tests and verification

Run from `src/backend`:

```text
python -m pytest tests
```

Written for this slice, under `tests/agent/`:

| Module | Covers |
| --- | --- |
| `test_graph_shape.py` | exactly three nodes; the declared edges; the loop actually runs and terminates; adversarial draft text cannot change the route; recursion-limit derivation; LangGraph introspection when installed |
| `test_fake_model_tool_loop.py` | one `sample_rows`/`profile_resource` call on `orders.lines[]`, then a schema-valid `ModelDraft`; refs not payloads; tools bound on the call; cold start vs catalogue reuse |
| `test_budget_exhaustion.py` | tool, model, token, wall-clock and cost exhaustion, each with its own code; durable call count; row and byte caps; no framework error |
| `test_repair_path.py` | one repair attempt, then `invalid_model_output`; refusal is not substituted; the write guard is wired into execution; empty inventory and unresolvable catalogue are typed; a render fault is typed |
| `test_duplicate_tool_replay.py` | replay by `(job_id, tool_call_id)` with ≤1 connector call; refusals are re-reported, not replayed; scope, argument and result-contract errors |
| `test_adapters_and_modes.py` | `auto`/`live`/`fake` resolution; startup banner has no secret; both adapters satisfy one contract and both end with a schema-valid draft |
| `test_prompt_safety.py` | sentinel values, whole rows, descriptions, sample and row caps at any depth, page caps, untrusted-block containment, block-splice protection, typed tool errors reaching the prompt, prompt digests |
| `test_compat.py` | the `StrEnum` fallback matches the standard library's `str`, `format`, f-string, JSON and ordering behaviour |
### Verification performed

Three commands, all checked in:

```text
python -m pytest            # from the repo root; pytest.ini sets testpaths
python -m pytest tests      # from src/backend; the documented command
python verify_us4_person_b.py     # requirement-level, independent of the suite
python tools/mutation_check.py    # does the suite fail when it should?
python run_agent_tests.py         # the suite on a machine without pytest
```

- **`python -m pytest` — 440 passed**, with `langgraph 1.2.15` installed. This
  exercises the **real `langgraph.StateGraph`**, not the fallback. It includes
  `test_langgraph_actually_injects_the_run_scoped_runtime` (the nodes receive the
  framework's injected runtime, not a positional guess), the differential test that
  compares both engines field by field, a fault-injection matrix, a per-field
  boundary fuzz, 250 seeded property cases and an AST architecture scan.
- **`python -m pytest tests` from `src/backend` — 440 passed.** Same suite, the
  invocation the task names.
- **`verify_us4_person_b.py` — 17/17 requirement-level checks hold.** It asserts the
  requirements from the outside through the public entrypoints and prints, by name,
  what it does not verify. It needs only `pydantic`.
- **`tools/mutation_check.py` — 7/7 mutations killed.** Seven load-bearing lines are
  broken one at a time; the suite must notice each one. It found two real gaps while
  being written.
- **`run_agent_tests.py` — `passed=410 failed=0 skipped=0`** on Python 3.10 without
  `langgraph`, which is how the fallback path stays exercised.
- `compat.StrEnum` was compared against the real `enum.StrEnum` by running the same
  18 probes (`str`, `format`, format spec, f-string, `%s`, `json.dumps`, equality both
  ways, dict-key lookup, `hash`, `len`, sorting interleaved with plain strings,
  string methods, `in`, `repr`) under Python 3.13 (stdlib) and Python 3.10 (the
  fallback): **identical output on every probe**.
- `python -m mypy --check-untyped-defs app main.py tests/agent` — clean, resolving
  the venv's real dependency stubs.

**Defects these techniques caught, after the unit suite was already green.** The first
run against the real library failed every end-to-end case: LangGraph injects a
parameter *named* `runtime` as a keyword, and only when it is visible in the
callable's signature — the node-write guard's `*args, **kwargs` hid it, so every node
ran with no runtime. The fault matrix then found that a **failed** tool call was not
charged against `max_tool_calls`, making the loop bound free exactly when a source was
broken. The boundary fuzz found the resource **name** was never projected. And the
property tests found that a sample containing `</untrusted_source_data>` **closed the
untrusted block early**, leaving the rest of the source text in the prompt's
instruction region. Each has a regression test; see
[`us4-person-b-verification.md`](us4-person-b-verification.md) for the full account.

## 7. Provider limitations and known gaps

1. **`langgraph` is optional at runtime.** The graph is built against the real
   `StateGraph` API and **verified against `langgraph 1.2.15`** (440 passed, with the
   library's own `get_graph()` introspection). The fallback in `app/agent/graphs.py`
   exists so a checkout without the dependency still executes the same nodes; it is
   labelled, and `graph_runtime()` reports which one is live. The dependency is in
   `requirements.txt`.
2. **The live adapter is exercised against an SDK stub, not a real provider.** The
   stub asserts the request shape the adapter builds (`system`, `messages`, bound
   tools with `tool_choice: auto`, native `output_format` JSON schema), but whether
   the installed SDK accepts that exact wire format is `[Unverified]` — E-2/E-6 in
   `plans/LANGGRAPH_HARNESS_PLAN.md`.
3. **No checkpointer.** `run_routing_job` invokes the graph once and returns; the
   harness gate's "resume from a checkpoint" half needs the Postgres saver that
   Person A's persistence unblocks. The gate's other half — start a job, complete a
   tool call, persist a result, end with schema-valid output, with no real source and
   no live provider — is met by `test_fake_model_tool_loop.py`.
4. **Persistence is in-memory.** `RoutingRepository` is the declared seam, and it now
   includes `create_job` and `record_model_call` as well as the reads, so Person A's
   adapter supplies the durable model-call count the budget already consults. Until
   it exists, the count is durable only within one process.
5. **The fake model is deterministic, not intelligent.** It reuses a catalogue table
   id when the catalogue names one; it does not verify that every proposed attribute
   exists in the reused table's columns. Catalogue reuse remains D2 P1 per `D2-LG-3`.
6. **`contracts.py` gained one import** (`from app.agent.compat import StrEnum`) so the
   package imports on Python 3.10. The field set, validators and `CONTRACT_VERSION`
   are unchanged; the file's contract surface is still Person C's, and Gate 0 asks
   the team to review any edit to it.
7. **`propose` writes `status: "awaiting_review"`** when it accepts a draft, because
   `US4.md` §4.2 gives `propose` the `status` write and the graph ends there. Person D
   may prefer `running` until the package is persisted; that is a one-line change in
   one node and does not affect routing, which never reads `status`.
8. **`max_cost_usd` needs a price.** `run_routing_job(cost_per_1k_tokens_usd=…)` is
   the seam; there is no price table in this package, so with no price passed the
   ceiling is reported as unevaluable rather than silently treated as infinite or as
   zero.

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
