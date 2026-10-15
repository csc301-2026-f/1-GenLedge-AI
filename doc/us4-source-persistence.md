# US4 Person A: source inventory and persistence

This slice implements the PostgreSQL control plane only. It imports boundary
types from `app.agent.contracts` without adding or changing contracts, graph
nodes, model adapters, HTTP routes, UI components, or proposal validation rules.

## Database setup (PowerShell)

Requires Python 3.11+ and PostgreSQL 17. The repository's Compose service can
provide PostgreSQL when Docker is installed. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src/backend/requirements-dev.txt

$env:POSTGRES_PASSWORD = '<choose-a-local-password>'
docker compose -f database/compose.yaml up -d postgres
docker compose -f database/compose.yaml exec postgres createdb -U postgres genledge
docker compose -f database/compose.yaml exec postgres createdb -U postgres genledge_test

$env:PGPASSWORD = $env:POSTGRES_PASSWORD
$env:GENLEDGE_DATABASE_URL = 'host=127.0.0.1 port=5432 dbname=genledge user=postgres'
$env:GENLEDGE_TEST_DATABASE_URL = 'host=127.0.0.1 port=5432 dbname=genledge_test user=postgres'
Set-Location src/backend
python -m app.common.migrations
python -m app.sources.fixtures
```

Wait until PostgreSQL is healthy before creating databases. If these databases
already exist, omit the two `createdb` commands. If PostgreSQL is already installed,
use your local host, port, database, and role instead of starting Compose.
`GENLEDGE_DATABASE_URL` accepts a psycopg connection string or PostgreSQL URI.
`PGPASSWORD` keeps the password outside the DSN. Do not commit environment secrets.

The default schema is `genledge_control`; override it with
`GENLEDGE_DATABASE_SCHEMA`. The migration identity is `001_us4_control_plane`.
`python -m alembic upgrade head` is an equivalent command from `src/backend`.
Migration execution is transactional and serialized by a PostgreSQL advisory lock;
running it repeatedly is safe. The role needs schema/table/function creation
privileges during migration. The baseline is forward-only: preserve data with
backups and use new Alembic revisions for later changes rather than editing the
applied baseline. There is no automatic destructive downgrade.

## Test commands

With the virtual environment active and local test DSN set, from `src/backend`:

```powershell
python -m pytest tests
python -m pytest tests/test_source_persistence.py tests/test_mapping_persistence.py -v
python -m scripts.smoke_persistence
python -m scripts.smoke_persistence
```

The full suite covers inventory round-trip, sample limits at both contract and SQL
boundaries, snapshot immutability through direct SQL, concurrent snapshot/job/tool
replay, immutable revisions, findings, coverage, catalogue scope, edit audit,
transaction rollback, Alembic repeatability, and a separate Python process reading
persisted records and replaying a committed tool call.

Integration tests create unique `test_us4_*` schemas and drop only those schemas
after each test. They require local PostgreSQL and never use the application DSN
or a shared team host. Without `GENLEDGE_TEST_DATABASE_URL`, database tests are
explicitly skipped; skips do not verify persistence. An unavailable configured
test server causes failures rather than silent skips. Test roles need permission
to create and drop their isolated schemas.

The smoke command writes deterministic synthetic records to the application
schema. Both runs report three resources and 18 fields and the same job ID and
revision. The first run normally reports `created=True`, `tool_replayed=False`,
and `factory_calls=1`; the second reports `created=False`, `tool_replayed=True`,
and `factory_calls=0`. Both report the persisted `reject` decision. It makes no
model or connector calls and leaves its records available for inspection.

## Public interfaces

| File | Interface | Result |
| --- | --- | --- |
| `app/common/database.py` | `Database(dsn=None, schema=None)` | Configurable transaction factory; no Flask dependency |
| `app/common/migrations.py` | `migrate(database=None)` | Upgrade through Alembic to head |
| `app/sources/fixtures.py` | `demo_inventory()` / `seed_demo(repository)` | Typed synthetic inventory / idempotently persisted snapshot |
| `app/sources/repository.py` | `save_snapshot(inventory, source_id=..., organization_id=..., source_name=...)` | Published `InventoryView`; deduplicated by source and fingerprint |
| `app/sources/service.py` | `get_inventory(snapshot_id) -> InventoryView` | Trusted worker read using environment configuration |
| `app/sources/service.py` | `InventoryService(repository, organization_id=...).get_inventory(snapshot_id)` | Organization-scoped read for application services |
| `app/mappings/repository.py` | `MappingRepository(database, organization_id=...)` | Organization-scoped job, package, catalogue, and edit adapter |
| `app/mappings/tool_repository.py` | `ToolResultRepository(database, organization_id=...)` | Durable evidence and replay adapter |

Inventory example, from a Python shell started in `src/backend`:

```python
from app.common.database import Database
from app.sources.fixtures import DEMO_SNAPSHOT_ID, demo_inventory, seed_demo
from app.sources.repository import InventoryRepository
from app.sources.service import get_inventory

