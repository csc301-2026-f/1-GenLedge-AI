# Smoke Tests

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
