# Agent Harness Architecture

## Purpose and starting point

The GenLedge harness turns connected operational data into a **proposed warehouse schema and the mappings that populate it**. The warehouse starts with no predefined analytical tables, columns, or catalogue. The agent must infer a reusable model from source evidence without receiving a particular reporting question. A human reviews the schema and mappings together, can edit either, and approves one version before any warehouse schema is created or data is loaded.

The goal is broad analytical usefulness, not a guarantee that an unknown future question can be answered. Keep the original source data accessible in a raw/landing layer, retain useful source detail and relationships in the proposed model, and explicitly report data that is not represented. Do not aggregate away transaction-level detail merely to make an attractive initial schema.

This document defines the proposed harness, not current application behavior. Today's frontend uses fixtures and simulated runs; the backend is a scaffold. The earlier [backend architecture](backend-architecture.md) and D1 plan assume that a target catalogue exists before mapping. For this harness, the first catalogue is **an output of the agent and human review**, and later catalogues are approved versions of that output. The existing Flask/Python backend and separate worker remain the intended host for this workflow; an older D1 diagram's LangGraph.js and Node.js runner are not the chosen harness runtime.

## The harness in one view

A harness is application code around an LLM: it supplies instructions and tools, executes tool calls, persists state, checks outputs, controls retries, and decides when to involve a human. The model proposes meaning; connector code reads source data; validators enforce rules; the human authorizes the result. LangGraph can coordinate those steps, but it does not replace the LLM API, connector implementations, or validation code.

```mermaid
flowchart TD
    SRC[Connected files, databases, APIs, ERP/CRM] --> CON[Connector and read-only tool layer]
    CON --> SNAP[Versioned source snapshot and profiles]
    SNAP --> DESIGN[LLM: draft warehouse schema]
    DESIGN --> MAP[LLM: draft mappings and transforms]
    MAP --> RULES[Deterministic validation]
    RULES --> CRITIC[LLM: semantic critique]
    CRITIC --> DECIDE{Ready or revision limit?}
    DECIDE -->|Revise| DESIGN
    DECIDE -->|Reviewable| UI[One human review package]
    UI -->|Edit schema or mapping| REMAP[Rebuild affected mappings and recheck]
    REMAP --> UI
    UI -->|Approve| VERSION[Immutable approved version]
    VERSION --> EXEC[Governed execution, later stage]
    EXEC --> WH[Raw data and approved warehouse tables]
```

**Input:** one or more authorized source connections plus their discoverable resources, metadata, and limited samples. **First output:** a reviewable draft containing a warehouse model, source-to-target mappings, transformations, checks, evidence, and unresolved decisions. **Final output:** an immutable, human-approved version of the valid package. The first harness run stops at the review package; execution only consumes an approved version.

## 1. Source input and discovery

### What enters the harness

An operator connects or uploads sources, for example a PostgreSQL ERP database, an Excel workbook, a Drive folder, or an API. Each connection has an organization-scoped `source_id`, connector type, allowed resources, credential reference, and read permissions. Credentials are held in deployment secrets, never in prompts, tool results, or the metadata catalogue.

The discovery service creates a **source snapshot** with a stable ID and capture time. For each resource (table, sheet, file, API collection), it records what is available: name/path, connector ID, field names and types, descriptions, declared keys and relationships, nested structure, approximate row count, timestamps, and source-provided metadata. Profiling adds bounded examples, null rates, distinct counts, candidate keys, value ranges, distributions, date ranges, and possible sensitive-data classifications. Files and APIs may provide less metadata than databases; unavailable facts are marked unknown rather than invented.

Example: an `orders` table may expose `order_id`, `customer_id`, `placed_at`, and `total`, a declared primary key on `order_id`, and sample rows. A `customers` sheet may expose `customer_id` and `name` but no declared key. The harness can test candidate key uniqueness and value overlap through the same profile tools regardless of where those resources live.

The source snapshot is the evidence boundary for a proposal. A later source change produces a new snapshot rather than silently changing the meaning of an existing proposal. Raw files and records remain in their source or a controlled landing store; the control database stores metadata, references, profiles, proposals, approval history, and run state. If a connector cannot provide an immutable source version, the runner must recheck its fingerprint or change cursor before execution and refuse to treat changed data as the reviewed snapshot.

