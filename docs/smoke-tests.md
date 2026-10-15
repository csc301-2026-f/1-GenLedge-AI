# Smoke Tests

## US4 source inventory and persistence

- Action: Run `python -m pytest tests/test_persistence_function_audit.py -q` with
  the local test DSN configured.
  Expected: 50 audit cases pass, including schema/configuration errors, malformed
  catalogue containers, boolean/number replay conflicts, normalized argument
  replay, revision immutability, and two complete smoke invocations. The error
  history and coverage commands are in
  [`doc/us4-persistence-function-audit.md`](../doc/us4-persistence-function-audit.md).

Setup commands and interface examples are in
[`doc/us4-source-persistence.md`](../doc/us4-source-persistence.md).

- Action: Configure a local PostgreSQL control database and run
  `python -m app.common.migrations` twice from `src/backend`.
  Expected: Both upgrades complete, with Alembic at `001_us4_control_plane` and no
  duplicate tables.
- Action: Run `python -m app.sources.fixtures`, then call
  `app.sources.service.get_inventory('demo-orders-snapshot-v1')`.
  Expected: An `InventoryView` contains `orders`, `orders.lines[]`, `customers`,
  18 fields, at most three samples per field, and ambiguous `order_date` metadata.
- Action: Run `python -m scripts.smoke_persistence` twice in separate processes.
  Expected: The same job and revision are read on the second run, its stored tool
  result replays with zero factory calls, and the `reject` edit remains visible.
- Action: Set `GENLEDGE_TEST_DATABASE_URL` to a separate local database and run
  `python -m pytest tests`.
  Expected: Inventory round-trip, SQL immutability, concurrent replay, package
  persistence, and cross-process reads pass. Without the test DSN, persistence
  tests report explicit skips.

## Development launchers

- Action: Run `./src/start-demo.sh` or `src\start-demo.bat` and open `http://127.0.0.1:5174`.
  Expected: The preserved standalone mock demo loads without requiring a Flask process.
- Action: Run `./src/start-app.sh` or `src\start-app.bat` and open `http://127.0.0.1:5173`.
  Expected: A redacted database status summary appears first and the launcher pauses for confirmation. After confirmation, pending Alembic migrations apply; then the connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite. If the connection check or migration fails, neither service starts.
- Action: Initialize the auth database, provision a user, then sign in with an incorrect password and the correct password at port 5173.
  Expected: The incorrect password is rejected; the correct password opens Sources.
- Action: Copy `src/backend/.env.example` to `src/backend/.env`, fill in `HOST`, `PORT`, `DATABASE`, `USER`, and `PASSWORD`, then run `auth-db-check`.
  Expected: Flask reports the expected PostgreSQL role and database without printing the password; TLS reports the configured connection state.
- Action: Run `auth-init-db` against a fresh developer database.
  Expected: The initial Alembic migration creates the auth tables and records the migration revision.
- Action: Refresh after login, sign out, then refresh again.
  Expected: The session restores before logout and stays signed out afterward.
- Action: Send an auth POST without a valid `X-CSRF-Token`.
  Expected: Flask returns 403.
- Action: Stop each launcher with `Ctrl+C` on Unix or by closing its service window on Windows.
  Expected: The processes started by that launcher stop and the ports are released.
