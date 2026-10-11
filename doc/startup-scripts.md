# Startup Scripts Implementation Plan

This change separates the preserved standalone mock demo from the current
Flask-backed frontend workflow.

## Completed

- Added `src/start-demo.sh` and `src/start-demo.bat` for the standalone demo on
  port 5174.
- Kept `src/start-app.sh` and `src/start-app.bat` for the connected frontend on
  port 5173 and Flask on port 5000.
- Added the Vite `/api` proxy required by the connected frontend.
- Updated `doc/start-app-scripts-spec.md` with both workflows and their checks.

## Verification

- Shell syntax, backend tests, frontend type checks, and the connected frontend
  build passed.
- The demo launcher served port 5174 without Flask.
- The full-stack launcher served ports 5173 and 5000, and login, session
  restore, logout, and signed-out session checks passed through the Vite proxy.