### Connector contract and tools

All connectors expose the same logical read interface. A connector may report a capability as unsupported; the harness must not assume that every source can run SQL, provide keys, or support incremental reads.

| Tool/capability | Input | Bounded result |
|---|---|---|
| `list_resources` | Source ID, path/filter, page token | Resource IDs, names, kinds, next page token |
| `describe_resource` | Source ID, resource ID | Fields, types, descriptions, declared keys/links, source metadata |
| `profile_resource` | Resource ID, selected fields, profile options | Counts, nulls, cardinality, ranges, candidate keys, distributions |
| `sample_rows` | Resource ID, selected fields, sample limit | Redacted representative rows with sampling method |
| `compare_fields` | Two field references, bounded sample options | Type compatibility, value overlap, uniqueness and join-cardinality evidence |
| `get_changes` | Source ID, previous snapshot/cursor | Changed resources or an explicit `unsupported` result |

Tools are implemented by application services over the connector interface, not by source-specific instructions embedded in the prompt. A tool call identifies authorized sources and resources by stable IDs; the service checks tenant access, enforces read-only access, limits rows/bytes/time, redacts sensitive values, and returns typed results with error codes. It never accepts arbitrary model-generated SQL or unrestricted URLs as a default tool. The agent can choose which resources or fields to inspect further, but cannot expand its own permissions.

For large source estates, discovery lists and profiles resources in pages and prioritizes uncertain or related resources for deeper inspection. The initial prompt includes a compact source inventory and tool descriptions, not a dump of the whole database. Each tool result is returned to the LLM as structured context and recorded against the snapshot. This keeps the prompt bounded and makes the proposal reproducible and auditable.

### What the agent is told at startup

The schema-design agent receives a versioned system instruction with these rules:

- Build a general-purpose analytical model from observed source structure and meaning; do not assume a business question or a pre-existing target schema.
- Preserve source grain, useful attributes, identifiers, relationships, dates, and provenance. Explain intentional omissions and keep the raw source available.
- Use only authorized tools and cite source resource/field IDs and profile evidence for proposed entities, attributes, and relationships.
- Distinguish observed facts, inferred semantics, and uncertainty. Never invent a source field, join, value, or certainty.
- Return a structured proposal matching the output contract. Do not create tables, execute transformations, or approve your own proposal.

The prompt also supplies the current snapshot ID, compact inventory, tool schemas, output schema, and budgets. Source names, descriptions, and sample text are **untrusted data** and cannot override these instructions.

## 2. Three-stage proposal loop

### Stage A: Design a warehouse model

The design agent calls discovery and profile tools as needed. It identifies candidate business entities, events, reference data, attributes, keys, relationships, and table grain. It may choose normalized canonical tables or event/fact and dimension structures where the evidence supports them. It records why each table and attribute exists, its source evidence, confidence, and unresolved ambiguity. It does not need a preset catalogue or a business question.

The model must account for all discovered source fields. A field can be represented directly, retained only in the raw layer with an explanation, classified as operational-only/sensitive, or marked unresolved. A field is never silently dropped. Source-preserving raw data protects against future questions the initial analytical model did not anticipate; it does not make the analytical model automatically complete.

### Stage B: Map sources into the draft model

The mapping agent receives the **draft** model and the same frozen source snapshot. It proposes, for every target attribute, one or more source field references, join paths, transformations, null/default behavior, and a load or merge key. It also records source-field coverage and any ambiguous or unmapped fields. Cross-source joins require evidence about key meaning, uniqueness, overlap, and cardinality; matching names alone are insufficient.

Transformations are declarative operations from an allowed vocabulary (for example cast, normalize, parse date, deduplicate, join, flatten, derive), with typed inputs and outputs. The agent does not emit executable SQL or Python to run directly. Later execution compiles approved operations through trusted code. If a value cannot be mapped safely, the proposal exposes it as unresolved for human review rather than guessing.

### Stage C: Check, critique, and revise

