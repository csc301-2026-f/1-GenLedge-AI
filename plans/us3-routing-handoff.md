# US3 routing handoff plan

## Scope

Add the discovery-side handoff to the existing US4 job-creation HTTP contract. Keep every change within discovery code and US3 documentation. Do not integrate or modify US4 endpoints, runtime, graph, repositories, routing/review UI, or auth policy.

## Success criteria

- Submit POST /api/mappings/jobs with the loaded canonical inventory.snapshot_id, credentials, X-CSRF-Token and Idempotency-Key. Never submit a typed-but-unloaded ID, default/demo snapshot, samples, organization identity or filtered field subset.
- Only a loaded inventory containing fields can submit. The whole snapshot is the unit of routing, regardless of resource selection or search filters.
- Prevent simultaneous submissions and snapshot replacement while submitting. Retain one request key and any accepted receipt for each snapshot while the discovery container stays mounted; retries reuse the key. Abort client requests on unmount and bound them by a timeout. Cancellation does not imply server rollback.
- Validate the actual HTTP job receipt and display its job ID/status without claiming routing completion or opening mocked routing screens. Missing API/config, authentication, malformed responses and network failures are explicit; retain the discovered fields.
- Run TypeScript checking, production build and diff review; accurately record verification limits.

## Sequence

- [x] Inspect current discovery/auth clients and the shared/PR18 job creation contract; confirm US3-only scope.
- [x] Implement the request boundary and per-snapshot handoff state.
- [x] Connect discovery controls and receipt/error display.
- [x] Review, typecheck/build, finalize docs and plan.
- [x] Prepare the focused feature for commit/push and the PR16 description update.

## Integration boundary

This branch has no mapping job endpoint. PR18 is the downstream contract reference and still requires integration with current authentication and a configured US4 runtime. No successful real job creation or execution can be claimed from this change alone. The client must display the missing endpoint honestly. Idempotency state is in component memory only and is reset when discovery unmounts or the page reloads.


## Verification and review

- Frontend TypeScript no-emit check passed after implementation.
- Vite production build passed (34 modules).
- Source review: the only POST body is the loaded snapshot ID; shared CreateMappingJobRequest/Response field names and all JobStatus values match the repository contracts. Auth CSRF protocol is consumed without editing auth code.
- React review: component state holds per-snapshot attempts, event handlers own submission, a ref guards duplicate in-flight requests, cleanup aborts and suppresses stale unmount updates, functional state updates preserve other snapshots, and resource/filter changes cannot replace the loaded snapshot during submission.
- No automated tests added/run. No browser/HTTP/real job creation, timeout injection or downstream runtime verification performed. The branch lacks the required job endpoint; this limitation is explicit in code/UI/docs.
- Only discovery code, US3 docs, this plan and its finalized doc copy are in scope. No README, US4 implementation, auth policy, dependencies, migration or database changes.