inventory = get_inventory(DEMO_SNAPSHOT_ID)
assert inventory == demo_inventory()
print([resource.name for resource in inventory.resources])
print(next(field for field in inventory.fields if field.ref.field_path == 'order_date'))
assert all(len(field.samples) <= 3 for field in inventory.fields)
assert seed_demo(InventoryRepository(Database())).snapshot_id == inventory.snapshot_id
```

The resources are `orders`, `orders.lines[]`, and `customers`. The inventory has
descriptions, native types, nullable and repeating flags, stable field references,
bounded synthetic samples, and the deliberately ambiguous date `03/04/2026`.
Email and postal-code samples are withheld. Whole source records and connector
credentials have no inventory columns or contract fields.

Job and tool replay example:

```python
from app.agent.contracts import ToolCallRequest
from app.mappings.repository import MappingRepository
from app.mappings.tool_repository import ToolResultRepository
from app.sources.fixtures import DEMO_ORGANIZATION_ID

database = Database()
jobs = MappingRepository(database, organization_id=DEMO_ORGANIZATION_ID)
arguments = dict(source_snapshot_ids=[inventory.snapshot_id],
                 idempotency_key='manual-example-v1', created_by='local-reviewer',
                 model_mode='fake')
job, created = jobs.create_job(**arguments)
same_job, created_again = jobs.create_job(**arguments)
assert same_job['id'] == job['id'] and not created_again
assert jobs.get_job_by_idempotency_key('manual-example-v1')['id'] == job['id']

tools = ToolResultRepository(database, organization_id=DEMO_ORGANIZATION_ID)
call = ToolCallRequest(id='manual-call-v1', name='profile_resource',
                       arguments={'source_id': 'demo-orders-source', 'resource_id': 'orders.lines[]'})
first = tools.get_or_record(job['id'], call, lambda: ('ok', {'repeating': True}),
                            redacted=True)
def must_not_run():
    raise AssertionError('A committed call was dispatched again')
