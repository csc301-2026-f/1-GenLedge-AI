# Development Launcher Specification

## Purpose

The repository provides separate cross-platform launchers for the preserved
standalone demo and the Flask-backed frontend. They start local development
servers without installing dependencies or changing application source files.

## Script locations

| Workflow | macOS/Linux/WSL/Git Bash | Windows Command Prompt/PowerShell |
|---|---|---|
| Standalone demo | `src/start-demo.sh` | `src/start-demo.bat` |
| Full stack | `src/start-app.sh` | `src/start-app.bat` |

All scripts resolve paths relative to their own location, so they can be run
from the repository root or another working directory.

## Workflows and services

### Standalone demo

The demo launcher starts only the preserved mock UI in `src/Frontend Demo/`.
It does not require Python, Flask, a database, or an API service.

| Service | Directory | Command | Address |
|---|---|---|---|
| Standalone demo | `src/Frontend Demo/` | `pnpm dev --host 127.0.0.1 --port 5174 --strictPort` | `http://127.0.0.1:5174` |

### Full stack

The full-stack launcher starts the current `backend-1` frontend and its Flask
backend. The frontend's Vite development server proxies `/api` requests to
Flask, so browser authentication uses the local backend.

| Service | Directory | Command | Address |
|---|---|---|---|
| Connected frontend | `src/frontend/` | `pnpm dev --host 127.0.0.1 --port 5173 --strictPort` | `http://127.0.0.1:5173` |
| Flask backend | `src/backend/` | `main.py` | `http://127.0.0.1:5000` |

The current backend uses demo authentication: any non-empty username and
password are accepted. The later `feature-login` integration will replace this
with database-backed authentication, password hashing, and credential
verification.

## Prerequisites

Dependencies are not installed automatically.

- `pnpm` must be installed and available on `PATH`.
- For the full-stack launcher, Python 3 must be installed and available on
  `PATH`, unless `src/backend/.venv` exists.
- For the full-stack launcher, Flask must be installed for the selected Python
  interpreter.
- Frontend dependencies must already be installed in each frontend's
  `node_modules` directory with `pnpm install`.

The full-stack scripts prefer the backend virtual environment when present:

- Unix: `src/backend/.venv/bin/python`
- Windows: `src/backend/.venv/Scripts/python.exe`

The demo scripts stop with setup guidance when `pnpm` is unavailable. The
full-stack scripts also validate Python and Flask and show the dependency
installation command when either is unavailable.

## Usage

From the repository root:

```bash
# macOS/Linux/WSL/Git Bash: standalone demo
./src/start-demo.sh

# macOS/Linux/WSL/Git Bash: full stack
./src/start-app.sh
```

```bat
:: Windows: standalone demo
src\start-demo.bat

:: Windows: full stack
src\start-app.bat
```

Install dependencies before the first run:

```bash
cd src/frontend
pnpm install

cd ../"Frontend Demo"
pnpm install

cd ../backend
python -m pip install -r requirements-dev.txt
```

On Windows, use `py -3` instead of `python` when that is the available Python
command.

## Process behavior

- The Unix scripts run their service processes in the same terminal.
- Pressing `Ctrl+C` in a Unix launcher stops the process or processes started by
  that launcher.
- The Windows scripts open service command windows so each service's logs stay
  visible.
- Close the Windows service window, or press `Ctrl+C` in it, to stop that
  service.
- Neither launcher starts PostgreSQL, a worker, AWS Glue, or other external
  data services.

## Output and build separation

Development servers do not produce the deployable frontend bundle. To build the
connected frontend, run:

```bash
cd src/frontend
pnpm build
```

Vite writes the compiled frontend to the repository-level `compiled/`
directory. `node_modules/`, cache directories, and `compiled/` are generated
artifacts and are ignored by Git.

## Acceptance checks

- The demo launcher starts the standalone UI at port 5174 without Python.
- The full-stack launcher starts the connected frontend at port 5173 and Flask
  at port 5000.
- The full-stack frontend can reach `/api/auth` through the Vite proxy.
- Missing prerequisites produce a clear message and a non-zero exit status.
- The demo and full-stack launchers can run at the same time because they use
  different frontend ports.
