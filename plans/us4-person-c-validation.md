# US4 Person C: Projection and Validation

## Goal

Produce a reviewable mapping package from the frozen US4 contracts, with deterministic findings, coverage, and sample redaction. Preserve valid tables when another table is blocked.

## Steps

- [x] Verify the clean `us4/integration` base and create `us4/person-c-validation`.
- [x] Add negative tests for projection, all finding codes, redaction, and strict contract boundaries.
- [x] Implement pure projection, validation, and redaction helpers without changing contracts.
- [x] Publish valid and invalid integration examples and update smoke checks.
- [x] Run the backend suite, inspect the diff, perform the README accuracy gate, commit, and push.

## Review

Implementation and verification completed. `python -m pytest tests` passes 51 tests and `python -m compileall -q app/mappings/validation.py` completes successfully. The root README was inspected for the required recruiter-first and stack sections; it predates this focused backend change and remains protected by the repo-local README instruction, so no README mutation was made.