The validator runs first. It checks the output contract, unique and legal names, supported types, referenced fields and tables, key and relationship integrity, transformation type compatibility, join cardinality risk, target-attribute population, source-field coverage, and explicit treatment of omissions. Profile-based checks flag suspicious null, uniqueness, range, or value-overlap assumptions. A blocker means the package is not executable; a warning remains visible to the reviewer.

A separate LLM critic then evaluates **semantic** quality: coherent table meanings and grain, plausible relationships, conflated concepts, confusing names, information loss through flattening or aggregation, and whether important source concepts are missing. It receives the draft plus source citations and deterministic findings, not an unbounded database dump. It returns structured findings with severity, target IDs, evidence, and a suggested action. The critic cannot approve, mutate, or execute the draft. It may use the same configured model provider under a different prompt; independence comes from the separate reviewer role and structured evidence, not necessarily a second vendor.

The design/mapping agent receives both sets of findings and revises the relevant parts. The harness reruns deterministic checks and semantic review on the new version. Use a configurable small revision limit (three rounds initially), plus tool-call, token, and elapsed-time budgets. Stop earlier when checks pass and the critic has no new material finding. At the limit, persist a reviewable package with explicit unresolved items; do not claim it passed. A proposal with structural blockers cannot be approved until corrected.

```text
tool request -> authorized tool execution -> typed result -> LLM context
schema draft -> mapping draft -> rule findings -> critic findings
             -> revise -> rerun checks -> review package
```

The LLM may reason over evidence, but the application relies on explicit calls, validated structured outputs, and recorded decisions. Conversation text alone is never the system of record.

## 3. Review package and output contracts

The proposed package is one versioned object. The following is an **illustrative contract**, not an existing API payload:

```json
{
  "proposal_id": "proposal-42",
  "revision": 2,
  "source_snapshot_ids": ["snapshot-7", "snapshot-8"],
  "status": "needs_review",
  "model": {
    "tables": [
      {
        "id": "orders",
        "name": "orders",
        "kind": "event",
        "grain": "one row per source order",
        "key": ["order_id"],
        "attributes": [
          {"id": "order_id", "type": "text", "nullable": false, "evidence": ["erp.orders.order_id"]},
          {"id": "customer_id", "type": "text", "nullable": false, "evidence": ["erp.orders.customer_id"]},
          {"id": "placed_at", "type": "timestamp", "nullable": true, "evidence": ["erp.orders.placed_at"]}
        ],
        "relationships": [
          {"from": "orders.customer_id", "to": "customers.customer_id", "cardinality": "many_to_one", "evidence": ["profile-19"]}
        ]
      },
      {
        "id": "customers",
        "name": "customers",
        "kind": "entity",
        "grain": "one row per customer",
        "key": ["customer_id"],
        "attributes": [
          {"id": "customer_id", "type": "text", "nullable": false, "evidence": ["erp.customers.customer_id"]}
        ],
        "relationships": []
      }
    ]
  },
  "mappings": [
    {"target": "orders.order_id", "sources": ["erp.orders.order_id"], "operations": [], "confidence": 0.99},
    {"target": "orders.customer_id", "sources": ["erp.orders.customer_id"], "operations": [], "confidence": 0.95},
    {"target": "orders.placed_at", "sources": ["erp.orders.placed_at"], "operations": ["parse_timestamp"], "confidence": 0.91},
    {"target": "customers.customer_id", "sources": ["erp.customers.customer_id"], "operations": [], "confidence": 0.95}
  ],
  "source_coverage": [
    {"field": "erp.orders.internal_note", "disposition": "raw_only", "reason": "Operational free text; review sensitivity before modeling"}
  ],
  "findings": [
    {"severity": "warning", "target": "orders.placed_at", "message": "Date format varies in samples", "evidence": ["profile-21"]}
  ]
}
```

The example is shortened to show the shape of the package. Formal API schemas must enforce complete references and distinguish IDs from display names. The full package also carries transformation definitions, target-source lineage, quality rules, prompt/model versions, tool-result references, validation results, critic findings, and proposal revision history. IDs refer to immutable snapshots and evidence, not mutable row positions.

### One human review surface

