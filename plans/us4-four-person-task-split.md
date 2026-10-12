# US4 Four-Person Task Split

## Goal

Implement the D2 US4 slice on `us4-sample-impl`:

```text
seeded source snapshot
-> bounded inventory
-> LangGraph routing proposal
-> deterministic projection and validation
-> persisted review package
-> frontend routing review
```

Authoritative references:

- `plans/user-stories/US4.md`: US4 acceptance criteria and the three-node graph.
- `plans/LANGGRAPH_HARNESS_PLAN.md`: shared contracts, budgets, state, failures, and D2 gates.
- `doc/agent-harness-architecture.md`: source-agnostic harness and proposal lifecycle.
- `doc/backend-architecture.md`: Flask modules, worker boundary, PostgreSQL control plane, and API conventions.

US4 ends when a reviewable routing package is published. US5 owns approval and human revision; US6 owns transformation and warehouse execution.

## Shared Decisions

### Scope and graph

- D2 uses a deterministic synthetic fixture; real connectors remain behind interfaces.
- The graph is exactly `context -> propose <-> tool_call -> END`.
- Validation, projection, persistence, job status, and frontend rendering remain deterministic application code outside the graph.

### Runtime modes

Use `GENLEDGE_MODEL_MODE=auto|live|fake`:

- `auto` uses a live provider only when provider configuration exists; otherwise it uses the deterministic fake model.
- `live` requires provider configuration and returns a typed configuration error when missing.
- `fake` always uses the fake model.
- Never commit keys or `.env` files.
- Startup output shows `fake` or the live provider/model without secrets.
- The fake model must execute through LangGraph and perform one tool call.

### Shared contracts

Use contract version `1`, strict Pydantic models, rejected unknown fields, and application-owned revisions/IDs.

```python
class FieldRef:
    source_id: str
    resource_id: str
    field_path: str

class InventoryField:
    ref: FieldRef
    type: Literal["text", "number", "boolean", "date", "timestamp", "json"]
    nullable: bool
    repeating: bool
    samples: list[str]       # maximum 3
    description: str | None
    ambiguity: str | None
    status: Literal["stable", "new", "unknown"]
    native_type: str | None

class InventoryView:
    snapshot_id: str
    resources: list[ResourceSummary]
    fields: list[InventoryField]
```

The fixture must contain `orders`, `orders.lines[]`, `customers`, an ambiguous `orders.order_date`, nullable/repeating metadata, and no full rows in the prompt projection.

`ModelDraft` follows the master plan: revision, tables, kind, grain, non-empty keys, attributes, relationships, evidence, confidence, rationale, source coverage, and unresolved items. The application computes `is_new` from `catalog_ref`; the model does not author it.

`MappingDraft` is produced after the graph:

```python
class Mapping:
    target: Identifier
    sources: list[Identifier]
    operations: list[TransformOp]
    join_path: list[str]
    confidence: float
    rationale: str | None

class MappingDraft:
    revision: int
    based_on_model_revision: int
    mappings: list[Mapping]
    unmapped_targets: list[Identifier]
    unresolved: list[str]
```

Only the closed transformation vocabulary from `plans/user-stories/US6.md` is allowed. No free-form SQL, Python, or arbitrary expressions may be model output.

Findings use `code`, `severity`, `target`, `message`, and `evidence`. Required codes are:

```text
invalid_source_reference, invalid_target_reference, invalid_merge_key,
missing_evidence, unmapped_source_field, unmapped_target_field,
ambiguous_date, unsupported_operation, stale_mapping_revision,
partial_table_failure
```

Use the shared statuses: `queued`, `running`, `awaiting_review`, `edit_requested`, `blocked`, `failed`, and `cancelled`.

### API

Implement:

```text
POST /api/mappings/jobs
GET  /api/mappings/jobs/{job_id}
GET  /api/mappings/jobs/{job_id}/package
PUT  /api/mappings/jobs/{job_id}/edits
```

