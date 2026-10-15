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
| `app/agent/models.py` | `ModelClient` protocol, `FakeModel`, `LiveModel`, mode resolution and provider validation | `resolve_model_mode`, `build_model_client`, `startup_banner`, `SUPPORTED_LIVE_PROVIDERS` |
| `app/agent/nodes.py` | `context`, `propose`, `tool_call` and the routers | `context_node`, `propose_node`, `tool_call_node`, `route_after_*` |
| `app/agent/deadlines.py` | The two node deadlines of `plans/LANGGRAPH_HARNESS_PLAN.md` §6.5 and an explicit statement of how strong each guarantee can be | `run_with_deadline`, `exceeded`, `tool_call_timeout_seconds`, `model_node_timeout_seconds` |
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
   durable count the budget reads. **A record that cannot be written ends the run** as
   a retryable `repository_unavailable`: the provider was already called, so continuing
   would leave a call the budget cannot see and re-arm the loop it exists to bound;
7. a malformed answer gets **one** repair call carrying the evidence, the previous
   response and the validation errors; if that also fails the run ends
   `invalid_model_output` and **no** fabricated draft is produced;
8. `ModelDraft.revision` is overwritten from `revision_count` after validation, so
   a wrong echo cannot trip the staleness guard;
9. an answer that overran `model_node_timeout_seconds` is recorded, refused and
   reported as `model_unavailable` - it never becomes the accepted draft. The check is
   **post-call**: it is not a cumulative "this node has already spent its budget" gate,
   because the budget names the elapsed time of one invocation; the job-wide pre-call
   gate is `max_wall_clock_seconds` in `_budget_stop`. See §7.10 for what each deadline
   can and cannot guarantee.

**`tool_call`** applies the dispatch contract per requested call:

1. validate arguments against the tool's own model;
2. check the job's source and resource scope (an out-of-scope source is also recorded
   as a security event);
3. **replay** a recorded `(job_id, tool_call_id)` - before the budget check, so a
   replay can never double-count a call;
4. check the tool-call budget **before** dispatch;
5. dispatch through the connector seam under `tool_node_timeout_seconds`, so a hung
   connector fails **its own call** with a typed `connector_timeout` result rather than
   blocking the node;
6. validate the connector's answer against the tool's declared **result** model, and
   enforce `max_tool_bytes` and `max_tool_rows`;
7. keep foreign diagnostics out, persist the typed result, and return a compact
   `ToolResultRef`. A **connector's** exception text is never persisted: the row carries
   one of `tools.CONNECTOR_ERROR_MESSAGES` (chosen by the typed code) and the text goes
   to a `DEBUG` log. Text the **harness** authored — argument validation, scope, budgets —
   is persisted as written, because it is the evidence the model adapts to.

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

**A provider is only advertised when an adapter exists for it.**
`models.SUPPORTED_LIVE_PROVIDERS` is `("anthropic",)` — the one SDK `LiveModel`
imports — and any other resolved provider is refused with the typed
`model_configuration_error` before a client is built, so the banner can never print
`provider=openai` on a process that will call the Anthropic SDK. Adding a provider
means adding an adapter **and** its id in the same change. Two related details:

* the API key is chosen **for the resolved provider** (its own `*_API_KEY`, then the
  provider-neutral `GENLEDGE_LLM_API_KEY`), not by "whichever key variable came first",
  so a machine holding keys for two vendors does not send one vendor's secret to the
  other's SDK;
* `OPENAI_API_KEY` is still counted as *configuration presence* for `auto`, so an
  operator who sets it gets a typed error naming what is supported rather than a
  silent fall-back to the fake model. That is the loud direction, and the test for it
  is `test_an_advertised_provider_is_refused_when_no_adapter_exists_for_it`.

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

**A connector's exception text is never persisted.** It is the one class of message in
this package that is written by foreign code, so the persisted row does not hold it at
all: `ToolDispatcher._error` builds the message from the typed code via
`tools.connector_error_message()`, whose lookup is **closed** — an unknown code (a
connector declares its own, so a code is foreign text too) gets the generic
`connector_error` sentence rather than its own prose. The exception's text goes to
`logger.debug` on `app.agent.tools`, the restricted diagnostic channel: `DEBUG`, not
`INFO`/`WARNING`, so a default-configured process does not emit it either.

