# Login implementation plan

- [x] Implement auth models, database sessions, CLI provisioning and revocable cookie sessions.
- [x] Add validated login/me/logout APIs, CSRF checks and organization access helpers.
- [x] Connect the React login, session restoration and logout using a Vite API proxy.
- [x] Verify focused auth tests and frontend build; document setup and limitations.

Preserve the D1 images from main. Account creation is admin CLI only.
Use DATABASE_URL for PostgreSQL; SQLite is a local development fallback.

Integration verification: 10 backend tests pass using SQLite, TypeScript
`tsc --noEmit` passes, and the Vite production build passes. A live HTTP flow
through the Vite proxy returned 401 for an incorrect password, 200 for login
and session restore, 204 for logout, and 401 after logout. PostgreSQL
integration and the Playwright browser smoke test were not run. Setup and
production follow-up are documented in `doc/auth-implementation.md`.