The UI presents proposed tables, attributes, grain, keys, and relationships alongside the source fields and transformations that will populate them. For each item it shows evidence and confidence; a coverage view shows represented, raw-only, excluded, and unresolved source fields. Structural blockers and semantic warnings are visible in context. Reviewers can add, rename, change, or remove tables, attributes, relationships, mappings, and transformations, including decisions about previously unmapped fields.

An edit creates a new draft revision. Changing a target schema field invalidates its dependent mappings and checks; the harness remaps the affected area and reruns **all cross-package deterministic checks** and semantic review. It preserves intentional human edits as constraints rather than overwriting them with a fresh agent proposal. If the edit cannot be mapped, the UI shows the unresolved dependency and keeps approval blocked for structural errors. Human review is a single stage for schema **and** mappings, not an earlier schema-only approval followed by a second review.

Approval records the reviewer, time, organization, approved proposal revision, source snapshot IDs, and validation result. It creates an immutable model-and-mapping version. Later edits or source drift start a new draft version; they never rewrite the version used by a running or historical pipeline. Execution accepts only an approved version and uses the same version ID for warehouse schema creation, transformations, quality checks, and lineage.

## 4. How LangGraph runs the harness

A hand-written `while` loop could send the model tools, run requested calls, feed results back, and repeat. LangGraph expresses the larger flow as named nodes with shared state and conditional edges. Each node is still ordinary Python calling an LLM, connector service, validator, or persistence service. Use Python LangGraph in the Flask/backend worker codebase, consistent with the current backend architecture. Long-running graph work runs in the worker, while the API creates a job and returns its ID.

### State and nodes

The graph state contains references and small outputs, not raw datasets:

```text
job_id, organization_id, source_snapshot_ids, source_inventory_ref,
tool_budget, tool_result_refs, model_proposal, mapping_proposal,
validation_findings, critic_findings, revision_count, status,
human_edits, approval_ref, prompt_version, model_version
```

| Node | Responsibility | Next step |
|---|---|---|
| `discover` | Freeze authorized source snapshots and profiles; record missing capabilities. | `design_schema` or failed discovery |
| `design_schema` | Ask the model to inspect further through tools and return a typed model draft. | `map_sources` |
| `map_sources` | Build mappings, transformations, coverage, and lineage against that draft. | `validate` |
| `validate` | Run deterministic structural and profile checks. | `semantic_review` or a revision path if output cannot be parsed |
| `semantic_review` | Obtain a separate structured critique. | `route_findings` |
| `route_findings` | Stop when reviewable; otherwise send findings to revision within budgets. | `revise` or `await_human` |
| `revise` | Update affected model/mappings while respecting human edits. | `validate` (or `map_sources` if the model changed) |
| `await_human` | Persist and expose the package; pause for edits or approval. | `revise` after edits, `approved` after approval |
| `approved` | Persist the immutable version and hand its ID to the execution boundary. | End of harness |

Within `design_schema` and `map_sources`, the **tool loop** has a conditional edge: if the model requests an allowed tool, dispatch it, append its typed result, and call the model again; if it returns the required structured proposal, continue. A tool error is reported as data with an actionable code, subject to a bounded retry policy. Tool exhaustion or source inaccessibility yields a failed/incomplete job with visible evidence, not a fabricated proposal.

The **revision loop** is separate: `validate` and `semantic_review` produce findings, `route_findings` chooses revision or human review, and every revision is saved. A checkpointer keyed by `job_id` persists state at node boundaries so a worker restart or human pause does not lose the job. Checkpoints support resumption; durable proposal, evidence, edits, and approval records live in the control database rather than only in LLM messages. The review API can resume the graph after a saved human edit or approval event.

```mermaid
flowchart LR
    D[discover] --> S[design_schema]
    S -->|tool call| T[tool dispatcher]
    T --> S
    S --> M[map_sources]
    M -->|tool call| T2[tool dispatcher]
    T2 --> M
    M --> V[validate]
    V --> C[semantic_review]
    C --> R{route_findings}
    R -->|Revise within budget| X[revise]
    X --> M
    R -->|Reviewable or limit reached| H[await_human]
    H -->|Human edit| X
    H -->|Approval of valid revision| A[approved]
```

