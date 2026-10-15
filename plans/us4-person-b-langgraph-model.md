# US4 Person B — LangGraph and Model Adapter (ExecPlan)

**Status: complete.** The finalized plan and handoff live in
[`doc/us4-person-b-langgraph-model.md`](../doc/us4-person-b-langgraph-model.md).

## Goal

Implement the US4 slice owned by Person B on branch `us4/person-b-langgraph-model`
(base `us4/integration`): the three-node routing graph, tool dispatch, budgets,
prompt projection, and the fake/live model adapters, with focused tests.

Authoritative references:

- `plans/us4-four-person-task-split.md` §"Person B"
- `plans/user-stories/US4.md` §4 (graph), §5 (contracts, prompt boundary), §8 (tests)
- `plans/LANGGRAPH_HARNESS_PLAN.md` §5–§9
- `doc/agent-harness-architecture.md` (harness gate, line 238)
- `src/backend/app/agent/contracts.py` (frozen contracts — imported, never redefined)

## Scope

Owned: `RoutingJobState`, the `context`/`propose`/`tool_call` nodes, tool dispatch,
agent budgets, prompt projection, the fake/live adapters, and model-mode
resolution.

Not implemented, deliberately: database schema, Flask routes, React components,
deterministic validation rules (`app/mappings/validation.py` is Person C), duplicate
contract definitions.

## Graph

```text
START -> context -> (propose | END)
propose -> (tool_call | END)
tool_call -> propose
```

## Task list

- [x] `plans/us4-person-b-langgraph-model.md` — this ExecPlan
- [x] `app/agent/state.py` — `RoutingJobState`, `replace_messages`, budget helpers
- [x] `app/agent/errors.py` — typed failure codes and `AgentFailure`
- [x] `app/agent/graphs.py` — LangGraph import seam with a labelled fallback runner
- [x] `app/agent/repositories.py` — repository protocol, in-memory doubles, seeded fixture
- [x] `app/agent/tools.py` — tool catalog, argument models, the dispatch contract
- [x] `app/agent/prompts.py` + `prompts/*.md` + `manifest.json` — versioned prompts, projection allow-list
- [x] `app/agent/models.py` — `FakeModel`, `LiveModel`, `resolve_model_mode`
- [x] `app/agent/nodes.py` — the three nodes and the routers
- [x] `app/agent/graph.py` — `build_graph`, `run_routing_job`, startup banner
- [x] `app/agent/compat.py` — `StrEnum` on Python 3.10
- [x] `requirements.txt` — `langgraph>=1.2,<2`
- [x] `app/__init__.py` — `create_app` emits the resolved model mode at start-up
- [x] Tests under `tests/agent/`
- [x] GLM 5.3 review findings fixed, each with a regression test
- [x] Plan finalized into `doc/us4-person-b-langgraph-model.md`
- [x] Third-review remediation: restored the prompt cap a killed mutation run had left
      disabled; rewrote `tools/mutation_check.py` to work on a throwaway copy with a
      baseline run and verified restores; typed storage failures; harness-checked replay
      identity; tool-round budgeting; replay reference deduplication; the full redaction
      category set; typed `invalid_state_update`; the frozen-contract check in
      `verify_us4_person_b.py`; `output_config.format` for the live adapter;
      `anthropic` declared in `requirements.txt`
- [ ] **Blocked:** a real provider call (`anthropic` not installed, no credential)
- [x] **`contracts.py` restored to `us4/integration`.** The frozen contract is not modified
      by this branch: the `StrEnum` import swap was reverted and `verify_us4_person_b.py`
      asserts byte-identity against the frozen blob. See
      `doc/us4-person-b-langgraph-model.md` §7.6 for the Python-version consequence.
- [ ] **Blocked:** the mutation battery has no verified run in this environment (the
      sandbox denies every copy destination); it refuses cleanly rather than mutating the
      repository
- [ ] **Not started:** checkpoint resume, which needs Person A's persistence

## Verification

