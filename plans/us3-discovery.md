# US3 source discovery implementation plan

## Scope

Implement pure Python discovery over parsed JSON-compatible records, a synthetic fixture, a versioned output contract, and sample-to-sample drift comparison. The code lives in `app/sources` and requires no Flask context or database. Source readers, authentication, persistence, HTTP routes, frontend integration, and AI tooling are separate integrations.

## Acceptance criteria

- Inspect at most 500 input records without consuming later records.
- Report observed fields, nested paths, array element paths, types, nullable/repeating flags, and up to three distinct bounded sample values.
- Preserve strings, including leading-zero identifiers and date text, and distinguish booleans from numbers.
- Represent objects/arrays without copying their full contents into sample values.
- Preserve input records and distinguish literal punctuation in field names from structural paths.
- Compare discovery results by canonical path and report additions, fields missing from the new sample, and observed type changes without modifying mappings.
- Keep the existing backend tests passing and document the input/output contract and remaining integration boundaries.

## Sequence

- [x] Run the current backend test baseline.
- [x] Add synthetic discovery tests and confirm they fail because discovery is not implemented.
- [x] Implement bounded discovery and document its contract; verify before the discovery-core commit.
- [ ] Add drift tests, implement comparison, and update documentation; verify and commit.
- [ ] Inspect the final diff and save the finalized plan in `doc/`.

## Contract decisions

Records are already parsed dictionaries containing JSON values. Discovery performs structural type observation, not semantic type conversion. First-N sampling is reported as `head`. Canonical paths are local field references; global IDs and persisted snapshot IDs are supplied by a later integration contract. Dotted identifiers and `[]` represent nesting/repetition; other keys use JSON-quoted brackets so literal dots/brackets remain unambiguous.

Nullable describes observed null/missing values, not a database constraint. Missing fields during comparison are sampling observations, not proof of source deletion. Samples are capped at three values per field and 80 characters per string; containers use size summaries. Results do not redact scalar values and must pass through the caller's access/redaction policy before exposure to a browser or LLM.

## Verification

Baseline: 18 existing backend tests passed. The new discovery test module initially failed collection because `app.sources.discovery` did not exist. After implementation, the full suite passed 34 tests (18 existing and 16 discovery cases). The synthetic fixture smoke and final diff review are performed before the feature commit.
