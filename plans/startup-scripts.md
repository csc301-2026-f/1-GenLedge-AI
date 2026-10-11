# Split Demo And Full-Stack Launchers

- [x] Add standalone demo launchers for Unix and Windows on port 5174.
- [x] Keep full-stack launchers on explicit frontend/backend ports and label their output.
- [x] Add the Vite `/api` proxy for the Flask-backed frontend.
- [x] Document both workflows, prerequisites, and shutdown behavior.
- [x] Run shell, backend, frontend, and manual startup checks.

## Verification

Verification results:

- `bash -n src/start-app.sh src/start-demo.sh` passed.
- `python -m pytest tests` passed: 18 tests.
- `pnpm exec tsc --noEmit` passed in both frontend projects.
- `pnpm build` passed in `src/frontend`.
- The demo launcher served port 5174 without a Flask process.
- The full-stack launcher served ports 5173 and 5000; login, session restore,
  logout, and signed-out `/api/auth/me` passed through the Vite proxy.
- `git diff --check` passed.
