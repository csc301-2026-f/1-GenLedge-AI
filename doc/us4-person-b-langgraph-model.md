# US4 Person B - LangGraph Routing Workflow

Finalized plan and handoff for the Person B slice of US4 on branch
`us4/person-b-langgraph-model` (base `us4/integration`).

Authoritative references:

- `plans/user-stories/US4.md` §4 (graph), §5 (contracts, prompt boundary), §8 (tests)
- `plans/us4-four-person-task-split.md` §"Person B", §"Integration Gates"
- `plans/LANGGRAPH_HARNESS_PLAN.md` §5-§9
- `doc/agent-harness-architecture.md` (harness gate, line 238)
- `src/backend/app/agent/contracts.py` (frozen contracts - imported, never redefined)

## 1. What was built

```text
START -> context -> (propose | END)
propose -> (tool_call | END)
tool_call -> propose
```

Three nodes, exactly. No human node, no revision loop, no validation node - the
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
| `app/agent/compat.py` | A `StrEnum` shim for a Python 3.10 floor. **No longer used by the agent package** — `contracts.py` was restored to the frozen `from enum import StrEnum`, so nothing in `app/agent` imports this except its own test (`tests/agent/test_compat.py`). Retained because that test is another contributor's and still passes. | `StrEnum` |

## 2. Node behaviour, as implemented

**`context`** loads the frozen inventory for `source_snapshot_ids` and the optional
catalogue (`None` = cold start). No model call. An empty or missing inventory is a
typed `empty_inventory` failure routed straight to `END` - never an empty proposal.
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
3. **replay** a recorded `(job_id, tool_call_id)` - before the budget check, so a
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
- the mode, provider and model, and never a secret. `main.py` calls `init_agent(app)`
once, so the banner is emitted at process start; a half-configured live deployment is
logged as a warning instead of crashing the process. `app/__init__.py` deliberately
does **not** import `app.agent` or Flask at module scope, so importing the harness
never requires a web framework.

## 5. Prompt boundary

`app/agent/prompts.py` is the only path from the process to a prompt. The
projection functions are typed against `InventoryView`, `CatalogueView` and
`ToolResult` - never the graph state, a `dict`, or `Any` - so passing a raw row, a
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
literally inside the untrusted block - it can neither crash the renderer nor splice
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

```text
cd src/backend
..\..\.venv\Scripts\python.exe -m pytest tests       # the documented command
python verify_us4_person_b.py     # requirement-level, independent of the suite
python tools/mutation_check.py    # does the suite fail when it should? (throwaway copy)
python run_agent_tests.py         # the suite on a machine without pytest
```

Numbers produced by an earlier cycle, kept only as a record - **re-run them, do not cite
them**: `458 passed` with `langgraph 1.2.15`; `423 passed, 5 skipped` on Python 3.10 with
no `langgraph`; `verify_us4_person_b.py` 17/17, now 19/19 including the two contract
checks; `14/14` mutations killed, now 31 mutations on an isolated copy. The test counts
are a liability to quote because this branch no longer reproduces them from a clean tree
without the venv on `PATH`; the commands above are the claim, not the numbers.

- `verify_us4_person_b.py` asserts the requirements from the outside through the
  public entrypoints and names, at the end, what it cannot verify.
- `tools/mutation_check.py` copies the current implementation - uncommitted work
  included - into a temporary directory, runs the copy once unmutated, then breaks one
  load-bearing line at a time and requires the suite to notice. It never writes to the
  development tree, so a kill cannot leave a mutation behind; it verifies each restore
  and fingerprints the tree before and after. Signal handlers are installed but are not
  the guarantee, and the docs no longer imply otherwise: on Windows a `SIGTERM` is an
  outright termination and no handler runs.

## 7. Provider limitations and known gaps

> **Remediation applied after a third review. Read this block before the list below.**
> The third review was of the *working tree*, not the commits, and the tree was broken:
> `tools/mutation_check.py` mutated the real checkout and was killed before its restore,
> leaving `if True:  # MUTATED` in `app/agent/prompts.py`. The suite was red (4 failed,
> 454 passed) and the "458 passed / 14-14 mutations" claims below were unreproducible
> from the delivery. Also fixed in that cycle: typed storage failures in `propose`,
> `tool_call` **and the runner's own pre-graph reads** (`get_inventory`, `get_catalogue`,
> `create_job`); a harness-checked replay identity, so a reused `tool_call_id` can no
> longer return another call's payload; a tool-round bound, so a model re-requesting one
> id can no longer loop unchecked - note that at the shipped defaults
> `max_tool_calls=40` exceeds `max_model_calls=20`, and since every tool round costs a
> model call the **model** budget is the binding bound there, with the round bound
> stopping the loop in the tighter configurations the tests use; replayed references are
> no longer duplicated; pre-dispatch refusals are no longer persisted; redaction covers
> non-string scalars, phone/address/identifier patterns, credential-shaped keys, and a
> restricted key's whole subtree; a bad node write is a typed `invalid_state_update`
> rather than an escaping `ValueError`; and the live adapter sends `output_config.format`
> instead of the stale `output_format`.
>
> **A second review of that cycle then found three more defects, fixed here:** the
> nested-credential redaction leak the rework itself introduced; thirteen stale
> mutation-battery anchors, which let the tool print "all mutations killed" and exit 0
> while testing none of the redaction, replay or scope fixes; and the three runner-level
> store faults.
>
> `doc/us4-person-b-verification.md` carries the full record, including what remains
> unverified - notably that the mutation battery has **no verified run** in this
> environment, and that no provider call has ever been made. The itemised gaps below are
> the ones that survive.