Conditional routing must be explicit in code: the model cannot direct itself to `approved`. The graph should keep a clear terminal state for failed discovery, invalid output after retries, cancelled review, and approved output. Repeated tool requests, cycles with no material improvement, and repeated critic findings consume budgets and eventually surface to the reviewer or fail with an actionable reason. The separate execution worker never reads an unapproved graph draft.

## 5. Ordered implementation sequence and team handoffs

The harness should be built in eight ordered parts. Each part has a clear dependency on the previous part, a concrete handoff artifact, and an acceptance gate. A different person can own each part, but the next owner starts from the latest integrated branch after the previous part's change is reviewed and merged. Investigation and design discussions can happen in parallel; implementation should follow this order so that later work builds on real, tested contracts rather than assumptions.

Every part must finish with four things: a working change or demonstrable spike, focused tests or a repeatable demo, documentation of the behavior and interfaces, and a short handoff that records decisions, known limitations, and the exact artifacts the next part consumes. No part should silently redefine an earlier contract. If a contract must change, update its version and document the migration before the next part starts.

### Part 1 — Harness foundation and contracts

**Purpose:** establish the stable boundaries that every later part uses.

Define the graph state, job lifecycle, proposal and revision identifiers, connector capability interface, tool request/result envelopes, structured LLM output contracts, and persistence references. Build a small LangGraph spike with a fake connector that demonstrates one model tool request, authorized tool execution, a typed tool result, a structured model response, and a checkpoint that can be resumed.

**Consumes:** project configuration and the harness architecture in this document.

**Produces:** versioned contract definitions, a minimal graph runner, fake source fixtures, and a decision record for budgets, statuses, and error envelopes.

**Acceptance gate:** a test can start a job, complete a tool call, persist the result, resume from a checkpoint, and end with a schema-valid structured output without connecting to a real source or LLM provider.

**Handoff to Part 2:** connector and tool contracts are stable enough for real discovery implementations; later parts must use the source/resource/field identifiers defined here.

### Part 2 — Source discovery and profiling

**Purpose:** turn connected sources into bounded, versioned evidence that the agent can inspect.

Implement connector-backed resource listing, resource descriptions, bounded sampling, profiling, candidate-key checks, and candidate-field comparison. Preserve connector capabilities and unsupported operations explicitly. Test the same discovery flow with at least two source classes, such as a file source and a relational database, while keeping the agent-facing tool names and result shapes identical.

**Consumes:** Part 1 connector/tool contracts and source fixture conventions.

**Produces:** source snapshots, profile reports, redaction and access checks, connector contract tests, and a source inventory that the graph can reference without embedding raw datasets in state.

**Acceptance gate:** a source can be snapshotted, profiled, and sampled through the common interface; results are bounded, tenant-scoped, reproducible enough for review, and explicit about unavailable metadata.

**Handoff to Part 3:** the schema agent receives stable source snapshot IDs, resource/field references, profile evidence, and discovery tools regardless of connector type.

### Part 3 — Warehouse schema proposal

**Purpose:** generate the first analytical model when the warehouse has no predefined schema.

Implement the schema-design prompt and graph node. The agent must propose a broad reusable model without receiving a business question or target catalogue. It must describe table grain, entities/events/reference data, attributes, keys, relationships, source evidence, confidence, and uncertainty. It must give every discovered source field an explicit disposition: represented in the model, retained raw-only, intentionally excluded with a reason, sensitive/restricted, or unresolved.

**Consumes:** Part 2 source snapshots, profiles, inventory, and read-only discovery tools.

**Produces:** a versioned `WarehouseModelProposal` with stable target IDs, evidence references, grain, relationship candidates, and source coverage.

**Acceptance gate:** the output validates against its structured contract, contains no invented source fields, preserves source grain where possible, and has no silent source-field omissions.

**Handoff to Part 4:** the mapping stage can address target tables and attributes by stable IDs and can trace every proposal decision to source evidence.

### Part 4 — Relationship, mapping, and transformation plans

**Purpose:** explain how source data will populate the draft model.

Implement relationship inference and mapping proposal generation against the frozen source snapshot and the Part 3 model. Use declared keys, value overlap, uniqueness, cardinality, nested structure, names, descriptions, and profile evidence; matching names alone are insufficient for a join. Describe transformations as typed declarative operations from an allowed vocabulary such as cast, normalize, parse date, deduplicate, join, flatten, and derive. Include null/default behavior, merge keys, source coverage, ambiguous mappings, and lineage references. Do not execute model-generated SQL or Python.