replay = tools.get_or_record(job['id'], call, must_not_run, redacted=True)
assert replay['ref'].replayed
assert replay['ref'].result_ref == first['ref'].result_ref
assert tools.get_result(replay['ref'].result_ref)['payload'] == {'repeating': True}
```

### Jobs and packages for Person D

`create_job(...) -> (job, created)` returns `created=False` on duplicate submission.
The caller must launch work only when `created=True`. A key is scoped to an
organization; reusing it with different snapshot IDs, creator, catalogue, budgets,
or mode raises `PersistenceConflict`. `get_job(id)` and
`get_job_by_idempotency_key(key)` read durable state. Job dictionaries use `id`,
`source_snapshot_ids`, `catalog_ref`, `status: JobStatus`, `budgets: AgentBudgets`,
and `failure: FailureInfo | None`, plus audit columns. The route owner translates
`id` to its HTTP `job_id`. `update_status(id, status, expected_status=..., failure=...)`
supports a locked compare-and-set; lifecycle policy belongs to the application.

`save_revision(job_id, model_draft, mapping_draft=None, findings=(), coverage=(),
table_is_new=None)` atomically stores a review package. All supplied draft,
finding, and coverage objects are existing shared contracts. Application-computed
table flags are stored separately from the model draft. Identical replay returns
the same package; differing content at the same `(job_id, revision)` conflicts.
`get_revision(job_id, revision=None)` reads the latest numeric revision by default
or a particular historical revision. Its dictionary contains `id`, `job_id`,
`revision`, typed `model_draft`, `mapping_draft`, `findings`, `coverage`,
`table_is_new`, and audit columns. Findings and coverage are revision-scoped;
later revisions do not overwrite earlier records.

`save_edit(job_id, edit_id=..., revision_id=..., reviewer=..., reviewer_role=...,
target=..., decision='accept'|'reject', idempotency_key=...) -> (edit, created)`
records one table decision. Exact retries return the original edit. Conflicting
IDs/keys are rejected, and the revision must belong to that job. `list_edits(job_id,
pending_only=False)` reads the audit; `mark_edit_applied(job_id, edit_id)` sets an
idempotent timestamp. Recording a decision does not mutate or approve a proposal,
change the job status, or apply a model revision. Person D owns orchestration.
Reviewer roles are stored, not authorized, by this repository.

`save_catalogue(id, {'tables': [{'name': 'fact_orders', 'columns': [{'name':
'order_id', 'type': 'text'}]}]})` / `get_catalogue(id)` persist immutable optional
catalogue metadata. No catalogue contract exists in the frozen shared module, so
the adapter accepts only the documented names/types dictionary and defines no
parallel Pydantic contract. Cold start uses `catalog_ref=None`.

### Tools for Person B

`replay(job_id, ToolCallRequest)` returns `None` or `{'ref': ToolResultRef,
'payload': ...}` with `replayed=True`. `get_result(result_ref)` resolves a stored
evidence reference. `save_result(job_id, call, status=..., payload=...,
redacted=True) -> ToolResultRef` stores an already-dispatched result without
overwriting a prior committed result.

Prefer `get_or_record(job_id, call, result_factory, redacted=True)` around the
caller-owned connector read: its transaction-scoped advisory lock serializes
duplicate calls across processes, invokes the factory only on a cache miss, and
stores the returned `('ok'|'error', JSON_payload)` pair. It returns the same
reference/payload shape as `replay`. A repeated call ID with a changed tool name
or arguments conflicts. The same call ID is independent in different jobs.
The factory must apply authorization, tool-specific schema checks, budgets,
timeouts, and redaction before returning. Only caller-attested redacted payloads
are accepted. The repository does not perform those other workstreams' rules.

## Limitations and boundaries

- This is the D2 seeded metadata slice; there are no live source connectors,
  graph checkpoints, approval flow, warehouse execution, or HTTP/UI integration.
- Reads/replay survive process restarts. A crash after an external read but before
  database commit may require repeating that read; this does not promise exactly
  once external execution. Already committed results always replay.
- The global inventory convenience function is for trusted workers. Application
  services should inject organization scope; identity and role authorization remain
  outside persistence.
- Callers must supply already safe inventory samples and redacted tool payloads;
  this slice does not duplicate Person C's redaction rules. It stores no raw fixture
  rows or credentials, and rejects unknown inventory fields through the shared model.
- The tool lock holds a database transaction during the factory call. Person B
  must enforce bounded tool timeouts. Connection pooling and worker recovery are
  deferred.
- Alembic owns schema versioning. The baseline has no destructive downgrade or
  offline SQL mode. Production backup/restore and deployment-role separation are
  not established by these development integration tests.

## Changed files

- `src/backend/requirements.txt`: PostgreSQL and migration dependencies.
- `src/backend/alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`,
  `migrations/001_us4_control_plane.sql`, and
  `migrations/versions/001_us4_control_plane.py`: Alembic configuration and schema.
- `src/backend/app/common/database.py` and `common/migrations.py`: connection and
  migration entrypoints.
- `src/backend/app/sources/fixtures.py`, `sources/repository.py`, and
  `sources/service.py`: synthetic inventory, snapshots, and typed service.
- `src/backend/app/mappings/repository.py` and `mappings/tool_repository.py`:
  scoped job/package/catalogue/edit persistence and tool replay.
- `src/backend/scripts/__init__.py` and `scripts/smoke_persistence.py`: runnable
  verification example.
- `src/backend/tests/conftest.py`, `tests/test_source_persistence.py`, and
  `tests/test_mapping_persistence.py`: isolated PostgreSQL integration coverage.
- `doc/backend-architecture.md`, `docs/smoke-tests.md`, this guide, and
  `doc/us4-person-a-source-persistence-plan.md`: behavior, setup, interfaces,
  limitations, and completed execution plan.