1. **`langgraph` is optional at runtime.** The graph is built against the real
   `StateGraph` API and **verified against `langgraph 1.2.15`** (with the
   library's own `get_graph()` introspection). The fallback in `app/agent/graphs.py`
   exists so a checkout without the dependency still executes the same nodes; it is
   labelled, and `graph_runtime()` reports which one is live. The dependency is in
   `requirements.txt`. **Known limitation:** on the fallback path nothing asserts the
   built graph's node or edge set - `graph_shape()` returns declared constants, and only
   the two LangGraph-gated tests introspect the compiled graph. Adding a fourth node
   would therefore pass the whole suite under `GENLEDGE_GRAPH_RUNTIME=local-fallback`.
2. **The live adapter is exercised against an SDK stub, not a real provider.** The
   stub asserts the request shape the adapter builds (`system`, `messages`, bound
   tools with `tool_choice: auto`, native `output_config.format` JSON schema). The stub
   accepts any keyword it is handed, so it cannot tell a correct parameter name from a
   stale one - that is exactly how `output_format` survived until now. `anthropic` is
   declared in `requirements.txt` but **not installed here**, no credential and no
   endpoint are configured, and `tools/live_provider_check.py` has never run. Whether a
   provider accepts the payload is `[Unverified]` - E-2/E-6 in
   `plans/LANGGRAPH_HARNESS_PLAN.md`.
3. **No checkpointer.** `run_routing_job` invokes the graph once and returns; the
   harness gate's "resume from a checkpoint" half needs the Postgres saver that
   Person A's persistence unblocks. The gate's other half - start a job, complete a
   tool call, persist a result, end with schema-valid output, with no real source and
   no live provider - is met by `test_fake_model_tool_loop.py`.
4. **Persistence is in-memory.** `RoutingRepository` is the declared seam, and it
   includes `create_job` and `record_model_call` as well as the reads, so Person A's
   adapter supplies the durable model-call count the budget already consults. Until
   it exists, the count is durable only within one process. Note the consequence the
   remediation tests surface: because the count is durable and job-scoped, running the
   *same* `job_id` twice consumes the budget twice, and the second run is correctly
   refused rather than replaying.
5. **The fake model is deterministic, not intelligent.** It reuses a catalogue table
   id when the catalogue names one; it does not verify that every proposed attribute
   exists in the reused table's columns. Catalogue reuse remains D2 P1 per `D2-LG-3`.
6. **`contracts.py` is unmodified.** An earlier revision of this branch swapped its
   `from enum import StrEnum` for `from app.agent.compat import StrEnum`, so the module
   would import on a Python 3.10 floor. The team decided the frozen contract is not to be
   modified, so that import was **restored** and the file is now byte-identical to the
   blob on `us4/integration` (line-ending differences aside, since `core.autocrlf=true`
   checks the file out with CRLF on Windows). `verify_us4_person_b.py` asserts that
   identity against the working tree, so an uncommitted edit is caught too, and it fails
   if the delta-declaration list it used to carry is ever repopulated.

   **Consequence to be aware of:** `enum.StrEnum` is Python 3.11+, so `contracts.py` now
   requires 3.11+ — the 3.10 floor that `app/agent/compat.py` was written for no longer
   applies to this package. The suite runs on the venv's Python 3.12 and passes. On 3.10
   the failure is an immediate `ImportError` of a documented name on any import of
   `app.agent.contracts`, not silent misbehaviour. `app/agent/compat.py` and its test
   remain in the tree and still pass: `test_compat.py` imports the shim directly, so it is
   not dead code, but nothing in the agent package depends on it any more.
7. **`propose` writes `status: "awaiting_review"`** when it accepts a draft, because
   `US4.md` §4.2 gives `propose` the `status` write and the graph ends there. Person D
   may prefer `running` until the package is persisted; that is a one-line change in
   one node and does not affect routing, which never reads `status`.
8. **`max_cost_usd` needs a price.** `run_routing_job(cost_per_1k_tokens_usd=…)` is
   the seam; there is no price table in this package, so with no price passed the
   ceiling is reported as unevaluable rather than silently treated as infinite or as
   zero. Likewise `max_revisions`, `model_node_timeout_seconds` and
   `tool_node_timeout_seconds` are declared in the frozen budget surface and read
   nowhere; the connector call has no timeout of its own.
9. **`GENLEDGE_LLM_EFFORT` is read and stored but never sent.** The provider documents
   effort as a request control whose home has moved between top level and
   `output_config`; sending it is a behaviour change that cannot be validated without a
   provider, so it is left unsent and recorded here instead of guessed at.

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