**Consumes:** Part 2 evidence and Part 3 `WarehouseModelProposal`.

**Produces:** a complete schema-and-mapping proposal package containing mappings, join paths, transformation plans, unresolved fields, and source-to-target lineage references.

**Acceptance gate:** every target attribute has a mapping, derivation, or explicit unresolved disposition; every mapping points to real source fields; transformations have typed inputs/outputs; and high-risk joins are flagged.

**Handoff to Part 5:** the quality system receives one package it can validate as a whole, rather than separate untraceable schema and mapping drafts.

### Part 5 — Automated quality and bounded revision loop

**Purpose:** find structural and semantic problems before human review while preventing an unbounded agent loop.

Run deterministic checks first: output shape, names and identifiers, references, types, keys, relationships, transformation compatibility, mapping coverage, source dispositions, join-cardinality risk, and profile-based null, uniqueness, range, and overlap warnings. Then run a separate structured LLM critique for semantic issues such as incoherent table grain, conflated concepts, implausible relationships, confusing names, and information loss.

Feed both finding sets back to the proposal agent for a bounded number of revisions, initially three rounds, with tool-call, token, and elapsed-time budgets. Persist every revision and finding. Stop early when blockers are gone and no material semantic finding remains. At the limit, produce a reviewable package with explicit unresolved issues; never claim that the package passed. Structural blockers remain approval-blocking.

**Consumes:** Part 4 proposal package and its evidence references.

**Produces:** deterministic validation results, semantic critique findings, revised proposal versions, and a clear distinction between blockers, warnings, and unresolved decisions.

**Acceptance gate:** the same input is checked repeatably, revisions cannot bypass deterministic validation, loops terminate at their budgets, and no invalid package is marked ready for approval.

**Handoff to Part 6:** the review UI has all evidence needed to show why each schema and mapping decision exists and what still needs attention.

### Part 6 — Combined human review and approval

**Purpose:** let a human review and edit the schema and mappings together as one coherent package.

Build one review surface showing tables, attributes, grain, keys, relationships, source fields, transformations, evidence, confidence, coverage, warnings, blockers, and unresolved decisions side by side. A reviewer can add, rename, change, or delete schema elements and mappings. Each edit creates a new draft revision, invalidates dependent mappings where necessary, reruns the affected mapping work and all cross-package deterministic checks, and reruns semantic review before the package can be approved. Human edits become constraints and must not be overwritten by a fresh agent proposal.

Approval records the reviewer, timestamp, organization, proposal revision, source snapshot IDs, and validation result. It creates one immutable model-and-mapping version. There is no separate schema-only approval followed by another mapping approval; the UI reviews the combined package once.

**Consumes:** Part 5 reviewable proposal and findings.

**Produces:** a draft-edit API/UI and an immutable approved version, or a visible blocked state with actionable findings.

**Acceptance gate:** edits rerun the correct dependent work, approval is impossible with structural blockers, approved versions cannot be mutated, and later drafts do not change historical approvals.

**Handoff to Part 7:** execution can accept exactly one approved version ID and use it as the authority for schema creation, transformations, quality rules, and lineage.

### Part 7 — Governed execution

**Purpose:** safely turn an approved proposal into warehouse structures and loaded data.

Compile only the approved declarative transformation vocabulary into trusted execution code. Use raw/landing data, staging tables, safe merge or upsert behavior, idempotent run IDs, permission boundaries, and quality checks before publishing. The model cannot issue DDL, arbitrary SQL, or direct writes. A failed load must remain failed and must not be reported as successful or leave an untracked partial publication.

**Consumes:** the immutable approved version from Part 6 and its referenced source snapshots.

**Produces:** target table definitions, staged and published data, run status/counts/errors, rejected-record handling, and execution lineage.

**Acceptance gate:** only approved versions execute; reruns do not duplicate data; staging and publication behavior is safe; and the run records the exact approved version and source evidence it used.

**Handoff to Part 8:** operations has durable run state, errors, counts, and version references to monitor and recover.

