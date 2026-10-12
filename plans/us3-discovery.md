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
- [x] Implement bounded discovery and document its contract; verify and commit the core.
- [x] Add drift tests, implement comparison, and update documentation; verify the comparison feature.
- [x] Inspect the final diff and save the finalized plan in `doc/`.

## Contract decisions

Records are already parsed dictionaries containing JSON values. Discovery performs structural type observation, not semantic type conversion. First-N sampling is reported as `head`. Canonical paths are local field references; global IDs and persisted snapshot IDs are supplied by a later integration contract. Dotted identifiers and `[]` represent nesting/repetition; other keys use JSON-quoted brackets so literal dots/brackets remain unambiguous.

Nullable describes observed null/missing values, not a database constraint. Missing fields during comparison are sampling observations, not proof of source deletion. Samples are capped at three values per field and 80 characters per string; containers use size summaries. Results do not redact scalar values and must pass through the caller's access/redaction policy before exposure to a browser or LLM.

## Verification

- Baseline: all 18 existing backend tests passed.
- Before implementation, the discovery module's tests failed collection because `app.sources.discovery` did not exist.
- Discovery core: 34 backend tests passed, including 16 discovery cases. Synthetic fixture smoke inspected three records and reported 14 fields. The core was committed as `07d778c`.
- Before comparison implementation, comparison tests failed collection because `compare_discoveries` did not exist.
- Final suite: 44 backend tests passed, including 26 US3 discovery/comparison cases. Command: `.venv/bin/python -m pytest tests -q -p no:cacheprovider` from `src/backend`.
- Refresh smoke reported added `currency`, missing `paid`, and observed `total` types changing from null/number/string to string. No database or API service was involved.
- `git diff --check` passed. Final scope review found no changes to frontend, authentication, startup scripts, database setup, README files, or historical deliverables.

## Handoff

Entry points are `discover_records` and `compare_discoveries` in `app.sources.discovery`. Input/output semantics and integration requirements are documented in `doc/us3-discovery.md`; repeatable fixture checks are in `docs/smoke-tests.md`.

Next integration work requires an authorized collection sample reader, stable collection/field identity policy, schema snapshot persistence/versioning, and an agreed UI/API contract. This change implements the independent US3 core; it does not claim the complete source-to-UI workflow or full harness profiling is implemented.
