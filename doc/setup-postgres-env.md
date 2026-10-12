# Developer PostgreSQL setup

This guide connects the Flask backend to each developer's own PostgreSQL
database. Use the shared `integration` role and `dev` database only for shared
integration testing. Never use the PostgreSQL `postgres` administrator account
from the application.

## 1. Account mapping

Use the role and database assigned to you by the database owner:

| Developer role | Database |
| --- | --- |
| `daniel` | `daniel` |
| `likunyu2` | `likunyu2` |
| `jeff06` | `jeff06` |
| `lvlvhu` | `lvlvhu` |
| `steven` | `steven` |
| `xiran` | `xiran` |
| `integration` | `dev` (shared integration only) |

PostgreSQL credentials are separate from the application login created by
`auth-create-user`. Receive only your own database password through the team's
approved private channel or password manager.

## 2. Create the private environment file

From the repository root:

```powershell
Copy-Item src/backend/.env.example src/backend/.env
```

On macOS/Linux:

```bash
cp src/backend/.env.example src/backend/.env
chmod 600 src/backend/.env
```

Edit `src/backend/.env` and replace the placeholders:

```dotenv
HOST=301db.dbestserv.com
PORT=5432
DATABASE=YOUR_DATABASE_NAME
USER=YOUR_DATABASE_USER
PASSWORD=YOUR_DATABASE_PASSWORD
SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET
APP_ENV=development
DB_SSLMODE=require
# DB_SSLROOTCERT=C:/path/to/server.crt
```

Use your assigned role and database. Put the database password in `PASSWORD`;
the backend safely constructs the PostgreSQL connection from these fields. Keep
`.env` private; it is ignored by Git. The committed `.env.example` contains
placeholders only.

`DB_SSLMODE` accepts `require`, `verify-ca`, or `verify-full`. Start with
`require` while the team is validating the public certificate. For `verify-ca`
or `verify-full`, set `DB_SSLROOTCERT` to the trusted certificate file path.
`require` encrypts the connection but does not verify the server identity.
The backend reads `.env` for both Flask CLI commands and the existing app
launchers; a variable already set in the process takes precedence.

The database owner reports that public access is now available. The older
database deployment guide records an earlier failed public connection and an
unresolved remote administrator login check. Treat the endpoint as
owner-reported until your own `auth-db-check` succeeds with your developer role;
ask the owner to resolve server access issues rather than changing server
configuration from this checkout.

## 3. Install and check the connection

Create the backend environment and install dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src/backend/requirements-dev.txt
```

Run the read-only connection check from the repository root:

```powershell
cd src/backend
..\..\.venv\Scripts\python.exe -m flask --app main auth-db-check
```

Expected output identifies your role, database, and TLS state. It never prints
the database password. If the check fails, verify DNS/network access, the role
password, the database name, and the selected `DB_SSLMODE`.

On macOS/Linux, from `src/backend`, use the same Python interpreter and run
`python3 -m flask --app main auth-db-check`, then the commands below with
`python3 -m flask --app main`.

## 4. Initialize your database

On a fresh developer database, apply the initial migration:

```powershell
..\..\.venv\Scripts\python.exe -m flask --app main auth-init-db
```

The migration creates `auth_organizations`, `auth_users`, and `auth_sessions`.
It also records the schema revision. If an existing database already contains
these tables, the command stops and asks for schema review; do not delete those
tables to force the migration.

Create a local application login for testing:

```powershell
..\..\.venv\Scripts\python.exe -m flask --app main auth-create-user --email you@example.com --organization YourOrganization --role Analyst
```

The command prompts for the application password and stores only its hash.

For the optional PostgreSQL integration check, set the `HOST`, `PORT`,
`DATABASE`, `USER`, and `PASSWORD` settings for your developer-owned database
in the test process and run `python -m pytest
tests/test_postgres_integration.py` from `src/backend`. The test creates a
uniquely named disposable schema, exercises migration and login, and removes
that schema. Set `TEST_FORBIDDEN_DATABASE` to another developer's database to
also verify that your role cannot connect to it. Never point this test at the
shared `integration/dev` database.

## 5. Run the app

The existing launchers load `src/backend/.env` and apply all pending checked-in
database migrations before starting Flask. This creates the schema in a fresh
database and upgrades a database that is already at an earlier migration
revision. Before doing that, they print a redacted status summary containing the
environment, database type, remote host and port, configured role, database,
SSL mode, actual connected role/database, and TLS state. They pause for your
confirmation. Passwords and full connection URLs are never printed. If the
connection check or migration fails, neither service starts.

```powershell
src\start-app.bat
```

or on macOS/Linux:

```bash
./src/start-app.sh
```

Open `http://127.0.0.1:5173`, then sign in with the application account created
above. The PostgreSQL role is used by Flask to store application data; it is not
the email/password used in the browser.

Schema changes must be added as reviewed Alembic migration files and committed
with the code change. The launcher applies those migrations on the next start;
it does not generate migrations from model differences or delete existing data.

## 6. Shared integration testing

Use `integration` with database `dev` only when a test requires shared data or
coordination across branches. Do not use it for personal feature experiments,
because another developer may change or remove those records.

## Common errors

- **Placeholder error:** replace every `YOUR_` and `REPLACE_WITH_` value in
  `.env`.
- **Password authentication failed:** confirm the assigned role and password.
- **Database does not exist:** use the database paired with your role; ask the
  database owner to provision it rather than using `postgres`.
- **Certificate verification failed:** keep `DB_SSLMODE=require` temporarily,
  or install the trusted certificate and set `DB_SSLROOTCERT` before using
  `verify-ca` or `verify-full`.
- **Migration stops on existing tables:** stop and have the schema reviewed;
  never drop another developer's database.
- **Migration fails on startup:** read the Flask migration error, fix the
  connection or migration issue, and restart the launcher. The services are
  intentionally not started with an unknown database schema.
