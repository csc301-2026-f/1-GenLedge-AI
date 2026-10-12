# Connect feature-login to developer PostgreSQL databases

## Plan

- [x] Inspect the backend, launcher, database documentation, tests, and branch state.
- [x] Synchronize `feature-login` with the merged `origin/main` without changing `main` or the pre-existing D1 image.
- [x] Add tracked backend environment placeholders and automatic `.env` loading with explicit PostgreSQL TLS settings.
- [x] Add an initial Alembic migration, migration-backed auth initialization, and a read-only connection check.
- [x] Document per-developer versus shared integration database setup, credential handling, and troubleshooting.
- [x] Add opt-in PostgreSQL verification and run the backend/frontend checks.
- [x] Make the existing app launchers apply pending migrations before startup.
- [x] Show a redacted database status summary and require confirmation before startup.

## Review

The backend suite passed with 16 tests and one opt-in PostgreSQL test skipped
because no developer credential was available. TypeScript checking and the
Vite build passed. `Test-NetConnection` reached `301db.dbestserv.com:5432`
from this machine, but authentication, authorization, and TLS remain unverified
without a developer role. The pre-existing D1 image was preserved. The root
README remains untouched as requested. Both launchers now run
`auth-db-check`, pause for confirmation, then run `auth-init-db` before starting
services and stop if the connection check or migration fails. The status check
normalizes copied JDBC/PostgreSQL URL forms and never prints passwords.
