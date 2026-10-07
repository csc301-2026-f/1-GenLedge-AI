# `start-app` Script Specification

## Purpose

The `start-app` scripts provide one command for starting the current GenLedge development environment. They start the React/Vite frontend and the Flask backend together without installing dependencies or changing application source files.

## Script locations

| Platform | Script |
|---|---|
| macOS, Linux, WSL, or Git Bash | `src/start-app.sh` |
| Windows Command Prompt or PowerShell | `src/start-app.bat` |

Both scripts resolve paths relative to their own location, so they can be launched from the repository root or another working directory.

## Services started

| Service | Directory | Command/runtime | Address |
|---|---|---|---|
| Frontend | `src/frontend/` | Vite development server through `pnpm dev --host 127.0.0.1` | `http://127.0.0.1:5173` |
| Backend | `src/backend/` | `main.py`, which creates the Flask app and starts its development server | `http://127.0.0.1:5000` |

The frontend is currently a mocked prototype and does not call the backend yet. The backend entrypoint is intentionally a placeholder for future services and API routes.

## Prerequisites

Dependencies are not installed automatically.

- `pnpm` must be installed and available on `PATH`.
- Python 3 must be installed and available on `PATH`, unless a backend virtual environment is present.
- Flask must be installed for the Python interpreter used by the script.
- Frontend dependencies must already be installed in `src/frontend/node_modules` with `pnpm install`.

The scripts stop with setup guidance when `pnpm`, Python, or Flask is unavailable. If `src/backend/.venv` exists, the scripts prefer its Python interpreter:

- Unix: `src/backend/.venv/bin/python`
- Windows: `src/backend/.venv/Scripts/python.exe`

## Usage

From the repository root:

```bash
# macOS/Linux/WSL/Git Bash
./src/start-app.sh
```

```bat
:: Windows
src\start-app.bat
```

Install dependencies before the first run:

```bash
cd src/frontend
pnpm install

cd ../backend
python -m pip install -r requirements-dev.txt
```

On Windows, use `py -3` instead of `python` when that is the available Python command.

## Process behavior

- The Unix script runs both services as child processes in the same terminal.
- Pressing `Ctrl+C` in the Unix script stops both services.
- The Windows script opens separate command windows for the frontend and backend so each service's logs remain visible.
- Close the two Windows service windows, or press `Ctrl+C` in each, to stop the services.
- Neither script starts PostgreSQL, a worker, AWS Glue, or external data services. Those are future architecture components.

## Output and build separation

Development servers do not produce the deployable frontend bundle. To create the browser-ready build, run:

```bash
cd src/frontend
pnpm build
```

Vite writes the compiled frontend to the repository-level `compiled/` directory. `node_modules/`, cache directories, and `compiled/` are generated artifacts and are ignored by Git.

## Acceptance checks

- Running the platform script from the repository root starts both services using the expected working directories.
- Missing prerequisites produce a clear message and a non-zero exit status.
- The frontend remains usable while the backend is only a placeholder.
- The Flask backend starts on port 5000 and can be replaced with future API/service startup logic through `src/backend/main.py`.
