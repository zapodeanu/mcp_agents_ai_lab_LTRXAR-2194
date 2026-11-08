#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="$ROOT_DIR/.backend.pid"
BACKEND_PORT="${BACKEND_PORT:-3081}"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "Stopping Network AI Hub backend (PID $PID)..."
    kill "$PID" || true
  fi
  rm -f "$PID_FILE"
fi

# Clean up a listener left by an older launcher that recorded the log-filter
# PID instead of the Node backend PID. Only processes owned by this user are
# eligible.
while IFS= read -r listener_pid; do
  [[ -n "$listener_pid" ]] || continue
  owner="$(ps -o user= -p "$listener_pid" 2>/dev/null | tr -d '[:space:]')"
  if [[ "$owner" == "$(id -un)" ]]; then
    echo "Stopping orphaned backend listener (PID $listener_pid)..."
    kill "$listener_pid" >/dev/null 2>&1 || true
  fi
done < <(lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN 2>/dev/null || true)

if [[ -f "$ROOT_DIR/nginx/local.conf" ]]; then
  nginx -s quit -p "$ROOT_DIR/" \
    -c "$ROOT_DIR/nginx/local.conf" >/dev/null 2>&1 || true
fi
echo "Stop signal sent."
