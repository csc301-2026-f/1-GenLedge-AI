# Smoke Tests

## US4 source inventory and persistence

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
  Expected: The connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite.
- Action: Stop each launcher with `Ctrl+C` on Unix or by closing its service window on Windows.
  Expected: The processes started by that launcher stop and the ports are released.
