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

## US3 discovery core

From `src/backend`, run the synthetic fixture through discovery:

```bash
.venv/bin/python - <<'PYTHON'
import json
from pathlib import Path
from app.sources.discovery import discover_records
records = json.loads(Path("tests/fixtures/us3/orders.json").read_text())
result = discover_records(records)
print(result.sampled_count)
print({field.path: field.types for field in result.fields})
PYTHON
```

Expected: three sampled records; nested paths such as `shipping_address.city` and `lines[].sku`; `total` has null/number/string types; date and leading-zero identifier values remain strings. No database or API service is used.

For sample-to-sample comparison, run from `src/backend`:

```bash
.venv/bin/python - <<'PYTHON'
import json
from pathlib import Path
from app.sources.discovery import compare_discoveries, discover_records
fixtures = Path("tests/fixtures/us3")
previous = discover_records(json.loads((fixtures / "orders.json").read_text()))
current = discover_records(json.loads((fixtures / "orders-refreshed.json").read_text()))
print(json.dumps(compare_discoveries(previous, current).as_dict(), indent=2))
PYTHON
```

Expected: `added` contains `currency`; `missing` contains `paid`; `typeChanges` reports `total` changing from null/number/string to string. These are sample observations; the comparison does not delete source fields or mappings.

## US3 saved snapshot presentation

Prepare an authorized synthetic snapshot using the publication steps below, configure/migrate the control store, and sign in to the working app with an application user in that same organization.

- Action: Choose Discover from the source screen.
  Expected: The saved snapshot ID form appears with no fabricated source/field data. Load and routing actions are disabled until their required inputs/integration exist.
- Action: Enter a saved snapshot ID and load it.
  Expected: The displayed snapshot ID is the requested saved ID; resources and fields come from GET /api/sources/snapshots/<id>. Sampling count/method are reported as not recorded. Canonical types, native evidence, stored status and prepared samples appear without invented conversions.
- Action: Search LINES and select the number type on the 14-field orders fixture.
  Expected: Only lines[].qty matches. Changing resource/snapshot resets filters; an unmatched query shows a no-match message.
- Action: Load a multi-resource snapshot, select orders.lines[], then load an empty snapshot.
  Expected: The correct resource fields are shown; empty resources show an explicit empty message. Routing stays disconnected.
- Action: Edit the snapshot ID, load an unknown/other-organization ID, or stop only the disposable store and load an authorized ID.
  Expected: Old rows clear immediately; 404 or safe503 messages appear with no SQL/DSN/credential details. Reloading after recovery succeeds.
- Action: Click Reload snapshot after a successful read.
  Expected: GET reads the same immutable ID. No source sampling, write or new snapshot occurs.

The standalone Frontend Demo and isolated DiscoveryPreview remain synthetic; they are not the connected App's live snapshot path.

## US3 shared inventory adapter

From `src/backend`, run a synthetic conversion without Flask startup or a database:

```bash
.venv/bin/python - <<'PYTHON'
import json
from pathlib import Path
from app.sources.discovery import discover_records
from app.sources.inventory_adapter import to_inventory

result = discover_records(json.loads(Path("tests/fixtures/us3/orders.json").read_text()))
inventory = to_inventory(result, snapshot_id="snapshot-orders-1", source_id="source-orders-1",
                         resource_id="orders", resource_name="Orders", resource_kind="collection")
print(inventory.snapshot_id, inventory.resources[0].field_count)
for field in inventory.fields:
    print(field.ref.field_path, field.type.value, field.native_type, field.samples, field.status)
PYTHON
```

Expected: 14 fields in the orders resource; `total` is json with `observed:null|number|string`; `order_date` is text; `customer_code` preserves JSON-quoted leading-zero strings; `lines[].sku` keeps its path and repeating flag. Every status is unknown. No source read, semantic date detection, redaction or snapshot persistence is performed by this adapter.

## US3 date ambiguity

From `src/backend`, inspect the detector and inventory propagation without starting services:

```bash
.venv/bin/python - <<'PYTHON'
from app.sources.date_ambiguity import detect_date_ambiguity
from app.sources.discovery import discover_records
from app.sources.inventory_adapter import to_inventory

for value in ('03/04/2026', '13/04/2026', '04/04/2026', '31/02/2026', '2026-04-03'):
    print(value, detect_date_ambiguity(value))
result = discover_records([{'date': value} for value in
                           ('2026-01-01', '2026-01-02', '2026-01-03', '03/04/2026')])
inventory = to_inventory(result, snapshot_id='dates-1', source_id='source-1',
                         resource_id='dates', resource_name='Dates', resource_kind='collection')
print(result.as_dict())
print(inventory.fields[0].model_dump(mode='json'))
PYTHON
```

Expected: only 03/04/2026 is flagged in the first list. The four-record discovery result carries ambiguity even though its three display samples are the ISO strings. Its type remains string, inventory type remains text, and the same marker appears in InventoryField. No date values are changed.

- Action: Load a saved snapshot published from the orders discovery fixture.
  Expected: order_date displays Date format ambiguous with a confirmation notice; stored canonical type/native evidence are unchanged. The isolated synthetic preview still supports its original initial/refreshed cases.

## US3 snapshot publication

Use a disposable local control database, apply its existing control-plane migration, and create InventoryRepository(Database(explicit_local_dsn)). Do not use a shared/team database for this check. From src/backend, pass the synthetic orders DiscoveryResult to publish_discovery with an explicit preparation callback such as withhold_samples in doc/us3-discovery.md.

- Action: Publish the orders fixture with candidate snapshot ID orders-v1, then read it through InventoryService scoped to the same organization.
  Expected: One resource, 14 fields, preserved canonical paths/types/nullable/repeating/native_type and order_date ambiguity. Samples reflect the explicit policy; withhold_samples saves empty sample lists.
- Action: Publish identical prepared metadata under candidate orders-retry.
  Expected: The returned ID is orders-v1 and only one snapshot exists for this source. Use that returned ID in later calls.
- Action: Publish orders-refreshed.json under orders-v2, then read both IDs.
  Expected: Two immutable snapshots. The old one retains paid; the new one has currency and the changed total type evidence. Neither is deleted or rewritten.
- Action: Read orders-v1 from another process and after restarting only the disposable server.
  Expected: The same stored inventory remains readable with the correct organization scope.
- Action: Attempt a read/save under another organization, reuse orders-v1 for different content, or update a sealed snapshot's field directly.
  Expected: Scoped not-found, source/ID conflict or immutability error; existing saved metadata remains intact.
- Action: Supply a preparation callback that raises before returning an inventory.
  Expected: The error propagates and no source/snapshot is created for that attempt. No silent retry or success response is produced.

No raw-source ingestion, HTTP API, browser wiring, sampling metadata persistence or model call is established by these checks. Remove only the disposable database/cluster after inspection.

## US3 saved snapshot API

- Action: Request a saved snapshot without a valid login, then with a valid login in its organization.
  Expected:401 then200 with contract_version/inventory and Cache-Control:no-store.
- Action: Request an unknown ID and another organization's ID, including a forged organization_id query parameter.
  Expected: Identical404 snapshot_not_found envelopes; identity is taken from the session.
- Action: Sign out and retry the read.
  Expected:401.
- Action: Use a logged-in app without control-store configuration, or stop only its disposable control database.
  Expected: Explicit503 snapshot_not_configured or snapshot_unavailable, no secret-bearing response, and no-store headers. Unexpected failures are not converted into an apparent successful empty inventory.

Keep all manual verification data in a disposable local store. Do not reuse team credentials or alter a shared database for these checks.
