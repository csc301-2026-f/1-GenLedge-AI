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