### Part 8 — Operations, lineage, drift, and recovery

**Purpose:** keep approved pipelines understandable and reliable after the first successful load.

Add run monitoring, checkpoints, bounded retries and backoff, resumable failure handling, quarantine/error records, alerts, source schema-drift comparison, and end-to-end lineage from source resource/field through profile, proposal, mapping, transformation, approval, run, and target column. Compatible drift can create a new draft; missing fields, changed types/meanings, and relationship changes require review. The active approved version remains stable until a replacement is approved.

**Consumes:** Part 7 run records and all prior version/evidence references.

**Produces:** operational dashboards/status APIs, retry and recovery behavior, drift events, impact reports, and lineage queries.

**Acceptance gate:** operators can identify run state and actionable errors, recover only eligible failures, trace a target value back to source evidence, and see source changes before they alter approved behavior.

### Cross-cutting rules for every part

- Keep connector interfaces, prompts, proposal structures, validators, and tests source-agnostic from Part 1 onward; do not hardcode one ERP's tables or workflow.
- Carry stable version, evidence, and lineage references through every artifact instead of adding lineage at the end.
- Preserve a source-serving raw/landing representation and record a disposition for every discovered field.
- Keep credentials and unrestricted source data out of prompts, graph state, logs, and the control database.
- Treat model output as an untrusted proposal. Only deterministic validation and an explicit human approval can make a version eligible for execution.

## 6. Safety, later execution, and change handling

- **Source agnosticism:** Connector-specific parsing and access stay behind the standard contract. Prompts, graph nodes, model types, and validators use resource/field references, not hardcoded ERP tables or vendor workflows. Contract tests should use at least a file, relational database, and API-style fixture.
- **Information preservation:** Store or retain a source-preserving raw copy/reference; record every discovered field's disposition. Proposed canonical tables should preserve identifiable records and relationships wherever practical. Flag lossy casts, deduplication, flattening, and aggregation for review.
- **Governance:** Tool execution is read-only and tenant-scoped. Redact samples and minimize data sent to the model. Only trusted compiler/executor code can create warehouse tables or load rows after approval; the model cannot issue DDL or arbitrary execution commands.
- **Execution and quality:** The approved package defines staging, merge/upsert keys, transformation rules, and data-quality checks. A later runner validates counts, null/uniqueness/referential constraints, rejects bad rows, and publishes only a successful load. Runs record status, retries, failures, and the exact approved version.
- **Lineage:** Preserve links from source snapshot/resource/field through tool evidence, model attribute, mapping, transform, approval, and execution run to target table/column. This lets a reviewer see why a field exists and an operator identify what a source change affects.
- **Drift:** New source snapshots are compared with those referenced by the approved package. Compatible changes may generate a new draft; missing fields, changed meanings/types, and relationship changes require review. The active approved version remains stable until a replacement is approved.
- **Failure and recovery:** Connector outages, unsafe or missing permissions, model errors, invalid structured output, and validation blockers are explicit job states. Retry transient failures within limits and resume from checkpoints; never label an incomplete or failed run successful.

## 7. Walkthrough: a new ERP source

1. An operator connects an ERP database. The connector lists `orders`, `order_lines`, and `customers`; discovery saves a snapshot of their fields, key metadata, bounded samples, and profiles.
2. The design agent receives the inventory and tools. It inspects detailed profiles and candidate joins, then proposes `orders`, `order_lines`, and `customers` tables with grain, keys, attributes, and relationships. It keeps source-only operational fields in the raw layer and explains their disposition.
3. The mapping agent ties source fields to each proposed target attribute, specifies any type conversion or join, and reports unresolved fields. No target catalogue was supplied.
4. Validators check references, type compatibility, key evidence, and coverage. A critic flags a possible billing-account/customer ambiguity. The agent revises if evidence resolves it; otherwise the warning remains visible.
5. The UI displays tables and mappings together. A reviewer changes `customers` to `accounts` and adds an attribute. The harness remaps affected fields, reruns checks, and shows any unresolved population rule.
6. The reviewer approves the resulting version. Only then may a later execution job create the target tables and load transformed data, using the approved version and source snapshots for traceability.
