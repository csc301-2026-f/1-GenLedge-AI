# Connect feature-login to developer PostgreSQL databases

## Plan

- [x] Inspect the backend, launcher, database documentation, tests, and branch state.
- [x] Synchronize `feature-login` with the merged `origin/main` without changing `main` or the pre-existing D1 image.
- [x] Add tracked backend environment placeholders and automatic `.env` loading with explicit PostgreSQL TLS settings.
- [x] Add an initial Alembic migration, migration-backed auth initialization, and a read-only connection check.
- [x] Document per-developer versus shared integration database setup, credential handling, and troubleshooting.
- [x] Add opt-in PostgreSQL verification and run the backend/frontend checks.

## Review

The backend suite passed with 16 tests and one opt-in PostgreSQL test skipped
because no developer credential was available. TypeScript checking and the
Vite build passed. `Test-NetConnection` reached `301db.dbestserv.com:5432`
from this machine, but authentication, authorization, and TLS remain unverified
without a developer role. The pre-existing D1 image was preserved. The root
README remains untouched as requested.
