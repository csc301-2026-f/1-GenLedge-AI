# How this slice is verified - and what each technique actually catches

Every serious defect found in the US4 Person B work was found by a technique
*other* than a passing test. This file records which technique caught what, so the
next person can pick the right tool instead of writing more unit tests.

The file is deliberately plain ASCII: an earlier revision mixed UTF-8 punctuation with
a `cp1252` round trip and was not decodable by strict readers. A verification record
that cannot be opened is not a verification record.

## Techniques applied, and what each one caught

| # | Technique | Command | What it caught that tests could not |
| --- | --- | --- | --- |
| 1 | **Adversarial review by a second model** | a GLM review of the committed diff | The blocker: source data containing `{{...}}` crashed `render()` out of the graph, and a value naming a declared placeholder spliced another prompt block into itself. Both reachable from ordinary source text. |
| 2 | **Run against the real dependency** | `python -m pytest` with `langgraph` installed | LangGraph injects a parameter *named* `runtime` as a keyword, and only if it is visible in the signature. The write-guard's `*args, **kwargs` hid it, so **every node ran with no runtime**. A hand-written stand-in can never validate the convention of the library it replaces. |
| 3 | **Observe the running process** | `python -c "import main"` | The startup banner logged at INFO into a root logger with no handler, so the resolved model mode silently vanished - the requirement was unmet while every test passed. |
| 4 | **Strict type check against real stubs** | `mypy` with the venv on `--python-executable` | Fixture helpers declared `type: str` where the contracts require `SourceType`; the runtime `mode="before"` validators had been masking the mismatch. Also a `**{...}` unpack whose types mypy widens and rejects. |
| 5 | **Run the documented command, not a proxy** | `python -m pytest tests` | There was no `pytest.ini`, so this collected nothing from the repo root. A shim that "worked" hid a build-configuration defect. It then caught a second one: `GENLEDGE_GRAPH_RUNTIME=local-fallback` - which both docs advertised - failed 2 tests, because the `get_graph()` cases skipped on library *availability* rather than on the engine actually selected. |
| 6 | **Fault-injection matrix** | `test_fault_injection.py` | A failed tool call was **not charged** against `max_tool_calls`, so a source that fails every read made the loop bound free - the graph's only defence against a runaway model stopped applying exactly when it mattered. Also: a connector growing an undeclared field was silently absorbed rather than rejected, because per-tool result models did not exist. |
| 7 | **Per-field sentinel fuzz** | `test_prompt_boundary_fuzz.py` | The resource **name** was loaded and never projected, so the model saw only opaque ids (`resource_0`) while AC6 asks it to reason over names. Per-field poisoning is what a fixed blocklist cannot do. |
| 8 | **Property-based tests with a seeded generator** | `test_properties.py` (250 cases) | Source text containing `</untrusted_source_data>` **closed the block early**, leaving the rest of the sample in the instruction region of the prompt - the sharpest form of the injection risk the boundary exists to bound. Fixed by neutralising delimiter tokens in every source-derived string. |
| 9 | **Architecture enforcement by AST scan** | `test_architecture_rules.py` | `graph.py` imported `langgraph.errors` directly, so the "one seam for the optional dependency" claim was false; `graph_runtime()` could have disagreed with what actually ran. |
| 10 | **Differential test across implementations** | `test_both_runtimes_produce_the_same_run` | The two graph engines were never compared on equal terms: the fallback only ran where LangGraph was absent. Both now run in one session and their states are compared field by field. |
| 11 | **Mutation check** | `python tools/mutation_check.py` | The three-sample projection cap had no test that could fail - the contract's `max_length=3` made it unreachable. `test_the_projection_caps_samples_even_for_an_out_of_contract_inventory` constructs an out-of-contract inventory and kills that mutation. |
| 12 | **A second, fresh adversarial review** | a GLM review of the whole slice, with an independent mutation battery | **The delimiter fix was incomplete.** `snapshot_id`, `resource_id`, the field path, the tool name, `tool_call_id` and `previous_response` were all still rendered raw, so six forgery routes remained - and the tests were complicit, because the fuzz list poisoned only the two fields that *were* neutralised. Also: redaction missed `mysql://` and `mongodb+srv://` DSNs and emails embedded in a sentence (its own docstring claimed otherwise); a lines-only inventory raised `IndexError` out of `run_routing_job`; and `auto` mode treated a provider *name* as configuration, so one harmless variable failed every job. |
| 13 | **Requirement-level script, independent of the suite** | `python verify_us4_person_b.py` | Says whether the *task's requirements* hold through the public entrypoints, so a suite and an implementation wrong in the same way still fail. It also prints, by name, what it cannot check. |
| 14 | **A third review, on the working tree rather than the commits** | GLM review + `git status`/`git diff` | The tree did not match the commits: `tools/mutation_check.py` mutated the *real* checkout, was killed mid-run, and left `if True:  # MUTATED` in `prompts.py` plus its own `.bak` beside it. The suite was red and the documented "14/14, 458 passed" was unreproducible from the tree as delivered. A green report about a broken delivery is the failure mode this technique exists to catch - see the remediation record below. |

