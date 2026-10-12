# US2 — Upload parsing and validation

This slice validates files without writing to an intake database. The Sources
upload modal calls the real backend and shows collection counts and header
corrections. The source list and database connection flow remain prototypes.
Validation does not advance discovery, create a source, or retain uploaded data.

## Run without any database

From `src/backend`, install `requirements-dev.txt` into your Python environment.
Then run:

```powershell
python -m app.sources.connectors.files C:\path\to\orders.csv
python -m pytest tests/test_file_validation.py -q
```

This checkout also has an ignored local virtual environment installed for testing.
From the repository root, try the included synthetic sample in PowerShell:

```powershell
Set-Location src/backend
.\.venv\Scripts\python.exe -m app.sources.connectors.files tests/fixtures/orders.csv
```

Expected: `status: validated`, `persisted: false`, one `orders` collection and
`rowCount: 2`. For the web flow, start the app using the existing launchers, sign
in, select Upload File, choose this sample, and click Validate File.

The command prints a JSON validation summary and exits with code 1 on invalid
input. Neither the parser nor the web API needs a database on this branch.
The web API uses main's existing demo login (`username` and `password`), which
stores a user in the signed session cookie. This is prototype authentication,
not production credential validation or organization authorization. No imports
from the unfinished `feature-login` branch are required.

## Code walkthrough

1. `connectors/files.py:parse_file(filename, stream)` bounds the file read and
   chooses a parser by extension. Text is decoded as UTF-8 with optional BOM.
2. Table parsers normalize headers and validate each data row. Document parsers
   preserve objects and arrays. A failure anywhere raises `FileValidationError`;
   callers never receive a partially validated workbook.
3. The result is a `ParsedFile` with `ParsedCollection` objects containing full
   records. A future import service can pass these to an intake writer after
   parsing returns successfully. Do not use the summary as the import payload.
4. `routes.py` checks the demo session, verifies its upload-specific CSRF token,
   and returns `summary()`. Its session check is the boundary to update when the
   shared authentication helper lands; no parser changes should be necessary.
5. `UploadFileModal.tsx` displays validation progress, errors, counts and corrections.
   It does not navigate or add a fake saved source on success.

## API

`POST /api/sources/uploads/validate`

- Signed-in demo session and `X-CSRF-Token` from
  `GET /api/sources/uploads/csrf` required. The token endpoint also requires a
  signed-in session. Both endpoints return `Cache-Control: no-store`.
- Tokens are stored under `sources_csrf_token` in the session; existing login
  and logout clear the session, invalidating the token for subsequent requests.
- Multipart form with exactly one file in the `file` field.
- Do not set the multipart Content-Type manually in browser fetch; FormData
  provides the boundary.
- Response is not cached. Full records and credentials are not returned.

Example 200 response (abbreviated):

```json
{
  "status": "validated",
  "persisted": false,
  "filename": "orders.csv",
  "format": "csv",
  "sizeBytes": 20,
  "collections": [{
    "name": "orders",
    "key": "orders_1c168adb00d208e4",
    "rowCount": 1,
    "headers": [{"column": 1, "original": "id", "key": "id"}],
    "warnings": []
  }]
}
```

Errors contain `error` text and, for parser failures, a machine-readable `code`.
Statuses: 400 malformed request; 401 signed out; 403 invalid CSRF; 413 too large;
415 unsupported format; 422 invalid file. Requests without a signed-in session
return 401 before CSRF validation.

## Parsing rules and current decisions

- 25 MB means 25,000,000 bytes, inclusive; request framing gets an extra 1 MB.
- 50,000 records per collection, inclusive, across all six formats. Worksheet
  headers and blank rows do not count. This extends the worksheet rule to text
  and document formats until the team agrees on different limits.
- CSV/TSV: first nonempty row is the header. Fields stay strings (including leading
  zeros); quoted delimiters/newlines work. Ragged rows fail. Blank rows are ignored.
- Blank headings become `column_N`; whitespace is trimmed. Duplicate headings get
  suffixes without stealing another original heading: `name,name,name_2` becomes
  `name,name_3,name_2`. Original headings, column positions and corrections remain
  in metadata. These are parser keys, not a finalized mapping identity contract.
- XLSX/XLS: each worksheet becomes a collection, including hidden sheets. Empty
  sheets fail; header-only sheets are valid with zero records. Missing trailing
  cells become null; dates/times become ISO strings. XLSX formulas and Excel error
  cells fail with instructions to paste values. XLS uses stored formula results
  exposed by xlrd; neither parser evaluates formulas. Password-protected/corrupt
  workbooks fail. XLSX archive contents are limited to 100 MB expanded.
- JSON: one object or an array of objects. NDJSON: one object per nonblank line.
  Empty document datasets fail. Nested structures and MongoDB Extended JSON
  objects (such as `$oid`) are preserved as JSON, not interpreted as BSON.
  Duplicate object keys, non-standard numbers, and numeric overflow fail.
- Collection keys combine a safe slug and stable name hash, preventing collisions
  when different names normalize to the same slug. The future intake layer must
  also scope physical names by organization, source and batch.
- UTF-8 is required for text formats. There is no type inference or flattening.
- The implementation holds validated records in memory; it is a bounded-file MVP,
  not a streaming ingestion worker. Larger-scale ingestion needs its own resource
  budgets. Deeply nested documents that exceed the parser's recursion limit fail.

Excel parsing follows [openpyxl read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html)
and the [xlrd workbook API](https://xlrd.readthedocs.io/en/latest/api.html).

## Deferred until intake storage is ready

Source/batch persistence, organization-scoped filename replacement, atomic
snapshot publication and cleanup, mapping preservation, and reading connected
MongoDB/DocumentDB sources in place. This slice alone does not complete US2.
