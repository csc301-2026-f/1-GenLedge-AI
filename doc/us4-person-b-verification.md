# How this slice is verified — and what each technique actually catches

Every serious defect found in the US4 Person B work was found by a technique
*other* than a passing test. This file records which technique caught what, so the
next person can pick the right tool instead of writing more unit tests.

## Techniques applied, and what each one caught

| # | Technique | Command | What it caught that tests could not |
| --- | --- | --- | --- |
| 1 | **Adversarial review by a second model** | a GLM 5.3 review of the committed diff | The blocker: source data containing `{{...}}` crashed `render()` out of the graph, and a value naming a declared placeholder spliced another prompt block into itself. Both reachable from ordinary source text. |
| 2 | **Run against the real dependency** | `python -m pytest` with `langgraph` installed | LangGraph injects a parameter *named* `runtime` as a keyword, and only if it is visible in the signature. The write-guard's `*args, **kwargs` hid it, so **every node ran with no runtime**. A hand-written stand-in can never validate the convention of the library it replaces. |
| 3 | **Observe the running process** | `python -c "import main"` | The startup banner logged at INFO into a root logger with no handler, so the resolved model mode silently vanished — the requirement was unmet while every test passed. |
| 4 | **Strict type check against real stubs** | `mypy` with the venv on `--python-executable` | Fixture helpers declared `type: str` where the contracts require `SourceType`; the runtime `mode="before"` validators had been masking the mismatch. Also a `**{...}` unpack whose types mypy widens and rejects. |
| 5 | **Run the documented command, not a proxy** | `python -m pytest tests` | There was no `pytest.ini`, so this collected nothing from the repo root. A shim that "worked" hid a build-configuration defect. It then caught a second one: `GENLEDGE_GRAPH_RUNTIME=local-fallback` � which both docs advertised � failed 2 tests, because the `get_graph()` cases skipped on library *availability* rather than on the engine actually selected. |
| 6 | **Fault-injection matrix** | `test_fault_injection.py` | A failed tool call was **not charged** against `max_tool_calls`, so a source that fails every read made the loop bound free — the graph's only defence against a runaway model stopped applying exactly when it mattered. Also: a connector growing an undeclared field was silently absorbed rather than rejected, because per-tool result models did not exist. |
| 7 | **Per-field sentinel fuzz** | `test_prompt_boundary_fuzz.py` | The resource **name** was loaded and never projected, so the model saw only opaque ids (`resource_0`) while AC6 asks it to reason over names. Per-field poisoning is what a fixed blocklist cannot do. |
| 8 | **Property-based tests with a seeded generator** | `test_properties.py` (250 cases) | Source text containing `</untrusted_source_data>` **closed the block early**, leaving the rest of the sample in the instruction region of the prompt — the sharpest form of the injection risk the boundary exists to bound. Fixed by neutralising delimiter tokens in every source-derived string. |
| 9 | **Architecture enforcement by AST scan** | `test_architecture_rules.py` | `graph.py` imported `langgraph.errors` directly, so the "one seam for the optional dependency" claim was false; `graph_runtime()` could have disagreed with what actually ran. |
| 10 | **Differential test across implementations** | `test_both_runtimes_produce_the_same_run` | The two graph engines were never compared on equal terms: the fallback only ran where LangGraph was absent. Both now run in one session and their states are compared field by field. |
| 11 | **Mutation check** | `python tools/mutation_check.py` | The three-sample projection cap had no test that could fail — the contract's `max_length=3` made it unreachable. `test_the_projection_caps_samples_even_for_an_out_of_contract_inventory` constructs an out-of-contract inventory and kills that mutation. The battery now stands at **14 mutations, all killed** � it found that the text cap, the recursion derivation, the field-path control, the `auto`-mode gate and four delimiter sites were each unpinned. |
| 12 | **A second, fresh adversarial review** | a GLM 5.3 review of the whole slice, with an independent 16-mutation battery | **The delimiter fix was incomplete.** `snapshot_id`, `resource_id`, the field path, the tool name, `tool_call_id` and `previous_response` were all still rendered raw, so six forgery routes remained � and the tests were complicit, because the fuzz list poisoned only the two fields that *were* neutralised. Also: redaction missed `mysql://` and `mongodb+srv://` DSNs and emails embedded in a sentence (its own docstring claimed otherwise); a lines-only inventory raised `IndexError` out of `run_routing_job`; and `auto` mode treated a provider *name* as configuration, so one harmless variable failed every job. |
| 13 | **Requirement-level script, independent of the suite** | `python verify_us4_person_b.py` | Says whether the *task's requirements* hold through the public entrypoints, so a suite and an implementation wrong in the same way still fail. It also prints, by name, what it cannot check. |

**The pattern worth noticing:** items 6–9 each found a *real defect* on their first run, and all four
were in code that already had passing tests. None of them was found by adding another example-based
test.

## The standing commands

```powershell
# .venv at the repository root
python -m pytest                 # 458 passed
python -m pytest tests           # same suite, from src/backend
python verify_us4_person_b.py    # 17/17 requirement-level checks
python tools/mutation_check.py   # 14/14 mutations killed
python run_agent_tests.py        # fallback path, on a machine without pytest
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

## What is still not verified

1. **A real model provider.** `tools/live_provider_check.py` is written and refuses to
   run without a key, but it has never been executed: this environment has no API key
   and no `anthropic` SDK installed. Run it to validate the one assumption a stub
   cannot — that the wire format (`output_format` JSON schema, `tool_choice: auto`)
   is accepted. It also accepts an Anthropic-compatible gateway:

   ```powershell
   pip install anthropic
   $env:GENLEDGE_LLM_API_KEY  = "..."
   $env:GENLEDGE_LLM_BASE_URL = "https://your-gateway.example/v1"
   $env:GENLEDGE_LLM_MODEL    = "glm-5.3"
   python tools/live_provider_check.py
   ```

2. **Checkpoint resume.** Needs Person A's persistence plus a saver. Until then the
   harness gate's "resume from a checkpoint" half is unmet.
3. **A real connector.** `FakeConnector` is the only implementation of the tool seam.
   The fault matrix pins the harness's side of the contract; Person A's adapter is the
   first real test of the other side.
4. **Concurrency.** Two runners on one job, a cancel racing a resume, and edit
   idempotency are Person D's and the persistence layer's concerns.
5. **Load and cost.** No measurement of tokens, latency or checkpoint growth, so
   `max_cost_usd` and `recursion_limit` remain derived from the plan's arithmetic
   rather than from observation.

## One deliberate friction point, recorded

Per-tool result models are `extra="forbid"`, so a connector that returns a field the
harness never declared gets a typed `connector_error` instead of being absorbed
(`test_an_undeclared_connector_field_is_rejected_not_absorbed`). That is the right
default — undeclared data would otherwise reach the review screen unvalidated — but it
means **adding a field to a connector requires adding it to its result model first**.
Person A should know that before wiring a real adapter.
