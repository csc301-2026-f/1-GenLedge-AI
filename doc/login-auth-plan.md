# Login implementation plan

- [x] Implement auth models, database sessions, CLI provisioning and revocable cookie sessions.
- [x] Add validated login/me/logout APIs, CSRF checks and organization access helpers.
- [x] Connect the React login, session restoration and logout using a Vite API proxy.
- [x] Verify focused auth tests and frontend build; document setup and limitations.

Preserve existing deliverables/D1 image changes. Account creation is admin CLI only.
Use DATABASE_URL for PostgreSQL; SQLite is a local development fallback.

Verification: 10 backend tests pass using SQLite, TypeScript tsc --noEmit passes,
Vite production build passes. Reviewed diff and git diff --check. No live browser
smoke test or PostgreSQL integration test was performed. Setup and production
follow-up are documented in doc/auth-implementation.md.