**The pattern worth noticing:** items 6-9 each found a *real defect* on their first run,
and all four were in code that already had passing tests. None of them was found by
adding another example-based test.

## The standing commands

```powershell
# .venv at the repository root; `python` on PATH has no pytest and no pydantic.
..\..\.venv\Scripts\python.exe -m pytest tests   # from src/backend
python verify_us4_person_b.py    # requirement-level checks, independent of the suite
python tools/mutation_check.py   # mutation battery, on a throwaway copy
python tools/sensitivity_check.py  # do the regression tests fail when their fix is reverted?
python run_agent_tests.py        # the agent suite on a machine without pytest
python tools/prompt_manifest.py  # regenerate the prompt digests after a prompt edit
python tools/live_provider_check.py   # opt-in: needs a provider key (see below)
```

Types (mypy lives outside the venv on this machine, so it borrows the venv's
dependency stubs):

```powershell
cd src\backend
mypy --python-executable ..\..\.venv\Scripts\python.exe --explicit-package-bases `
     --check-untyped-defs app main.py tests\agent
```

Run the suite on a specific engine while LangGraph is installed:

```powershell
$env:GENLEDGE_GRAPH_RUNTIME = "local-fallback"   # or "langgraph", or "auto"
python -m pytest
```

## Remediation record (third review cycle)

The third review found the working tree itself to be the defect. What changed, and what
it cost, recorded here because the earlier "all green" claim was true of the commits and
false of the delivery.

### The mutation battery was the hazard, not the safeguard

`tools/mutation_check.py` wrote its mutations into `src/backend`, not a copy. Its restore
was a bare `finally:`, so a kill skipped it, and the checkout was left with a disabled
prompt cap. The tool also had no baseline run and decided "killed" from a non-zero exit
alone, which means an already-failing tree reports every mutation as killed and still
exits 0.

It now:

* copies the current implementation - **including uncommitted work** - into a temporary
  directory and mutates only that. The development tree is never written to, so a kill at
  any instant costs a stale temporary directory, not a corrupted checkout;
* refuses to start unless the copy looks like a backend, contains `pytest.ini`, and is
  not inside the repository — the one exception is the explicit, gitignored
  `.mutation-scratch` directory, accepted by identity because a confined sandbox may
  permit nowhere else;
* runs the unmutated copy **first** and aborts if it is not green;
* re-hashes each file after restoring it and aborts if the restore did not land;
* fingerprints the tracked implementation files before and after the run and fails if any
  changed;
* still installs `SIGINT`/`SIGTERM` handlers, but the README-level claim is the weaker,
  honest one: on Windows `os.kill(pid, SIGTERM)` terminates the process outright and no
  handler runs. The isolation is what makes that safe; the handlers are a convenience.

Its mutation list grew from 14 to 31, because the third review found the shipped set to
be a narrow sample: it targeted no redaction rule, no replay-identity check, no storage
fault, and no cross-resource field scope. The list was then re-derived against the
current source, because **13 of the 31 anchors had gone stale** once the fixes changed
the lines they matched — and a skipped mutation was being reported as a killed one, so
the tool printed "All 31 mutations were killed by the suite" and exited 0 while testing
none of those behaviours. An anchor miss now exits non-zero and names the labels, and a
run whose suite fails to *collect* is reported as `[BROKEN]` instead of counted as a
kill, so a collection error can no longer inflate the result.

**The battery has not been executed in this environment.** It refuses to mutate the
repository by design, and this session's sandbox denies every location it can copy to:
`C:\Windows\Temp` and the profile temp directory are refused, and a new nested tree under
the in-workspace scratch directory is refused with `WinError 5`. The battery therefore
**has no verified run**, and nothing here should be read as one — its anchors, its
parsing and its exit-code contract were checked; its kills were not. The substitute
evidence for the same question is the revert check recorded below.

### The regression tests were checked for sensitivity, not just presence

A test that cannot fail proves nothing, so the fixes were reverted in a throwaway copy
one at a time and the matching regression test was required to fail. The replay-identity
check, the duplicate-id guard, the non-string-scalar content rule, the nested-credential
rule, the three runner-level store faults and the traversal token each produced a named
assertion failure. `tools/mutation_check.py` asks the same question at a larger scale and
is the tool to run once a writable scratch location exists.

**Fifth cycle (the five follow-up findings).** The same check was repeated for each of
them, by reverting the fix in place, running the matching tests, and restoring the file
(the tree was fingerprinted afterwards and the suite re-run green). Every revert was
caught, by name:

| Fix reverted | Test that failed |
| --- | --- |
| `redact_message` at the persisted `ToolResult.message` | `test_i1_a_connector_exception_cannot_write_a_credential_into_the_result` — all six parametrisations |
| `_call_connector`'s deadline (dispatch calls the connector directly again) | `test_i2_a_hung_connector_fails_its_call_not_the_node` |
| The model-node deadline check | `test_i2_an_over_budget_model_answer_is_refused_and_charged` |
| `_record_model_call`'s fail-closed raise (back to a `logger.warning` and continue) | `test_i3_a_model_call_whose_record_cannot_be_written_ends_the_run`, `test_i3_a_raising_adapter_whose_record_cannot_be_written_ends_the_run`, `test_i3_a_repair_call_whose_record_cannot_be_written_ends_the_run` |
| `SUPPORTED_LIVE_PROVIDERS` widened to include `openai` | `test_an_advertised_provider_is_refused_when_no_adapter_exists_for_it`, `test_build_model_client_refuses_an_unsupported_provider`, `test_live_model_refuses_an_unsupported_provider` |
| `canonical_prompt_text`'s line-ending fold (`return raw.decode("utf-8")`) | `test_a_crlf_checkout_hashes_the_same_as_an_lf_checkout`, `test_the_canonicalisation_matches_the_regeneration_tool` |

This is the substitute for `tools/mutation_check.py`, which still has no verified run
here — see above. It is weaker evidence than the battery would be: it reverts one whole
fix at a time rather than one line at a time, and it was run by the same agent that made
the fixes.

**It is now a tool, not a claim.** `python tools/sensitivity_check.py` copies the current
implementation (uncommitted work included) into the ignored `.mutation-scratch/`, runs the
unmutated copy first and refuses to score anything if that is not green, then applies one
named revert at a time, requires the tests that claim to cover it to fail **by name**, and
restores the file — verifying that the restore landed. It exits non-zero on any single
`SURVIVED`, `STALE` (an anchor that no longer matches, which is how a battery starts
lying) or `BROKEN` entry. Its last run here reported `KILLED=9 of 9 mutations`, naming the
nine finding labels and the failing test ids; the development tree was unchanged afterwards
(`git status` identical, suite green). It also earned its place during this work: the
`error_code` change renamed a test, and the tool's first run after that reported the mutation
as `SURVIVED` with the stale expected name — which is exactly the "a battery that silently
skips is a battery that lies" failure it exists to prevent, caught in practice rather than
described.

### Targeted security follow-up: the connector redaction was a blocklist

The fifth cycle's finding 1 was closed by redacting connector exception text with the
credential patterns. A targeted follow-up then observed what the report itself admitted:
*"a credential shape nobody enumerated still reaches `ToolResult.message`"* — which
contradicts the requirement it was meant to satisfy. Redaction **cannot** close that: any
pattern list leaks the first shape it does not know.

The correction moves the boundary rather than widening the list. Connector exception text
is no longer persisted at all:

| | Before (fifth cycle) | At that fix | Now (round 4) |
| --- | --- | --- | --- |
| Where the message comes from | `redact_message(<connector's text>)` | `tools.connector_error_message(<typed code>)` — a **closed** lookup | unchanged |
| An unenumerated credential shape | persisted unless a pattern happened to match | cannot be persisted: the row never held the text | unchanged |
| A message with no restricted shape | persisted verbatim | replaced by the fixed sentence for its code | unchanged |
| An unknown connector-declared code | persisted with its own prose | generic `connector_error` sentence; **the code itself was still stored verbatim** | replaced by `connector_error`; the declared code goes to `DEBUG` — see `DECLARED_ERROR_CODES` below |
| Diagnostics for an operator | in the row | `logger.debug` on `app.agent.tools` (`DEBUG`, so a default process emits nothing) | unchanged |
| Harness-authored refusals (validation, scope, budget) | persisted verbatim | **unchanged** — persisted verbatim, which is what the model corrects itself from | unchanged |
| Typed `error_code` | preserved | preserved | **validated** against the declared envelope |

The middle column is what the message fix did on its own; the last column is the current state.
The `error_code` row is the reason the last column exists at all: making the message generic
left the *code* — also connector-declared — persisted verbatim, any length, unredacted, and the
third route below is where that was found and closed.

Verified by `test_i1_*` (17 test functions, 24 cases) against the **constructed and
persisted** rows, not against the redaction helper: a known DSN, a known `Authorization`
header, and an *unfamiliar* sentinel (`X-Acme-Session=Zx9Qv2Lm7Rt4Wp1Kd8Nh5Bs3Gy6Jc0Fa`)
that `redact_message` provably returns unchanged — the test asserts that non-match
explicitly, so it cannot silently stop proving the fail-safe case. The sensitivity tool
reverts the new boundary (`persisted_message = redact_message(details)`, the fifth-cycle
design) and **six** tests fail, including the unfamiliar-shape case.

**A third route was found by a follow-up question, and is closed too.** The message had been
made generic while `error_code` — also connector-declared, `error_code: str | None` with no
pattern or enum, on a model that is *not* the frozen contract — was still persisted
verbatim: any text, any length, unredacted, and it is the field the model acts on. Probed and
confirmed before the fix (`X-Acme-Session-Zx9Qv2…` as the code, persisted; a 5000-character
code, persisted). `prompts.py` had been projecting `error_code` through `redact_value`
*because* the model treated it as source-derived, so the row was trusting a value the prompt
boundary did not. It is now validated against `tools.DECLARED_ERROR_CODES` — the eight-code
envelope of `plans/LANGGRAPH_HARNESS_PLAN.md` §8.4 plus this module's own storage, dispatch
and connector-transport codes — and an undeclared code becomes `connector_error` with the
declared string on the `DEBUG` channel. The frozen contract is untouched: `ToolResultRef`
carries no code, and the field stays `str`; the set constrains what the harness *writes*.
Pinned by `test_i1_an_unknown_connector_code_is_replaced_not_persisted`,
`test_i1_a_very_long_connector_code_cannot_be_persisted` and
`test_i1_every_code_the_harness_itself_emits_is_declared` (the control, which caught the
closed set and the message table drifting apart while it was being written).

**The control test's own limit, measured rather than assumed.** That control scans
`tools.py`'s `_error(...)` call sites with an AST. An independent review defeated it three
ways, each by exploiting a *spelling* trust rather than a provenance check: a new local
`code = "some_new_failure"` passed at a real call site, a module-local `_Codes.code`
attribute, and a call through an alias of `self._error`. In all three the control stayed
green while the undeclared code reached `_error` — and in all three the **runtime gate still
replaced it before persistence**, so the guarantee this round added is untouched and none was
blocking. What the bypasses defeat is the drift tripwire, not the boundary, and the test
docstring now says exactly that instead of claiming a provenance check the code does not
perform. Closing them properly means resolving `Name('code')` by its assignment inside the
enclosing function, exempting `Attribute` only when its value side is a bare `Name`, and
resolving aliased calls — recorded here as known follow-up rather than done, because the
tripwire's remaining value did not justify the machinery in the same change.

**An independent review of that fix found a second route, now closed as well.** `extra="forbid"`
makes a connector's invented key the *location* of a `ValidationError`, and `_brief` rendered
that location — so a connector-chosen field name reached a persisted row through the one
message the new boundary does not cover, contradicting the claim that a validation report
never renders a connector-supplied value. It was demonstrated, not theoretical:
`describe_resource result does not match its contract: X-Acme-Session-Zx9Qv2…: Extra inputs
are not permitted`, persisted. The correction is the same shape as the boundary — whitelist
rather than sanitise: a location part is rendered only when the result (or argument) model
declares it, or when it is an integer list index; anything else becomes `<undeclared-field>`.
Pydantic's own `msg` still names the category of problem, so the model loses nothing it can
act on. Pinned by
`test_i1_a_connector_chosen_field_name_cannot_reach_the_persisted_result` and, for the
pre-existing strictness test, `test_an_undeclared_connector_field_is_rejected_not_absorbed`
— whose assertion was **changed** from "the offending field is named" to "the connector's
name is not persisted, the marker and pydantic's message are". That assertion was the bug:
it required the leak.

### Defects fixed

| Was | Now |
| --- | --- |
| A control-store fault in `tool_call` or `propose` escaped `run_routing_job` as a traceback. | Every repository read and write in those nodes maps to a typed `repository_unavailable` failure; `tool_call` also clears its pending batch, so the run ends instead of re-entering the loop. |
| `tool_call_id` is model-authored and was the harness's replay, budget and evidence key. A different tool or different arguments under a reused id was served the earlier payload **for free**. | A recorded result now carries the arguments it ran with. A replay is accepted only when the tool name and the validated arguments match; anything else is a typed `replay_mismatch`. Duplicate ids inside one batch are refused whole. |
| A model that kept re-requesting one id looped until `max_model_calls`; `max_tool_calls` never fired. | `max_tool_calls` bounds tool **rounds** as well as charged reads, and the terminal failure reports the rounds it spent instead of zeroing them. **At the shipped defaults (40 tool calls, 20 model calls) the model budget is still the binding bound**, because every round costs a model call; the round bound is what fires in the configurations the tests use. A terminal `tool_call` failure is sticky: `tool_call -> propose` is an unconditional edge, and `propose` used to clear the failure and re-arm the loop. Replayed refs are no longer duplicated onto the state. |
| A repository fault in the *runner* — the `get_inventory`, `get_catalogue` and `create_job` calls made before the graph starts — escaped as a traceback, because `_run_graph`'s handlers never saw them. | All three are typed `repository_unavailable`. A blip during the first inventory read is the likeliest moment for one, and it now produces a failed job with a reason instead of a traceback. |
| Pre-dispatch refusals were persisted, so a *corrected* call under the same id replayed the old refusal forever. | Refusals made before dispatch are not persisted (`persist=False`), which is what the code's own docstring always claimed. |
| Redaction checked only `str` values and a short key list, so a card number or phone stored as an `int`, an address, and a credential used as a *dict key* all passed through. | Content is checked against the string form of every scalar; contact and identifier patterns cover phone, postal address, SSN, IBAN and card runs; a key that names restricted data takes its whole **subtree** with it, and a key that is itself credential material is replaced. Ordinary values are asserted to survive. The first attempt at this introduced its own leak — a mapping under `credentials` matched the container branch before the name rule — which a later review caught and `test_f1_*` now pins. |
| Free-form pass-through arguments (`path`, `page_token`, `cursor`) were unconstrained text, and a path-shaped token could still carry `..`. | They are pattern-constrained tokens, and a `..` path segment is refused before any connector call. |
| The state guard raised a bare `ValueError`, which escaped `run_routing_job`; `errors.INVALID_STATE_UPDATE` was dead code. | The guard raises `InvalidStateUpdateError` and the runner maps it to a typed `invalid_state_update` failure. The guard earned its place during this work twice: it caught an incomplete edit of ours that wrote `failure` from `tool_call` without declaring it, and an incomplete one that wrote the round counter from `context`. |
| `verify_us4_person_b.py` filtered its scope check on `src/backend/app/agent/`, so the frozen `contracts.py` inside that prefix was invisible by construction. | The script compares the working-tree `contracts.py` against the blob at the freeze commit and fails on any difference, so an uncommitted edit is caught as well as a committed one. It also asserts `CONTRACT_VERSION` is unchanged and that the delta-declaration list it used to carry stays empty. |
| The live adapter sent `output_format`, which the provider's SDK migrated away from in 0.77.0. | It sends `output_config.format`, the documented JSON-outputs surface, and a test pins the payload shape and the absence of the old parameter. |
| **Fixed after a third pass over these fixes.** A replayed result whose ref was already on the state was skipped entirely — correct within one run, wrong across runs, and it also dropped the *payload* once a run held more results than the prompt projects, so the model re-asked and the job died on a budget with the evidence in hand. | The replay is moved to the **end** of the projected window instead of being skipped, so the ref is not duplicated and the payload is visible. `test_g1_*` and `test_h1_*` pin both halves; reverting either way fails them. |
| The batch loop passed a request **index** as the used-call count, so a batch whose first entry was refused before dispatch had its second, valid entry refused as `budget_exhausted` while nothing had reached the connector. | The loop passes the count of *charged* calls, which advances only when a call is charged. `test_h2_*` pins it. |

### The frozen contract was restored, not modified

An earlier revision of this branch made `contracts.py` import `StrEnum` from
`app/agent/compat.py` so the module would load on a Python 3.10 floor. The team decided the
frozen contract is not to be modified, so that import was reverted and the file is now
byte-identical to the `us4/integration` blob. (The working tree differs from the blob only
in line endings: `core.autocrlf=true` checks the file out with CRLF on Windows while the
committed blob is LF. `git diff origin/us4/integration -- contracts.py` is empty.)

`verify_us4_person_b.py` asserts that identity against the **working tree**, so an
uncommitted edit is caught as well as a committed one, and it fails if the
delta-declaration list it used to carry is ever repopulated - declaring a delta is not the
same as the team approving one.

Two consequences recorded rather than glossed:

* `enum.StrEnum` is Python 3.11+, so `contracts.py` now requires 3.11+. The suite runs on
  the venv's Python 3.12 and passes. On 3.10 the failure is an immediate `ImportError` on
  import of `app.agent.contracts`, not silent misbehaviour.
* `app/agent/compat.py` was not deleted: `tests/agent/test_compat.py` imports it directly,
  so it is not unused, and removing another contributor's test was out of scope. Nothing in
  the agent package depends on it any more.

### What this cycle did NOT establish

The fixes above are covered by the test suite and by the requirement script. They are
**not** corroborated by a mutation-battery run (see above) and none of it is evidence about
a real provider: `anthropic` is now declared in `requirements.txt` and is **not
installed**, no credential and no endpoint are configured, and
`tools/live_provider_check.py` has still never run. The wire format is justified by the
provider's documentation, not by an accepted response.

## What is still not verified

1. **A real model provider.** `tools/live_provider_check.py` is written and refuses to
   run without a key, but it has never been executed: this environment has no API key and
   no `anthropic` SDK installed. That is an explicit blocker, not a pass. It validates the
   one assumption a stub cannot - that the wire format (`output_config.format` JSON
   schema, bound tools with `tool_choice: auto`) is accepted, and that the answered draft
   validates against `ModelDraft`. It also accepts an Anthropic-compatible gateway:

   ```powershell
   pip install anthropic
   $env:GENLEDGE_LLM_API_KEY  = "..."
   $env:GENLEDGE_LLM_BASE_URL = "https://your-gateway.example/v1"
   $env:GENLEDGE_LLM_MODEL    = "glm-5.3"
   python tools/live_provider_check.py
   ```

   A gateway is **not** Anthropic: a success there shows the adapter works against that
   endpoint's request format and says nothing about Anthropic's own wire behaviour. Both
   facts have to be reported separately.

2. **Checkpoint resume.** Needs Person A's persistence plus a saver. Until then the
   harness gate's "resume from a checkpoint" half is unmet.
3. **A real connector.** `FakeConnector` is the only implementation of the tool seam.
   The fault matrix pins the harness's side of the contract; Person A's adapter is the
   first real test of the other side.
4. **Concurrency.** Two runners on one job, a cancel racing a resume, and edit
   idempotency are Person D's and the persistence layer's concerns.
5. **Load and cost.** No measurement of tokens, latency or checkpoint growth, so
   `max_cost_usd` and `recursion_limit` remain derived from the plan's arithmetic rather
   than from observation.
6. **The `effort` parameter.** `GENLEDGE_LLM_EFFORT` is read and stored but never sent;
   the provider documents effort as a request control whose home has moved between top
   level and `output_config`. Sending it is a behaviour change that cannot be validated
   here, so it stays unsent and this line stays on the list.
7. **The fallback graph runtime, in this cycle.** The suite was run with `langgraph`
   installed, so `graph_runtime()` reported `langgraph`; the
   `GENLEDGE_GRAPH_RUNTIME=local-fallback` pass was not repeated after the fifth-cycle
   changes. Both engines share the same node functions and the same `guarded` wrapper, and
   nothing in this cycle touches the runtime seam (`app/agent/graphs.py` and
   `app/agent/graph.py` are unmodified), but that is an argument, not an observation.
8. **The tool-call deadline's residual thread.** `run_with_deadline` bounds the *caller*
   by waiting on a daemon worker. A connector that never returns leaves that worker alive;
   Python cannot preempt a thread. The run proceeds on a typed `connector_timeout` and the
   budget bounds how often that can happen, but the thread is a real, documented cost.
9. **The model-node deadline is not preemption.** A synchronous SDK call cannot be
   interrupted in-process, so `model_node_timeout_seconds` is enforced as a deadline on
   what the node will *accept*: an over-budget answer is recorded, refused and reported as
   `model_unavailable`. The hard per-attempt bound is the provider client's own request
   timeout (`GENLEDGE_LLM_TIMEOUT_SECONDS`, 300 s by default, derived to a 960 s attempt
   bound per `plans/LANGGRAPH_HARNESS_PLAN.md` §6.5). Do not read the node budget as a
   guarantee that a hung provider call is abandoned.
10. **Message redaction is a scalar rule, not a parser — and it is no longer the
    guarantee for connector text.** `redact_message` remains a blocklist, and a credential
    shape nobody has enumerated (an opaque session cookie, a bespoke header) would still
    pass through it. That is now acceptable **only** because no connector exception text is
    persisted at all: `_error` builds the row's message from the typed code through the
    closed lookup `tools.connector_error_message()`, and the exception's own text goes to
    `logger.debug` on `app.agent.tools`. This item previously read as a residual gap in the
    connector guarantee; the targeted security follow-up below closed it. What remains a
    documented limit is narrower: the `storage_failed` path still persists harness-authored
    prose *around* a control-store exception, and that path relies on the blocklist — a
    control-store driver that quotes an unenumerated credential shape in the message the
    harness frames would reach the row. It is not the connector path, it is defence in
    depth rather than a guarantee, and it is pinned by
    `test_i1_an_unfamiliar_credential_from_the_store_is_also_kept_out`.

## One deliberate friction point, recorded

Per-tool result models are `extra="forbid"`, so a connector that returns a field the
harness never declared gets a typed `connector_error` instead of being absorbed
(`test_an_undeclared_connector_field_is_rejected_not_absorbed`). That is the right
default - undeclared data would otherwise reach the review screen unvalidated - but it
means **adding a field to a connector requires adding it to its result model first**.
Person A should know that before wiring a real adapter.
