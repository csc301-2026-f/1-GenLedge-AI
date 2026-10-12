# Login implementation plan

- [x] Implement auth models, database sessions, CLI provisioning and revocable cookie sessions.
- [x] Add validated login/me/logout APIs, CSRF checks and organization access helpers.
- [x] Connect the React login, session restoration and logout using a Vite API proxy.
- [x] Verify focused auth tests and frontend build; document setup and limitations.

Preserve the D1 images from main. Account creation is admin CLI only.
Use HOST, PORT, DATABASE, USER, and PASSWORD for PostgreSQL; SQLite is a local
development fallback.

Integration verification: backend tests, TypeScript check, and Vite build pass.
Browser and live proxy checks are tracked in the final review below.

## Main integration review

- [x] Base the branch on the merged `origin/main` and retain its demo and launchers.
- [x] Replace the connected app's mock auth while retaining restore, retry, and logout handling.
- [x] Keep the two D1 image files out of the login diff.
- [x] Run the live proxy flow and inspect the final PR diff.

Live proxy check: incorrect password 401, login 200, session restore 200,
logout 204, and subsequent session lookup 401. The Playwright smoke script
was updated but could not run because the local `playwright` package is absent.
PostgreSQL integration was not exercised.
