# US4 persistence function audit and error record

## Scope and environment

Person A public persistence functions, shared serialization helpers, migration
entrypoints, and the smoke command were exercised using Python 3.13.5 and isolated
local PostgreSQL 17.6 schemas. Existing authentication/API/contract tests run as
part of the full backend suite. This audit does not add graph, API, UI, connector,
redaction, or deterministic proposal-validation functionality.

## Baseline before fixes

- Existing suite: **65 passed**.
- Persistence line/branch report: **95% combined coverage** across the original
  seven persistence modules. The smoke module was not imported by tests, which
  coverage reported as a warning; the new suite now invokes it twice.
- New public-function audit: **20 failed, 30 passed** before implementation
  changes. Those failures reproduce the five defects below. This test/error
  record is committed separately before the fixes, as requested.

## Reproduced errors

| ID | Function | Trigger | Observed error | Required behavior |
| --- | --- | --- | --- | --- |
| A1 | `Database.__init__` | Empty, whitespace-only, NUL-containing, non-string, or overlong UTF-8 schema; empty environment schema | Six cases silently accepted, integer raises `AttributeError`, list raises `TypeError` | Reject invalid configuration with `ValueError` before connecting; default only on omitted schema |
| A2 | `MappingRepository.save_catalogue` | Non-dictionary payload, table, or column containers, including lists with the expected key strings | Eight cases raise `TypeError` from `set(...)` or string-key indexing | Reject malformed containers with `ValueError` and persist no catalogue |
| A3 | `ToolResultRepository.replay` / `get_or_record` | Reuse a call ID after changing a nested argument from JSON boolean `true` to number `1` | Both calls incorrectly replay; expected conflict is absent | Treat boolean/number changes as conflicting requests without dispatch |
| A4 | `ToolResultRepository.replay` | Save a valid `ToolCallRequest` whose object-valued arguments contain a tuple; replay the exact same request | Raises `PersistenceConflict` because the database stored its JSON array while comparison uses the original tuple | Compare the same normalized JSON representation used during persistence |
| A5 | `MappingRepository.save_revision` | Change a stored `default_value` operation argument from `True` to `1` at the same revision | Incorrectly accepts the changed content as an identical immutable revision | Raise `PersistenceConflict`; retain the original immutable package |

A1 has eight failing parametrizations, A2 eight, A3 two, and A4/A5 one each.
Python's `True == 1` behavior causes A3 and A5. Dictionary equality recursively
inherits that behavior. The database schema limit must be measured in UTF-8 bytes:
PostgreSQL's default identifier limit is 63 bytes and longer identifiers are
truncated, potentially aliasing distinct configured schema names. See the
[PostgreSQL identifier documentation](https://www.postgresql.org/docs/current/sql-syntax-lexical.html).

The passing audit cases cover every public persistence operation, reserved and
valid schema boundaries, source/organization isolation, bad job/edit arguments,
optional mapping omission, missing records, typed table flags, transaction rollback
after factory failure, nonfinite payload rejection, JSON object-key order,
numeric equivalence, array order, large integers, and two smoke invocations.

## Reproduction

Activate the virtual environment, install `src/backend/requirements-dev.txt`, and
configure `GENLEDGE_TEST_DATABASE_URL` for a disposable local PostgreSQL database.
From `src/backend`:

```powershell
python -m pytest tests/test_persistence_function_audit.py -q --tb=short
python -m pytest tests
```

At the error-record commit, the first command intentionally reports the failures
above. At the subsequent fix commit, those same tests must pass.

Coverage command (set `COVERAGE_FILE` to an ignored scratch path if desired):

```powershell
python -m coverage run --branch --source=app.common.database,app.common.migrations,app.sources.repository,app.sources.service,app.sources.fixtures,app.mappings.repository,app.mappings.tool_repository,scripts.smoke_persistence -m pytest tests
python -m coverage report -m
```

## Final verification

Pending the separate fix commit. Coverage is evidence of exercised branches,
not a proof that every possible input or failure has been tested.
