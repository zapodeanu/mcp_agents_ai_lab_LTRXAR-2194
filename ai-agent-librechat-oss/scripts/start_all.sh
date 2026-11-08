#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"

if [[ ! -f "$LAB_ENV" ]]; then
  echo "ERROR: missing $LAB_ENV"
  echo "Copy the lab root .env.example to $LAB_ENV and configure it first."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required for MongoDB connectivity checks."
  exit 1
fi

mongo_check() {
  local host="$1"
  local port="$2"
  python3 - "$host" "$port" <<'PY'
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
}

MONGO_URI_VALUE="$(awk -F= '/^MONGO_URI=/{print $2}' "$LAB_ENV" | tail -n1)"
MONGO_HOST="127.0.0.1"
MONGO_PORT="27017"
IS_LOCAL_MONGO=false

if [[ "$MONGO_URI_VALUE" =~ ^mongodb://(127\.0\.0\.1|localhost):([0-9]+) ]]; then
  MONGO_HOST="${BASH_REMATCH[1]}"
  MONGO_PORT="${BASH_REMATCH[2]}"
  IS_LOCAL_MONGO=true
elif [[ "$MONGO_URI_VALUE" =~ ^mongodb:// ]]; then
  echo "Using remote MongoDB from MONGO_URI; local service start skipped."
else
  echo "MONGO_URI not set or not standard mongodb:// form; defaulting to local 127.0.0.1:27017."
  IS_LOCAL_MONGO=true
fi

if [[ "$IS_LOCAL_MONGO" == true ]]; then
  if mongo_check "$MONGO_HOST" "$MONGO_PORT"; then
    echo "MongoDB already reachable at ${MONGO_HOST}:${MONGO_PORT}."
  else
    echo "MongoDB not reachable at ${MONGO_HOST}:${MONGO_PORT}. Attempting to start it..."
    if command -v systemctl >/dev/null 2>&1 && \
       systemctl list-unit-files mongod.service >/dev/null 2>&1; then
      sudo -n systemctl start mongod >/dev/null 2>&1 || true
    elif command -v brew >/dev/null 2>&1; then
      brew services start mongodb/brew/mongodb-community@8.0 >/dev/null 2>&1 || \
      brew services start mongodb-community@8.0 >/dev/null 2>&1 || \
      brew services start mongodb-community >/dev/null 2>&1 || true
    fi

    ATTEMPTS=20
    for ((i=1; i<=ATTEMPTS; i++)); do
      if mongo_check "$MONGO_HOST" "$MONGO_PORT"; then
        echo "MongoDB is up."
        break
      fi
      sleep 1
      if [[ $i -eq $ATTEMPTS ]]; then
        echo "ERROR: MongoDB is still not reachable at ${MONGO_HOST}:${MONGO_PORT}."
        echo "Start it manually and retry. Example:"
        if command -v systemctl >/dev/null 2>&1; then
          echo "  sudo systemctl start mongod"
        else
          echo "  brew services start mongodb/brew/mongodb-community@8.0"
        fi
        exit 1
      fi
    done
  fi
fi

exec env LAB_ENV="$LAB_ENV" bash "$ROOT_DIR/scripts/start_suite_ssl.sh"
