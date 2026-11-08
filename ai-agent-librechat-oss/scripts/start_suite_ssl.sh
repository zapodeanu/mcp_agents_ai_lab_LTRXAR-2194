#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
REQUIRED_NODE_VERSION="v24.22.1"
REQUIRED_NPM_VERSION="11.13.0"
SRC_DIR="${SRC_DIR:-$ROOT_DIR/librechat-src}"
cd "$ROOT_DIR"

APP_LOGGER_NAME="${APP_LOGGER_NAME:-ai_agent_librechat_launcher}"
_BANNER_LINE="================================================================================"
LIBRECHAT_LOG_FILE="${LIBRECHAT_LOG_FILE:-$ROOT_DIR/logs/ai_agent_librechat.log}"
APP_LOG_FORMAT="${APP_LOG_FORMAT:-${MCP_LOG_FORMAT:-%(asctime)s - PID:%(process)d - %(name)s - %(levelname)s - %(message)s}}"

if [[ -s "$NVM_DIR/nvm.sh" ]]; then
  # shellcheck disable=SC1090
  . "$NVM_DIR/nvm.sh"
  nvm use "${REQUIRED_NODE_VERSION#v}" >/dev/null
fi

timestamp_now() {
  python3 - <<'PY'
from datetime import datetime
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3])
PY
}

log_info() {
  local message="$1"
  printf "%s - PID:%s - %s - INFO - %s\n" "$(timestamp_now)" "$$" "$APP_LOGGER_NAME" "$message"
}

log_block() {
  local text="$1"
  while IFS= read -r line; do
    [[ -n "$line" ]] && log_info "$line"
  done <<< "$text"
}

if ! command -v nginx >/dev/null 2>&1; then
  log_info "ERROR: nginx is not installed."
  log_info "Install nginx with your operating system's package manager."
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  log_info "ERROR: Node.js + npm are required."
  exit 1
fi
if [[ "$(node --version)" != "$REQUIRED_NODE_VERSION" || "$(npm --version)" != "$REQUIRED_NPM_VERSION" ]]; then
  log_info "ERROR: LibreChat requires Node.js $REQUIRED_NODE_VERSION and npm $REQUIRED_NPM_VERSION."
  log_info "Found Node.js $(node --version) and npm $(npm --version)."
  exit 1
fi
if [[ ! -d "$SRC_DIR" ]]; then
  log_info "ERROR: LibreChat source not found at $SRC_DIR"
  log_info "Run: bash scripts/setup_local.sh"
  exit 1
fi
if [[ ! -f "$LAB_ENV" ]]; then
  log_info "ERROR: missing $LAB_ENV"
  log_info "Copy the lab root .env.example to $LAB_ENV and configure it first."
  exit 1
fi

NODE_EXTRA_CA_CERTS_VALUE="$(awk -F= '/^NODE_EXTRA_CA_CERTS=/{sub(/^[^=]*=/,""); print; exit}' "$LAB_ENV" | sed 's/^"//; s/"$//')"
NODE_EXTRA_CA_CERTS_VALUE="${NODE_EXTRA_CA_CERTS_VALUE:-$LAB_ROOT/certs/mcp-selfsigned.crt}"
if [[ -n "${NODE_EXTRA_CA_CERTS_VALUE:-}" ]]; then
  if [[ -f "$NODE_EXTRA_CA_CERTS_VALUE" ]]; then
    export NODE_EXTRA_CA_CERTS="$NODE_EXTRA_CA_CERTS_VALUE"
    log_info "Using NODE_EXTRA_CA_CERTS from $LAB_ENV"
  else
    log_info "WARN: NODE_EXTRA_CA_CERTS path does not exist: $NODE_EXTRA_CA_CERTS_VALUE"
  fi
fi

BACKEND_PORT="${BACKEND_PORT:-3081}"
HTTPS_PROXY_PORT="${HTTPS_PROXY_PORT:-3080}"
CERT_DIR="${CERT_DIR:-$LAB_ROOT/certs}"
CERT_KEY="${CERT_KEY:-$CERT_DIR/mcp-selfsigned.key}"
CERT_CRT="${CERT_CRT:-$CERT_DIR/mcp-selfsigned.crt}"
NGINX_TEMPLATE="$ROOT_DIR/nginx/local.conf.template"
NGINX_CONF="$ROOT_DIR/nginx/local.conf"
NGINX_MIME_TYPES="${NGINX_MIME_TYPES:-}"
NGINX_PID_FILE="$ROOT_DIR/nginx/nginx.pid"
NGINX_CLIENT_TEMP_PATH="$ROOT_DIR/nginx/tmp/client"
NGINX_PROXY_TEMP_PATH="$ROOT_DIR/nginx/tmp/proxy"
PID_FILE="$ROOT_DIR/.backend.pid"