The reason it is built this way rather than sanitised: `redact_message` is a **blocklist**,
and a blocklist leaks the first credential shape nobody enumerated — a session cookie, a
vendor-specific header, an opaque token with no recognisable prefix. Redaction is still
applied as defence in depth on the paths that embed foreign text in harness-authored prose
(today the `storage_failed` message quoting a control-store fault), but nothing about the
connector guarantee depends on the list being complete. The control test proves a
credential-bearing message is not flattened into `[redacted]` either: the model gets a
sentence it can read and the code it adapts to.

Messages the **harness** authors are persisted verbatim, and that is deliberate: an
argument-validation report, a scope refusal, a budget stop and a row/byte cap are our own
strings, and they are the evidence the model needs to correct itself. Making every message
generic would satisfy "no connector text is persisted" while destroying that.

Prompt digests are canonicalised for line endings. `manifest()` hashes
`canonical_prompt_text(file)` - CRLF and lone CR are folded to LF - so a
`core.autocrlf=true` checkout (this repository's setting, and the Windows default)
agrees with `manifest.json` instead of failing the digest check for a reason unrelated
to the prompt. Only line endings are normalised: an instruction edit, a front-matter
edit and a trailing space all still change the hash, and
`tools/prompt_manifest.py` normalises identically so a regenerated manifest cannot
drift by platform.

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
| `test_adapters_and_modes.py` | `auto`/`live`/`fake` resolution; startup banner has no secret; an unsupported provider is refused and the key sent belongs to the resolved provider; both adapters satisfy one contract and both end with a schema-valid draft |
| `test_prompt_safety.py` | sentinel values, whole rows, descriptions, sample and row caps at any depth, page caps, untrusted-block containment, block-splice protection, typed tool errors reaching the prompt, prompt digests and their CRLF/LF stability |
| `test_remediation_regressions.py` | one named test per confirmed defect of every review cycle, including section `I`: connector exception text kept out of persisted results at a fail-safe boundary, both node deadlines enforced, an unrecordable model call ending the run |
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
>
> **A fourth review produced five follow-up findings, all addressed in section `I` of
> `tests/agent/test_remediation_regressions.py`:** (1) a connector's own exception text
> was persisted verbatim into `ToolResult.message`, so a driver quoting its DSN wrote a
> credential into the control store - it is now **not persisted at all** (see the
> security-follow-up note below and the findings table in §7);
> (2) an unsupported `GENLEDGE_LLM_PROVIDER` was accepted and then served by the
> Anthropic SDK while the banner named the other vendor - the provider is now validated
> against `models.SUPPORTED_LIVE_PROVIDERS` and the API key is chosen for the resolved
> provider; (3) a `record_model_call` failure was swallowed into a log line, so the
> durable count the model budget reads could silently stop charging calls - it now ends
> the run as a retryable `repository_unavailable`; (4) `model_node_timeout_seconds` and
> `tool_node_timeout_seconds` were declared and read nowhere - the tool call is now
> bounded hard at the connector seam with a typed `connector_timeout`, and the model
> node refuses an over-budget answer, with §7.10 stating plainly which of the two is
> preemption and which is a deadline; (5) prompt digests were taken over raw bytes, so a
> `core.autocrlf=true` checkout disagreed with `manifest.json` - line endings are now
> canonicalised, without weakening the content check.

### Security follow-up: the connector redaction was still a blocklist

The fourth-cycle fix for finding 1 redacted connector exception text with the credential
patterns. The revision report's own residual list admitted the consequence: *"a credential
shape nobody enumerated still reaches `ToolResult.message`"* — which contradicts the
requirement the fix was written for. That is not a tuning problem. A pattern list is a
blocklist, and a blocklist leaks the first shape nobody thought of: a session cookie, a
vendor-specific header, an opaque token with no recognisable prefix.

The boundary moved rather than the list widened:

| | Fourth cycle | Now |
| --- | --- | --- |
| Persisted message | `redact_message(<connector's text>)` | `tools.connector_error_message(<typed code>)` — a **closed** lookup |
| Unenumerated credential shape | persisted unless a pattern matched | cannot be persisted; the row never held the text |
| Ordinary connector prose | persisted verbatim | replaced by the fixed sentence for its code |
| Unknown connector-declared code | persisted with its own prose | generic sentence; the code became `connector_error` too — the `error_code` row below is that correction |
| An undeclared field's name in a validation report | persisted (pydantic's location *is* the connector's key) | whitelisted against the declared model fields; `<undeclared-field>` otherwise |
| Operator diagnostics | in the row | `logger.debug` on `app.agent.tools` — `DEBUG`, so a default process emits nothing |
| The typed `error_code` | a connector-declared code was persisted **verbatim** — any text, any length, unredacted — while the prompt layer projected it through `redact_value` *because* it was untrusted | validated against `tools.DECLARED_ERROR_CODES`, the envelope of `plans/LANGGRAPH_HARNESS_PLAN.md` §8.4 plus this module's own codes; an undeclared code becomes `connector_error` and the declared string goes to the same `DEBUG` channel |
| A validation report's location | rendered verbatim, so an undeclared field's **connector-chosen name** was persisted | whitelisted against the declared result/argument model fields; an undeclared name becomes `<undeclared-field>`, a declared one and pydantic's own `msg` still name the problem |
| Harness-authored refusals | persisted verbatim | **unchanged** |
| `error_code` | preserved | preserved |

`test_i1_*` (17 test functions, 24 collected cases, in the "I" section) verifies this
against the **constructed and persisted** rows rather than against the redaction helper: a
known DSN, a known `Authorization` header, an unfamiliar sentinel value
(`X-Acme-Session=Zx9Qv2Lm7Rt4Wp1Kd8Nh5Bs3Gy6Jc0Fa`) that `redact_message` provably returns
unchanged — that non-match is asserted, so the case cannot silently stop proving itself —
an unfamiliar *field name* on the validation-report route, and an unfamiliar,
5000-character *code* on the `error_code` route, which are the two further leaks an
independent review and a follow-up question found. `python tools/sensitivity_check.py`
reverts the boundary and each of the three routes in turn; **9 of 9** mutations are killed,
each by named tests.

**Three foreign-text routes, all closed.** The message, the `error_code` and a validation
report's location each carried connector-authored text into a persisted `ToolResult` at
some point in this work; each was found by a different reviewer or question, and each is
now a closed set rather than a filter:

| Route | What the row holds now |
| --- | --- |
| `message` | one of `CONNECTOR_ERROR_MESSAGES`, chosen by the typed code |
| `error_code` | one of `DECLARED_ERROR_CODES`, or `connector_error` for anything else |
| validation `location` | declared model field names and integer indices, or `<undeclared-field>` |

The pattern is worth naming because it is the actual design rule here: **a persisted field
that can carry foreign text gets a closed set, not a sanitiser.** A fourth route would be a
fourth whitelist, and the whitelists are asserted to stay in step with each other by
`test_i1_every_code_the_harness_itself_emits_is_declared`.

### Follow-up review (fourth cycle): the five findings

Five findings were raised against commit `99589e9` and are closed here. Each has a
named regression test in section `I` of `tests/agent/test_remediation_regressions.py`
(the provider-routing and prompt-digest cases live beside their own subject modules).

| Finding | Was | Now |
| --- | --- | --- |
| Connector error redaction | The connector's exception text was stored verbatim as `ToolResult.message`, so an HTTP client quoting an `Authorization` header, or a driver quoting the DSN it could not open, wrote credential material into the control store - and it was rendered back on any later read (`get_tool_result`). | **Revised after a targeted security follow-up.** The first fix redacted the text with the credential patterns; that was a blocklist, and the follow-up finding correctly observed that an unenumerated credential shape still reached the row. The boundary is now **fail-safe**: connector exception text is not persisted at all. `_error` builds the message from the typed code through the closed lookup `tools.connector_error_message()` (`CONNECTOR_ERROR_MESSAGES`), the text goes to `logger.debug` on `app.agent.tools`, and `redact_message` remains only as defence in depth on the `storage_failed` path. Harness-authored refusals are still persisted verbatim. Tests: `test_i1_*` (10 cases, including an unfamiliar credential shape and a control that our own refusals keep their detail). |
| Live provider selection | `GENLEDGE_LLM_PROVIDER` accepted any string; `build_model_client` then called the Anthropic SDK regardless, while the startup banner printed `provider=openai`, and the API key could come from `OPENAI_API_KEY`. | `models.SUPPORTED_LIVE_PROVIDERS` is the one adapter that exists; the provider is validated at resolution (live/auto) **and** in `build_model_client` and `LiveModel`, raising the existing typed `model_configuration_error`. The key is chosen for the resolved provider (its own `*_API_KEY`, then the neutral `GENLEDGE_LLM_API_KEY`). Tests: `test_an_advertised_provider_*`, `test_build_model_client_refuses_*`, `test_live_model_refuses_*`, `test_the_api_key_sent_belongs_*`. |
| Durable model-call records | `_record_model_call` caught a store fault and emitted `logger.warning`, then the run continued. Since `get_model_call_count` is the model budget's authority, an unrecorded call could be spent again and `max_model_calls` stopped binding precisely when the store was unhealthy. | It raises the typed `repository_unavailable` and every call site returns a terminal failure: the main call, the adapter-raised path, and the single repair. Tests: `test_i3_*`. Stated limit: recording after the fact cannot make a remote invocation transactional - it makes the **harness** refuse to continue. |
| Execution timeouts | Both budgets were declared in the frozen contract and read nowhere; a hung connector blocked the worker indefinitely. | `app/agent/deadlines.py` owns both. `tool_node_timeout_seconds` is a **hard** bound on one connector call (daemon worker + wait), reported as the typed `connector_timeout`; `model_node_timeout_seconds` is a **deadline**: an over-budget answer is recorded, refused and reported as `model_unavailable`, because a synchronous SDK call cannot be preempted in-process. The hard per-attempt bound is the provider request timeout, derived per §6.5. Tests: `test_i2_*`. |
| Prompt manifest hashing | `manifest()` hashed raw file bytes, so a `core.autocrlf=true` checkout (this repository's setting) produced CRLF digests that disagreed with `manifest.json` on a fresh clone. | `prompts.canonical_prompt_text` folds CRLF/lone CR to LF before hashing, in `manifest()` and in `PromptSpec.sha256`; `tools/prompt_manifest.py` normalises identically. Only line endings: instruction, front-matter, placeholder and trailing-space edits all still change the digest. Tests: the four `manifest hashing is a property...` cases in `test_prompt_safety.py`. |

Two consequences recorded rather than glossed: the tool-call timeout leaves its daemon
worker behind if the connector never returns (the caller is bounded, the thread is not),
and `tool_node_timeout_seconds=0` means "unbounded" rather than "fail immediately", so the
shipped default is what actually bounds a call.

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
   zero. `max_revisions` is likewise declared in the frozen budget surface and read
   nowhere (US5 owns revision).
9. **`GENLEDGE_LLM_EFFORT` is read and stored but never sent.** The provider documents
   effort as a request control whose home has moved between top level and
   `output_config`; sending it is a behaviour change that cannot be validated without a
   provider, so it is left unsent and recorded here instead of guessed at.
10. **The two node timeouts are enforced, but not with the same strength** — the
   difference is a property of synchronous Python, not a design choice, and
   `app/agent/deadlines.py` states it in the module docstring:

   | Budget | Enforced at | Guarantee |
   | --- | --- | --- |
   | `tool_node_timeout_seconds` | the connector seam in `ToolDispatcher._call_connector` | **Hard.** The connector runs on a daemon worker and the node waits at most the budget, so a hung connector fails its own call with a typed `connector_timeout` result and the run continues to `propose`. `0` disables the bound. |
   | `model_node_timeout_seconds` | `propose` and its repair call | **Deadline, not preemption.** A synchronous provider SDK call cannot be interrupted in-process, so the check is **post-call**: an answer that overran the budget is recorded durably, refused and reported as `model_unavailable`, and it never becomes the accepted draft. There is deliberately no cumulative pre-call gate here — this budget names the elapsed time of one invocation, and the job-wide pre-call gate is `max_wall_clock_seconds` in `_budget_stop`. The **hard** per-attempt bound is the provider client's own request timeout, derived as `request × (1 + retries) + 60 s` in `models.derived_model_timeout_seconds` (960 s at the documented defaults). |

   The residual risk, stated rather than hidden: a connector that never returns leaves
   its daemon worker behind (the *caller* is bounded, the thread is not), and a provider
   call that hangs is bounded only by the SDK's own timeout and retry policy — level 1
   of §6.5, which is the layer the plan assigns it to.

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