Job creation requires `Idempotency-Key`, returns `202 {job_id, status}`, and never executes the graph in the request thread. Errors use:

```json
{"error": {"code": "invalid_model_output", "message": "...", "details": {}}}
```

## Person A: Source Inventory and Persistence

Own the PostgreSQL control schema, migrations, seeded snapshot, inventory service, repository functions, and database tests.

Tasks:

- Create tables for snapshots, resources, fields, catalogues, jobs, revisions, findings, coverage, tool results, and edits.
- Seed `orders`, `orders.lines[]`, `customers`, bounded samples, source-native types, and ambiguous `order_date`.
- Implement `get_inventory(snapshot_id) -> InventoryView`.
- Enforce stable references, three-sample limits, snapshot immutability, and no raw rows or credentials in inventory.
- Implement job/revision/findings/coverage persistence, idempotency lookup, tool replay, and edit persistence.
- Provide fixture and repository adapters to Persons B and D.

Tests:

- Inventory validation and sample limits.
- Snapshot immutability.
- Job/revision persistence across restart.
- Duplicate job and tool-call replay.
- Findings and coverage persistence.

Done when a seeded snapshot round-trips through persistence into a valid `InventoryView` and another process can read it.

## Person B: LangGraph and Model Adapter

Own `app/agent`, graph state, `context`, `propose`, `tool_call`, tool dispatch, adapters, prompt projection, and budgets.

Tasks:

- Implement `RoutingJobState` with job/snapshot/catalogue references, pending calls, tool-result references, draft, counters, budgets, failure, status, and model mode.
- Implement `context` with snapshot loading, inventory projection, optional catalogue loading, and empty-inventory failure.
- Implement `propose` with one structured call, strict validation, one repair attempt, typed tool requests, and application-owned revisions.
- Implement `tool_call` with argument validation, source/job scope, budgets, replay by `(job_id, tool_call_id)`, redaction, persistence, and typed errors.
- Use the canonical `sample_rows` or `profile_resource` tool for the fake `orders.lines[]` call.
- Implement `resolve_model_mode()` and a shared live/fake `ModelClient` interface.
- Make the fake model request one tool call, then return a valid `ModelDraft`.
- Add prompt sentinel tests for credentials, DSNs, organization IDs, client names, raw rows, mappings, and reviewer identity.
- Print the resolved mode at startup without secrets.

Tests:

- Exactly three graph nodes.
- Tool and model budget exhaustion.
- Invalid output and one repair attempt.
- Tool replay without a second connector call.
- Fake/live adapter compatibility.
- Prompt boundary sentinel coverage.

Done when the fake model completes a real LangGraph tool loop and returns a schema-valid `ModelDraft` without restricted context exposure.

## Person C: Contracts, Projection, and Validation

Own shared Pydantic contracts, `mappings/validation.py`, model-to-mapping projection, findings, coverage, redaction, and negative tests. Review TypeScript response shapes with Person D.

Tasks:

- Implement the master-plan contracts without duplicate definitions in other packages.
- Implement `ModelDraft + InventoryView + catalogue -> MappingDraft + is_new + coverage`.
- Validate source/target references, merge keys, evidence, confidence, operations, ambiguity, coverage, stale revisions, and partial table failures.
- Return findings as data; invalid proposals must not raise.
- Define redaction for email, phone, address, identifiers, credential-like values, and unknown sensitive fields.
- Publish valid and invalid JSON examples for Persons B and D.

Tests:

- Unknown fields, type coercion, invalid confidence, empty evidence/rationale, invented operations, and invalid enums.
- Every required finding code.
- Ambiguous-date blocking.
- Multiple target tables from one source collection.
- Partial table preservation.
- Projection never includes raw rows or credentials.

Done when every package imports the same contract types and invalid proposals produce stable blocker codes.

## Person D: API, Job Service, Frontend, and Integration

