# US3 date ambiguity plan

## Scope

Detect potentially ambiguous slash-separated date strings during bounded structural discovery, carry that evidence into the existing inventory contract, and display it in the discovery preview. Preserve values and types. No locale selection, conversion, reviewer resolution, storage, API or execution changes.

## Success criteria

- Match one/two-digit day and month followed by a four-digit year, with optional surrounding whitespace.
- Flag only when DD/MM/YYYY and MM/DD/YYYY both describe valid, different Gregorian dates.
- Keep ISO year-first dates, invalid dates and identical interpretations unflagged without asserting the field's format is known.
- Inspect every observed string within the existing record limit, even after three display samples are collected; never inspect record 501.
- Preserve the existing paths/types/samples/flags and propagate optional ambiguity to InventoryField without changing the frozen shared contract.
- Show a field badge and explanatory notice from supplied results; regenerate synthetic preview payloads from the Python core.
- Compile Python, inspect representative outputs and boundaries, typecheck/build frontend and inspect the final diff. Record verification limits.

## Sequence

- [x] Read existing core, adapter, shared contract, UI and date transformation rules.
- [x] Implement the detector and propagate ambiguity through discovery and the adapter.
- [x] Update frontend presentation, generated preview data and technical/smoke documentation.
- [x] Complete checks, finalize plan, commit/push B and update the PR description.

## Contract

The raw version-1 discovery payload gains an optional ambiguity string only for flagged fields. Unflagged fields omit it. Existing field properties retain their meanings. The marker matches the existing seeded-inventory convention: date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY. The shared InventoryField already has an optional ambiguity property. Comparison remains path/type based and does not report ambiguity-only drift.

## Verification

- Manually inspected ambiguous padded/unpadded/whitespace slash dates, unambiguous day/month values, identical interpretations, invalid calendar dates, leap-day values, year zero, ISO strings, two-digit years, hyphen dates, timestamps and ordinary identifiers. Only valid distinct slash-date interpretations were marked.
- A four-record example marked the field even though the ambiguous fourth value was outside its three display samples. A 501-record iterator remained positioned at the unread ambiguous record after discovery sampled the first 500.
- Inspected nested-array metadata and propagation to InventoryField. Shared inventory JSON serialization/revalidation round-trip succeeded; original values and string/text types remained intact.
- Both generated fixture snapshots retain 14 fields. Existing comparison still reports added currency, missing paid and changed total types; empty discovery remains unchanged.
- Python compile checks, frontend TypeScript check, Vite production build and diff whitespace checks passed. Shared US4 contracts were not changed.
- No automated tests were added or run. Browser/manual UI checks are documented but were not executed; no database, HTTP, model or reviewer workflow was exercised.