port_is_available() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket
import sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

stop_existing_stack() {
  # Stop prior nginx instance for this project config.
  nginx -s quit -p "$ROOT_DIR/" -c "$NGINX_CONF" >/dev/null 2>&1 || true

  # Stop only the backend process previously recorded by this project.
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$PID_FILE"
  fi
}

mkdir -p \
  "$ROOT_DIR/logs" \
  "$ROOT_DIR/nginx" \
  "$NGINX_CLIENT_TEMP_PATH" \
  "$NGINX_PROXY_TEMP_PATH" \
  "$CERT_DIR"
if [[ "${LIBRECHAT_LOG_FILE#/}" == "$LIBRECHAT_LOG_FILE" ]]; then
  LIBRECHAT_LOG_FILE="$ROOT_DIR/$LIBRECHAT_LOG_FILE"
fi
mkdir -p "$(dirname "$LIBRECHAT_LOG_FILE")"

MONGO_URI_VALUE="$(awk -F= '/^MONGO_URI=/{print $2}' "$LAB_ENV" | tail -n1)"
if [[ -n "${MONGO_URI_VALUE:-}" ]]; then
  if [[ "$MONGO_URI_VALUE" =~ ^mongodb://(127\.0\.0\.1|localhost):([0-9]+) ]]; then
    MONGO_HOST="${BASH_REMATCH[1]}"
    MONGO_PORT="${BASH_REMATCH[2]}"
    if ! python3 - "$MONGO_HOST" "$MONGO_PORT" <<'PY'
import socket
import sys
host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2.0)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
    then
      log_info "ERROR: MongoDB is not reachable at ${MONGO_HOST}:${MONGO_PORT}"
      log_info "Start MongoDB first, then retry."
      exit 1
    fi
  fi
fi

if [[ -z "$NGINX_MIME_TYPES" ]]; then
  for candidate in \
    "/opt/homebrew/etc/nginx/mime.types" \
    "/usr/local/etc/nginx/mime.types" \
    "/etc/nginx/mime.types"; do
    if [[ -f "$candidate" ]]; then
      NGINX_MIME_TYPES="$candidate"
      break
    fi
  done
fi
if [[ -z "$NGINX_MIME_TYPES" ]]; then
  log_info "ERROR: Could not locate nginx mime.types."
  log_info "Set NGINX_MIME_TYPES explicitly and rerun."
  exit 1
fi

if [[ -f "$CERT_KEY" && -f "$CERT_CRT" ]] && \
   ! openssl x509 -in "$CERT_CRT" -noout -checkend 86400 >/dev/null 2>&1; then
  log_info "Existing local TLS certificate is invalid or expires within 24 hours; regenerating it."
  rm -f "$CERT_KEY" "$CERT_CRT"
fi

if [[ ! -f "$CERT_KEY" || ! -f "$CERT_CRT" ]]; then
  log_info "Generating self-signed local TLS certificate..."
  rm -f "$CERT_KEY" "$CERT_CRT"
  openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout "$CERT_KEY" \
    -out "$CERT_CRT" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi
chmod 600 "$CERT_KEY"

if [[ "${CERT_KEY#/}" == "$CERT_KEY" ]]; then
  CERT_KEY="$ROOT_DIR/$CERT_KEY"
fi
if [[ "${CERT_CRT#/}" == "$CERT_CRT" ]]; then
  CERT_CRT="$ROOT_DIR/$CERT_CRT"
fi

esc() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

sed \
  -e "s/__BACKEND_PORT__/$BACKEND_PORT/g" \
  -e "s/__HTTPS_PROXY_PORT__/$HTTPS_PROXY_PORT/g" \
  -e "s/__CERT_KEY__/$(esc "$CERT_KEY")/g" \
  -e "s/__CERT_CRT__/$(esc "$CERT_CRT")/g" \
  -e "s/__NGINX_MIME_TYPES__/$(esc "$NGINX_MIME_TYPES")/g" \
  -e "s/__NGINX_PID_FILE__/$(esc "$NGINX_PID_FILE")/g" \
  -e "s/__NGINX_CLIENT_TEMP_PATH__/$(esc "$NGINX_CLIENT_TEMP_PATH")/g" \
  -e "s/__NGINX_PROXY_TEMP_PATH__/$(esc "$NGINX_PROXY_TEMP_PATH")/g" \
  -e "s/__APP_LOG_FILE__/$(esc "$LIBRECHAT_LOG_FILE")/g" \
  "$NGINX_TEMPLATE" > "$NGINX_CONF"

# Auto-restart behavior: if configured ports are occupied, stop prior stack
# and start fresh instead of failing with bind errors.
if ! port_is_available "$BACKEND_PORT" || ! port_is_available "$HTTPS_PROXY_PORT"; then
  log_info "Existing listener detected. Attempting automatic restart cleanup..."
  stop_existing_stack
  sleep 1
fi

if ! port_is_available "$BACKEND_PORT"; then
  log_info "ERROR: backend port $BACKEND_PORT is already in use."
  log_info "Try: BACKEND_PORT=3181 bash scripts/start_suite_ssl.sh"
  exit 1
fi
if ! port_is_available "$HTTPS_PROXY_PORT"; then
  log_info "ERROR: nginx HTTPS proxy port $HTTPS_PROXY_PORT is already in use."
  log_info "Try: HTTPS_PROXY_PORT=3443 bash scripts/start_suite_ssl.sh"
  exit 1
fi

# Keep readiness checks scoped to this launch instead of matching stale output
# from a previous LibreChat process.
: > "$LIBRECHAT_LOG_FILE"
chmod 600 "$LIBRECHAT_LOG_FILE"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${BACKEND_PIPELINE_PID:-}" ]]; then
    kill "$BACKEND_PIPELINE_PID" >/dev/null 2>&1 || true
  fi
  nginx -s quit -p "$ROOT_DIR/" -c "$NGINX_CONF" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! SYNC_OUTPUT="$(LAB_ENV="$LAB_ENV" bash "$ROOT_DIR/scripts/sync_config.sh" 2>&1)"; then
  log_block "$SYNC_OUTPUT"
  log_info "ERROR: sync_config.sh failed."
  exit 1
fi
log_block "$SYNC_OUTPUT"

log_info "$_BANNER_LINE"
log_info "AI Agent LibreChat Started (nginx + backend)"
log_info "Process ID: $$"
log_info "Starting LibreChat backend on 127.0.0.1:${BACKEND_PORT} ..."
cd "$SRC_DIR"
NO_COLOR=1 FORCE_COLOR=0 NODE_DISABLE_COLORS=1 npm_config_color=false \
PORT="$BACKEND_PORT" HOST=127.0.0.1 npm run --silent backend 2>&1 \
  | stdbuf -oL awk '
      {
        gsub(/\x1B\[[0-9;?]*[ -\/]*[@-~]/, "");

        if (skip_json_block) {
          opens = gsub(/\{/, "&");
          closes = gsub(/\}/, "&");
          brace_depth += opens - closes;
          if (brace_depth <= 0) {
            skip_json_block = 0;
            brace_depth = 0;
          }
          next;
        }

        if ($0 ~ /info:[[:space:]]+Mongo Connection options[[:space:]]*$/) {
          print "info: Mongo Connection options [omitted JSON]";
          skip_json_block = 1;
          brace_depth = 0;
          next;
        }

        if ($0 ~ /info:[[:space:]]+Custom config file loaded:[[:space:]]*$/) {
          print "info: Custom config file loaded [omitted JSON]";
          skip_json_block = 1;
          brace_depth = 0;
          next;
        }

        if ($0 ~ /RAG API is either not running or not reachable at .*you may experience errors with file uploads\./) {
          next;
        }

        print;
      }
    ' >> "$LIBRECHAT_LOG_FILE" &
BACKEND_PIPELINE_PID=$!
BACKEND_PID=""

for _attempt in {1..60}; do
  if ! kill -0 "$BACKEND_PIPELINE_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PIPELINE_PID" || true
    log_info "ERROR: LibreChat backend exited before opening port $BACKEND_PORT."
    exit 1
  fi
  BACKEND_PID="$(
    lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN 2>/dev/null |
      awk 'NR == 1 { print; exit }' || true
  )"
  if [[ -n "$BACKEND_PID" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$BACKEND_PID" ]]; then
  log_info "ERROR: LibreChat backend did not open port $BACKEND_PORT within 60 seconds."
  exit 1
fi

echo "$BACKEND_PID" > "$PID_FILE"

log_info "Starting nginx TLS proxy..."
log_info "HTTPS proxy: https://localhost:${HTTPS_PROXY_PORT} -> backend:${BACKEND_PORT}"
log_info "$_BANNER_LINE"
nginx -p "$ROOT_DIR/" -c "$NGINX_CONF"

log_info "Ready: https://localhost:${HTTPS_PROXY_PORT}"
log_info "Press Ctrl+C to stop."

while true; do
  if ! kill -0 "$BACKEND_PIPELINE_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PIPELINE_PID" || true
    break
  fi
  sleep 1
done
