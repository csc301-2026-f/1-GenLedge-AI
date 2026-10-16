# US3 source discovery plan

## Goal and current scope

Build structural discovery for parsed records, publish prepared inventory metadata, expose organization-scoped snapshot reads, and let the frontend inspect a saved snapshot and submit its ID to the routing API contract.

The implemented components do not yet form a complete upload-to-discovery workflow. Real source reading/re-sampling depends on US2; routing execution depends on US4. This plan tracks US3 work and its interfaces, without implementing those use cases.

Technical contracts, the finalized implementation record and historical verification are in [Source discovery](../doc/us3-discovery.md). Repeatable manual procedures are in [Smoke tests](../docs/smoke-tests.md). Earlier task-level plans are retained in Git history.

## Success criteria

- Inspect at most 500 parsed JSON-compatible records without reading beyond the bound or changing input values.
- Report deterministic canonical paths, observed type unions, nullable/repeating flags and at most three bounded samples; preserve date text and leading-zero identifiers.
- Compare observations by canonical path without deleting source fields or modifying mappings. Sample absence must not be presented as confirmed deletion.
- Detect distinct valid DD/MM/YYYY and MM/DD/YYYY interpretations in slash dates without choosing a locale or converting values.
- Adapt to the shared InventoryView with explicit source/resource/snapshot identity, conservative type projection, original type evidence and ambiguity.
- Publish only after an explicit preparation policy; reuse existing scoped immutable persistence and return the actual saved snapshot ID after deduplication.
- Read saved snapshots with login_required and server-derived organization scope. Unknown and foreign snapshots share 404; missing configuration/expected database failures produce safe 503 responses with no-store.
- Validate consumed HTTP data and show loading/error/empty/ready states, resources, filters, samples and ambiguity. Reload must read the same snapshot, not claim to re-sample.
- Submit only the loaded nonempty snapshot ID to the shared routing contract with credentials, CSRF and an idempotency key. Display an actual receipt/error without implying routing completion.

## Implemented work

- [x] Bounded discovery, immutable output contract, canonical paths and synthetic fixtures.
- [x] Sample-to-sample schema comparison and presentation support for changes.
- [x] Conservative slash-date ambiguity detection and propagation/display.
- [x] Shared inventory adapter, with no independent duplicate contract.
- [x] Prepared snapshot publication using the existing repository.
- [x] Authenticated organization-scoped saved-snapshot GET and API-driven frontend.
- [x] Discovery-side routing request/receipt handling, isolated from US4 implementation.

## Documentation consolidation

- [x] Inspect existing task plans, technical documentation, code and references.
- [x] Consolidate current scope, decisions, completed work, dependencies and qualified verification in this plan and the technical document.
- [x] Remove superseded task plans and duplicate finalized copies; preserve the manual checks and repair references.
- [x] Review the documentation-only diff and prepare a function-based PR description.

## Remaining US3 work and interfaces

| Work | Prerequisite | Intended outcome |
| --- | --- | --- |
| Source/resource selection | US2 exposes authorized listings or upload result identifiers | UI selects real data instead of requiring a manually supplied snapshot ID |
| Fresh discovery orchestration | US2 provides an authorized bounded reader and stable source/resource/batch identity | Read a pinned batch, discover, prepare and publish, then return the actual saved ID |
| Re-sample and drift flow | Fresh reader plus previous-version association and retained observation evidence | Compare old/new observations, show drift, preserve old snapshots and mapping references |
| Sampling metadata | Agreed persistence/API extension | Preserve sample count/method and source batch association without inventing total counts |
| Sample exposure | Agreed preparation policy | Expose only permitted metadata/sample values; the current helper requires an explicit callback |
| Downstream field semantics | US4 agrees resource scope, nested arrays and literal-key path support | Shared FieldRef values retain the same meaning across modules |

## Ownership boundaries

- US1 supplies authenticated identity, organization scope, CSRF and role/session policy. US3 reuses these helpers.
- US2 owns parsing and persistent raw storage. An upload batch and a schema snapshot are different artifacts; US3 must pin the intended batch and avoid reading another organization or a changing source version.
- Shared persistence already provides inventory transactions, scoped reads, deduplication and immutability. Control and auth migrations remain separate; application startup does not migrate/seed inventory.
- US4 owns the mapping job API, durable idempotency, authorization and configured execution runtime. This branch has only its client-side request consumer, not a working endpoint/graph.
- US5 owns reviewer-controlled ambiguity/mapping decisions; US6 applies approved transformation rules. US3 only reports observed evidence.

## Verification approach and limits

The finalized evidence table in the technical document distinguishes earlier automated core checks, manual PostgreSQL/API/browser inspection and frontend build checks. Historical results are not a current full-suite pass. The routing request has not been verified against a real job API. This documentation change runs no tests or build; checks are limited to diff scope, whitespace, surviving references and PR description consistency.
