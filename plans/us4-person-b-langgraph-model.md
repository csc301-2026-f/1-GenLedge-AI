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

## Verification

```text
cd src/backend
python -m pytest tests
```

Pass criteria and their outcomes:

| Criterion | Outcome |
| --- | --- |
| exactly three graph nodes and the declared edges | met (`test_graph_shape.py`); the two compiled-LangGraph introspection cases skip without the package |
| the fake model completes a real tool loop and returns a valid `ModelDraft` | met (`test_fake_model_tool_loop.py`) |
| tool and model budget exhaustion each produce a typed failure | met, plus token, wall-clock and cost (`test_budget_exhaustion.py`) |
| invalid output → one repair attempt → `invalid_model_output` | met (`test_repair_path.py`) |
| duplicate `(job_id, tool_call_id)` replays without a second connector call | met (`test_duplicate_tool_replay.py`) |
| fake/live adapter compatibility | met against an SDK stub (`test_adapters_and_modes.py`) |
| restricted values never reach a prompt | met (`test_prompt_safety.py`) |

### Verification results recorded

- **`python -m pytest tests` could not be run to completion on this machine.** There
  is no network access, and neither the Python 3.13 interpreter nor any reachable
  image has `pydantic`, `flask` or `langgraph`. Every suite in the repository fails
  at collection for that pre-existing reason, not because of this change.
- The 104 `tests/agent` cases were **executed unmodified** through a temporary
  pytest-compatible harness against Python 3.10 + pydantic 2.11.9:
  `passed=104 failed=0 skipped=2` (the two skips are the LangGraph-introspection
  cases). The harness was a local verification aid and was removed before the
  commit.
- `python -m mypy --check-untyped-defs app/agent tests/agent` — clean.

A GLM 5.3 review of the first commit found one blocker (source data containing
`{{...}}` could escape the renderer) and several majors; all are fixed and each has a
regression test. The full list of what was fixed, and the limitations that remain,
is in [`doc/us4-person-b-langgraph-model.md`](../doc/us4-person-b-langgraph-model.md).

Full detail, environment variables, and the remaining provider and persistence
limitations are in [`doc/us4-person-b-langgraph-model.md`](../doc/us4-person-b-langgraph-model.md).