Own mapping routes, job lifecycle service, API response models, frontend client, `DiscoverScreen.tsx`, `RouteScreen.tsx`, and end-to-end integration. Person D does not own database schema, graph internals, or validation rules.

Tasks:

- Implement idempotent job creation and source-snapshot validation.
- Run the graph asynchronously, persist the draft, project and validate it, persist the review package, and set `awaiting_review`, `blocked`, or `failed`.
- Implement status, package, and table-decision endpoints.
- Persist `accept`/`reject` decisions by idempotent `edit_id` while preserving unrelated tables.
- Replace routing fixtures with live job/package data.
- Render confidence, rationale, merge key, `is_new`, findings, coverage, loading, blocked, failed, and retry states.
- Display fake/live model mode and reuse the existing frontend client conventions.

Tests:

- Job creation returns `202`.
- Repeated idempotency keys return the original job.
- Status/package survive refresh.
- Invalid references render blockers.
- Decisions persist and repeated edits replay safely.
- Frontend build has no TypeScript errors.
- Static `ROUTE_DATA` is removed from the live path.

Done when a user can start routing, inspect a persisted package, reject one table, refresh, and see the same decision.

## Integration Gates

### Gate 0: Contract freeze

All four people approve the inventory, drafts, findings, coverage, statuses, API envelope, model modes, fake-model behavior, PostgreSQL configuration, and ownership boundaries. Later contract changes require team review and a version update when the shape changes.

### Gate 1: Package boundaries

Each person provides public entrypoints, typed examples, unit tests, contract tests, and supported/unsupported behavior notes. Use fake boundaries: A=fake repository, B=fake inventory/tools/model, C=handwritten drafts, D=fake agent/validator.

### Gate 2: Persistence

Merge A first and prove:

```text
snapshot ID -> persisted inventory -> valid InventoryView
```

### Gate 3: Graph and validation

Merge B and C and prove:

```text
InventoryView -> context -> tool call -> replay/checkpoint -> ModelDraft -> MappingDraft -> findings
```

### Gate 4: API and frontend

Merge D after service entrypoints stabilize and prove:

```text
POST job -> 202 -> async execution -> GET status -> GET package -> live routing screen
```

### Gate 5: End-to-end rehearsal

Sign in, open Schema Discovery, start routing, observe queued/running, inspect proposals and ambiguity, reject one table, refresh, replay the same decision, and confirm the displayed model mode.

## Verification and Documentation

Run from `src/backend`:

```text
python -m pytest tests
```

Run from `src/frontend`:

```text
pnpm build
```

Run the manual flow with `./src/start-app.sh` or `src\start-app.bat`. Update `docs/smoke-tests.md` with Action/Expected entries and update the root README with US4 behavior, PostgreSQL configuration, model modes, commands, and D2 limitations.

## Acceptance Mapping

- AC1: D creates the routing job.
- AC2: A and B provide inventory, catalogue projection, and model input.
- AC3: B/C implement cold-start/new-table behavior; reuse is P1 with a second catalogue fixture.
- AC4: C validates multiple targets from one source collection.
- AC5: B/C enforce columns and real merge keys.
- AC6: A/B preserve names, types, descriptions, samples, and repeating structure.
- AC7: B/C/D produce and display confidence and rationale.
- AC8: C validates references.
- AC9: C/D produce and display findings and coverage.
- AC10: US6 owns populated-table protection; D2 reports this limitation.
- AC11: C/D preserve valid tables and persist idempotent decisions.

## Assumptions

- Target is D2 US4, not the full connector-backed production harness.
- PostgreSQL is the control-plane target; test doubles are allowed in unit tests.
- `GENLEDGE_MODEL_MODE=auto` is the default.
- The fake model uses the real LangGraph path.
- US4 publishes a reviewable package; US5 owns approval; US6 owns loading.
- Real connectors, drift, semantic critique, the full revision loop, and production worker recovery are outside this D2 split.
