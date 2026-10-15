# US3 inventory adapter plan

## Scope

Adapt one existing structural DiscoveryResult into the canonical InventoryView from app.agent.contracts. Reuse the frozen shared contract without adding fields, inferred business metadata, persistence, HTTP routes or graph dependencies.

## Success criteria

- Caller supplies snapshot/source/resource identity, display name and resource kind.
- Preserve every canonical path, field order, nullable/repeating flag and all observed types.
- Normalize strings to text and booleans/numbers to matching source types; containers, mixed non-null types and null-only observations use json.
- Preserve original structural type evidence in native_type using an observed: prefix.
- Render samples as JSON literals inside the contract's list of strings so strings, booleans, numbers and null remain distinguishable.
- Leave status unknown, description/ambiguity unset; do not guess stable history or semantic types.
- Validate construction through the existing Pydantic contracts. Keep original DiscoveryResult for sampling metadata absent from InventoryView.
- Inspect synthetic conversion output, compile changed Python and typecheck/build the frontend after the base sync. Document results and limits precisely.

## Sequence

- [x] Inspect instructions, source report and frozen contract; sync main and the original shared-contract dependency.
- [x] Add the pure adapter and document conversion policy and caller responsibilities.
- [x] Inspect fixture conversion/serialization and complete build/type checks.
- [x] Finalize the plan, commit A, push and update PR description.

## Boundaries

One report describes one caller-selected resource. Paths such as lines[].sku remain relative to that resource; automatic extraction into orders.lines[] is a separate source-normalization concern. Existing FieldRef accepts canonical literal-key paths, but downstream mapping/tool identifier restrictions are not resolved here. The adapter does not call exposure/redaction policy or make samples safe for an LLM. It does not persist sampling metadata, generate IDs or compare snapshots.

## Verification

- Synthetic orders converted to one resource with all 14 fields; selected output confirmed mixed total->json with observed:null|number|string, quoted leading-zero IDs, boolean literals, unchanged date text and repeating nested paths.
- Manually inspected null-only->json, nullable number->number, mixed boolean/number->json, literal dot vs nested path, and zero-field resource output.
- Shared InventoryView JSON serialization/revalidation round-trip succeeded; the original discovery report remained equal to a fresh discovery result.
- Python compile checks passed for the discovery module and adapter. Frontend TypeScript check and Vite production build passed after syncing main.
- Shared contract/API/error files remain byte-identical to the original dependency commit. Diff whitespace checks passed.
- No automated tests were added or run for this increment; the existing core's prior 44-test result predates this base sync. No database, HTTP service, browser or model integration was exercised.

## Dependency history

Main was merged as 0a3adab. Shared contracts were merged as e85d836, preserving the original ca87e2a commit and author history. The requirements conflict was resolved by retaining auth dependencies and pydantic. The adapter is a separate feature commit; no graph or persistence implementation is imported.
