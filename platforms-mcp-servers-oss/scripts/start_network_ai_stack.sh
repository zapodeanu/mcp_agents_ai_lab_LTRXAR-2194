#!/usr/bin/env bash
set -euo pipefail

# Launch sequence:
# 1) Stop existing MCP remote servers
# 2) Start the Catalyst Center and Meraki Magic remote FastMCP servers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORMS_DIR_DEFAULT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT_DEFAULT="$(cd "$PLATFORMS_DIR_DEFAULT/.." && pwd)"
MERAKI_MAGIC_DIR_DEFAULT="$REPO_ROOT_DEFAULT/meraki-magic-mcp-community"

LAB_ENV="${LAB_ENV:-$HOME/lab.env}"
if [[ ! -f "$LAB_ENV" ]]; then
  echo "ERROR: Required environment file not found: $LAB_ENV"
  exit 1
fi

PLATFORMS_DIR="${PLATFORMS_DIR:-$PLATFORMS_DIR_DEFAULT}"
MERAKI_MAGIC_DIR="${MERAKI_MAGIC_DIR:-$MERAKI_MAGIC_DIR_DEFAULT}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT_DEFAULT/.venv/bin/python}"
MCP_ENABLE_TLS="${MCP_ENABLE_TLS:-true}"
MCP_SSL_CERTFILE="${MCP_SSL_CERTFILE:-$REPO_ROOT_DEFAULT/certs/mcp-selfsigned.crt}"
MCP_SSL_KEYFILE="${MCP_SSL_KEYFILE:-$REPO_ROOT_DEFAULT/certs/mcp-selfsigned.key}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_CATALYST_PORT="${MCP_CATALYST_PORT:-8000}"
MCP_MERAKI_PORT="${MCP_MERAKI_PORT:-8001}"
MCP_MERAKI_MAGIC_PORT="${MCP_MERAKI_MAGIC_PORT:-8002}"
CATALYST_PID_FILE="$REPO_ROOT_DEFAULT/logs/catalyst_center_mcp.pid"
MERAKI_MAGIC_PID_FILE="$REPO_ROOT_DEFAULT/logs/meraki_magic_mcp.pid"

if [[ ! -d "$PLATFORMS_DIR" ]]; then
  echo "ERROR: PLATFORMS_DIR not found: $PLATFORMS_DIR"
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python executable not found: $PYTHON_BIN"
  exit 1
fi
if [[ ! -f "$MERAKI_MAGIC_DIR/meraki_magic_remote.py" ]]; then
  echo "ERROR: Meraki Magic entry point not found: $MERAKI_MAGIC_DIR/meraki_magic_remote.py"
  exit 1
fi

stop_owned_process() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}

echo "============================================================"
echo "Starting MCP remote servers at $(date)"
echo "============================================================"

echo "[0/1] Stopping existing MCP servers..."
stop_owned_process "$CATALYST_PID_FILE"
stop_owned_process "$MERAKI_MAGIC_PID_FILE"
sleep 1
for port in "$MCP_CATALYST_PORT" "$MCP_MERAKI_MAGIC_PORT"; do
  if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ERROR: Port $port is already used by a process not owned by this lab."
    exit 1
  fi
done

echo "[1/1] Starting remote MCP servers..."
mkdir -p "$REPO_ROOT_DEFAULT/logs"
# TLS for MCP remotes is enabled by default (POC): generate self-signed cert if needed.
MCP_TLS_ARGS=()
if [[ "$MCP_ENABLE_TLS" == "true" ]]; then
  mkdir -p "$(dirname "$MCP_SSL_CERTFILE")"
  if [[ -f "$MCP_SSL_CERTFILE" && -f "$MCP_SSL_KEYFILE" ]] && \
     ! openssl x509 -in "$MCP_SSL_CERTFILE" -noout -checkend 86400 >/dev/null 2>&1; then
    echo "  - Existing MCP TLS certificate is invalid or expires within 24 hours; regenerating it."
    rm -f "$MCP_SSL_CERTFILE" "$MCP_SSL_KEYFILE"
  fi
  if [[ ! -f "$MCP_SSL_CERTFILE" || ! -f "$MCP_SSL_KEYFILE" ]]; then
    rm -f "$MCP_SSL_CERTFILE" "$MCP_SSL_KEYFILE"
    openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
      -keyout "$MCP_SSL_KEYFILE" \
      -out "$MCP_SSL_CERTFILE" \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
  fi
  chmod 600 "$MCP_SSL_KEYFILE"
  MCP_TLS_ARGS=(--ssl-certfile "$MCP_SSL_CERTFILE" --ssl-keyfile "$MCP_SSL_KEYFILE")
  echo "  - MCP TLS enabled with cert: $MCP_SSL_CERTFILE"
fi

# Remote wrappers already write structured logs to:
#   $REPO_ROOT_DEFAULT/logs/catalyst_center_mcp.log
#   $REPO_ROOT_DEFAULT/logs/meraki_magic_mcp.log
nohup "$PYTHON_BIN" "$PLATFORMS_DIR/catalyst_center_remote.py" --host "$MCP_HOST" --port "$MCP_CATALYST_PORT" \
  "${MCP_TLS_ARGS[@]}" \
  >/dev/null 2>&1 &
CATALYST_PID=$!

nohup "$PYTHON_BIN" "$MERAKI_MAGIC_DIR/meraki_magic_remote.py" --host "$MCP_HOST" --port "$MCP_MERAKI_MAGIC_PORT" \
  "${MCP_TLS_ARGS[@]}" \
  >"$REPO_ROOT_DEFAULT/logs/meraki_magic_mcp.log" 2>&1 &
MERAKI_MAGIC_PID=$!
printf '%s\n' "$CATALYST_PID" >"$CATALYST_PID_FILE"
printf '%s\n' "$MERAKI_MAGIC_PID" >"$MERAKI_MAGIC_PID_FILE"

echo "  - catalyst_center_remote PID: $CATALYST_PID"
echo "  - meraki_magic_remote PID: $MERAKI_MAGIC_PID"

echo "Waiting 5 seconds..."
sleep 5

if [[ "$MCP_ENABLE_TLS" == "true" ]]; then
  curl -k -fsS "https://127.0.0.1:${MCP_CATALYST_PORT}/health" >/dev/null || {
    echo "ERROR: Catalyst did not pass HTTPS health check"
    exit 1
  }
  curl -k -fsS "https://127.0.0.1:${MCP_MERAKI_MAGIC_PORT}/health" >/dev/null || {
    echo "ERROR: Meraki Magic did not pass HTTPS health check"
    exit 1
  }
else
  curl -fsS "http://127.0.0.1:${MCP_CATALYST_PORT}/health" >/dev/null || {
    echo "ERROR: Catalyst did not pass HTTP health check"
    exit 1
  }
  curl -fsS "http://127.0.0.1:${MCP_MERAKI_MAGIC_PORT}/health" >/dev/null || {
    echo "ERROR: Meraki Magic did not pass HTTP health check"
    exit 1
  }
fi

echo "============================================================"
echo "MCP startup launched in background."
echo "============================================================"

