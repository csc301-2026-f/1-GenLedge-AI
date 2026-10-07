#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
BACKEND_DIR="$SCRIPT_DIR/backend"

pause_before_exit() {
  if [[ -t 0 ]]; then
    printf '\nPress any key to exit...'
    IFS= read -r -n 1 -s
    printf '\n'
  fi
}

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required. Install Node.js and pnpm, then run this script again." >&2
  pause_before_exit
  exit 1
fi

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "Python is required. Install Python 3, then run this script again." >&2
  pause_before_exit
  exit 1
fi

if ! "$PYTHON" -c 'import flask' >/dev/null 2>&1; then
  echo "Flask is not installed for $PYTHON." >&2
  echo "Install it with: $PYTHON -m pip install -r \"$BACKEND_DIR/requirements-dev.txt\"" >&2
  pause_before_exit
  exit 1
fi

cleanup() {
  kill "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(cd "$FRONTEND_DIR" && pnpm dev --host 127.0.0.1) &
FRONTEND_PID=$!
(cd "$BACKEND_DIR" && "$PYTHON" main.py) &
BACKEND_PID=$!

echo "Frontend: http://127.0.0.1:5173"
echo "Backend:  http://127.0.0.1:5000"
wait "$FRONTEND_PID" "$BACKEND_PID"
pause_before_exit
