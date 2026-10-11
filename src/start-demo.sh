#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$SCRIPT_DIR/Frontend Demo"

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

cleanup() {
  if [[ -n "${DEMO_PID:-}" ]]; then
    kill "$DEMO_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

(cd "$DEMO_DIR" && pnpm dev --host 127.0.0.1 --port 5174 --strictPort) &
DEMO_PID=$!

echo "GenLedge standalone demo: http://127.0.0.1:5174"
wait "$DEMO_PID"
pause_before_exit
