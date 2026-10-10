# Backend authentication ExecPlan

- [x] Fetch origin and branch backend-1 from origin/main (6432775); preserve existing untracked HTML assets.
- [x] Establish scaffold baseline and failing auth tests.
- [x] Implement JSON routes, signed session and configuration.
- [x] Run pytest and real HTTP cookie lifecycle on a non-default port.
- [x] Document contract, inspect diff, commit and push before Plan 2.

## Verification
System Python lacks pytest; use /tmp/genledge-auth-venv with repository requirements-dev.txt.

Baseline: 1 scaffold test passed. Before implementation: 17 auth cases failed on missing routes/configuration. After implementation: `python -m pytest tests -q` from src/backend passed all 18 tests using the temporary venv. An initial root-directory invocation could not import app; corrected to the documented backend directory. Real HTTP check uses /tmp/genledge-http-check.py and automatically stops main.py.

Handoff: doc/auth-api.md is the final contract; no API deviations. Plan 2 continues on this branch only after successful backend push. No frontend or launcher changes in this stage.
Real HTTP verification passed on port 65486: 401 → login 200 → me 200 → logout 200 → me 401. Diff whitespace check passed. Inspected auth state/response: no password retention and no unrelated tracked changes.
