# Smoke Tests

## Development launchers

- Action: Run `./src/start-demo.sh` or `src\start-demo.bat` and open `http://127.0.0.1:5174`.
  Expected: The preserved standalone mock demo loads without requiring a Flask process.
- Action: Run `./src/start-app.sh` or `src\start-app.bat` and open `http://127.0.0.1:5173`.
  Expected: The connected frontend loads, Flask is available at port 5000, and `/api/auth` requests reach Flask through Vite.
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

## US3 discovery presentation

- Action: Open the working app, sign in and choose Discover from the source screen.
  Expected: Discovery is labelled Synthetic preview, with source Synthetic orders fixture and collection orders. The initial result reports three sampled records and 14 fields; `total` displays null/number/string and `customer_code` retains quoted leading-zero strings.
- Action: Search `LINES` and choose the number type filter. Clear filters before the next step.
  Expected: Search is case-insensitive; `lines[].qty` matches the type filter; no-match queries show an explicit empty-filter message.
- Action: Click Re-sample or select Refreshed sample.
  Expected: `currency` is added, `paid` is missing from the sample, and `total` changes to string. The notice explains missing is not confirmed deletion. Added and Type changed filters show the matching current fields.
- Action: Use the labelled preview selector to choose Empty sample, Loading, then Error.
  Expected: Empty fields, loading status and explicit error are shown separately. Routing is disabled in all three states; Re-sample is disabled during loading and returns to the refreshed fixture from error/empty.
- Action: Advance from a nonempty sample.
  Expected: The existing mock routing screen opens. Discovery does not make an HTTP request, persist data, or supply live records to routing.
