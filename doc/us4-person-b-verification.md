# How this slice is verified — and what each technique actually catches

Every serious defect found in the US4 Person B work was found by a technique
*other* than a passing test. This file records which technique caught what, so the
next person can pick the right tool instead of writing more unit tests.

## The techniques, ranked by what they actually caught

| # | Technique | Command | What it caught that tests could not |
| --- | --- | --- | --- |
| 1 | **Adversarial review by a second model** | a GLM 5.3 review of the committed diff | The blocker: source data containing `{{...}}` crashed `render()` out of the graph, and a value naming a declared placeholder spliced another prompt block into itself. Both were reachable from ordinary source text. |
| 2 | **Run against the real dependency** | `python -m pytest` with `langgraph` installed | LangGraph injects a parameter *named* `runtime` as a keyword, and only if it is visible in the signature. The write-guard's `*args, **kwargs` hid it, so **every node ran with no runtime**. A hand-written stand-in can never validate the convention of the library it replaces. |
| 3 | **Observe the running process** | `python -c "import main"` | The startup banner logged at INFO into a root logger with no handler, so the resolved model mode silently vanished — the requirement was unmet while every test passed. |
| 4 | **Strict type check against real stubs** | `mypy` with the venv on `--python-executable` | Fixture helpers declared `type: str` where the contracts require `SourceType`; the runtime `mode="before"` validators had been masking the mismatch. Also a `**{...}` unpack whose types mypy widens and rejects. |
| 5 | **Run the documented command, not a proxy** | `python -m pytest tests` | There was no `pytest.ini`, so this collected nothing from the repo root. A shim that "worked" hid a build-configuration defect. |
| 6 | **Differential test across implementations** | `test_both_runtimes_produce_the_same_run` | The two graph engines were never compared on equal terms: the fallback only ran where LangGraph was absent. Now both run in one session and their states are compared field by field. |
| 7 | **Mutation check** | `python tools/mutation_check.py` | The three-sample projection cap had no test that could fail — the contract's `max_length=3` made it unreachable. `test_the_projection_caps_samples_even_for_an_out_of_contract_inventory` now constructs an out-of-contract inventory and kills that mutation. |
| 8 | **Requirement-level script, independent of the suite** | `python verify_us4_person_b.py` | Says whether the *task's requirements* hold through the public entrypoints, so a suite and an implementation that are wrong in the same way still fail. It also prints, by name, what it cannot check. |

## The standing commands

```powershell
# .venv at the repository root
python -m pytest                 # 141 passed
python -m pytest tests           # same suite, from src/backend
python verify_us4_person_b.py    # 17/17 requirement-level checks
python tools/mutation_check.py   # 4/4 mutations killed
python run_agent_tests.py        # fallback path, on a machine without pytest
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

1. **A real model provider.** The live adapter is asserted against an SDK stub.
   Whether the installed `anthropic` SDK accepts the exact wire format
   (`output_format` JSON schema, `tool_choice: auto`) is untested. To close it:
   `pip install anthropic`, set `ANTHROPIC_API_KEY`, then
   `GENLEDGE_MODEL_MODE=live python -c "..."` running one job and asserting the
   draft validates and the token accounting is non-zero.
2. **Checkpoint resume.** Needs Person A's persistence plus a saver. Until then the
   harness gate's "resume from a checkpoint" half is unmet.
3. **A real connector.** `FakeConnector` is the only implementation of the tool
   seam, so the contract is asserted against a shape I wrote. Person A's adapter is
   the first real test of it.
4. **Concurrency.** Two runners on one job, a cancel racing a resume, and edit
   idempotency are Person D's and the persistence layer's concerns; nothing here
   exercises them.
5. **Load and cost.** No measurement of tokens, latency or checkpoint growth, so
   `max_cost_usd` and `recursion_limit` remain derived from the plan's arithmetic
   rather than from observation.

## Techniques not yet applied, and what they would buy

- **Property-based testing.** The projection and the router are pure functions with
  clear invariants ("never more than three samples", "never a key outside the write
  set", "the router never reads model text"). Generating arbitrary inputs would
  cover shapes nobody thought to write by hand. Not installed here; a seeded
  generator would be enough.
- **Fault-injection matrix.** One connector fault is covered. A matrix over
  {non-dict return, wrong shape, oversize, raise, timeout at each step} asserting a
  typed result and no budget leak would pin the whole taxonomy.
- **Boundary sentinel fuzz.** The sentinel test uses fixed constants. Placing a
  sentinel in *every* field of `InventoryView`, `CatalogueView` and `ToolResult` —
  including `description`, `native_type`, `status`, resource `name`, catalogue
  `table_id` — and asserting none survives would close per-field gaps like the
  `native_type` one the review found by reading.
- **Architecture enforcement.** The plan forbids `runs` importing `app.agent`.
  A one-line import scan would make that structural rather than aspirational.