```text
cd src/backend
..\..\.venv\Scripts\python.exe -m pytest tests -o addopts=""
```

The venv interpreter is not optional: `python` on `PATH` has neither pytest nor
pydantic. `-o addopts=""` overrides `pytest.ini`'s `addopts = -q`, which otherwise
suppresses the summary line and hides the test count.

Pass criteria and their outcomes:

| Criterion | Outcome |
| --- | --- |
| exactly three graph nodes and the declared edges | met on the langgraph engine by introspection of the compiled graph; the declared-shape cases are tautological and nothing asserts the built node set on the fallback engine |
| the fake model completes a real tool loop and returns a valid `ModelDraft` | met (`test_fake_model_tool_loop.py`) |
| tool and model budget exhaustion each produce a typed failure | met, plus token, wall-clock and cost (`test_budget_exhaustion.py`); `max_tool_calls` now bounds tool *rounds*, so a replayed call cannot make the loop free |
| invalid output → one repair attempt → `invalid_model_output` | met (`test_repair_path.py`) |
| duplicate `(job_id, tool_call_id)` replays without a second connector call | met, and now checked for integrity: a replay under a reused id with a different tool or different arguments is refused (`replay_mismatch`) |
| fake/live adapter compatibility | met against an SDK stub (`test_adapters_and_modes.py`) — the stub accepts any keyword, so it cannot validate a parameter *name* |
| restricted values never reach a prompt | met for the named categories (`test_prompt_safety.py`, and one sentinel per category in `test_remediation_regressions.py`) |

### Verification results recorded

**Numbers below were produced by earlier cycles and are kept only as a record. Re-run
the commands; do not cite the counts.** Two of them were wrong at the time they were
written: the "458 passed" run was green on a *pristine copy* while the delivered working
tree was red, and "14/14 mutations killed" was produced by a battery that mutated the
real checkout and could not distinguish a kill from a collection error.

```text
..\..\.venv\Scripts\python.exe -m pytest tests -o addopts=""   # prints the count
python verify_us4_person_b.py     # requirement-level checks, independent of the suite
python tools/mutation_check.py    # mutation battery, on a throwaway copy
python run_agent_tests.py         # the agent suite on a machine without pytest
```

- The suite exercises the **real `langgraph.StateGraph`** when the package is
  installed, including `get_graph()` introspection and an assertion that the
  framework's injected runtime actually reaches the nodes. The labelled fallback is
  selected with `GENLEDGE_GRAPH_RUNTIME=local-fallback`.
- A third review, of the *working tree* rather than the commits, found the delivery
  broken: `tools/mutation_check.py` mutated the real checkout and was killed before its
  restore, leaving a disabled prompt cap in `prompts.py`. That tool has been rewritten to
  work on a throwaway copy with a baseline run and verified restores, and the defects
  found in the same cycle (typed storage failures, replay identity, tool-round budgeting,
  redaction categories, typed `invalid_state_update`, the frozen-contract check, and the
  live adapter's `output_config.format`) are fixed with regression tests.
- `verify_us4_person_b.py` asserts the requirements from the outside through the
  public entrypoints, compares the frozen `contracts.py` against the blob at the freeze
  commit, and names at the end what it cannot verify.

**Defect the real-library run caught:** LangGraph injects a parameter *named*
`runtime` as a keyword, and only when it is visible in the callable's signature. The
node-write guard wrapped each node in `*args, **kwargs`, hiding it — so every node ran
with no runtime. Fixed in `guarded`/`runtime_for`.

**Still not established:** a real provider call. `anthropic` is declared in
`requirements.txt`, but it is not installed here, no credential or endpoint is
configured, and `tools/live_provider_check.py` has never run. The live wire format is
justified by the provider's documentation, not by an accepted response.

Full detail, environment variables, and the remaining provider and persistence
limitations are in [`doc/us4-person-b-langgraph-model.md`](../doc/us4-person-b-langgraph-model.md);
the remediation record and the list of what remains unverified are in
[`doc/us4-person-b-verification.md`](../doc/us4-person-b-verification.md).
