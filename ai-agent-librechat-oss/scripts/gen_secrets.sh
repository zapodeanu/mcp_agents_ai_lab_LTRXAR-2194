#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"

if [[ ! -f "$LAB_ENV" ]]; then
  echo "ERROR: missing $LAB_ENV"
  echo "Copy the lab root .env.example to $LAB_ENV before generating secrets."
  exit 1
fi

rand_hex() {
  local n="$1"
  python3 - "$n" <<'PY'
import secrets
import sys
n = int(sys.argv[1])
print(secrets.token_hex(n))
PY
}

set_var_if_empty() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$LAB_ENV"; then
    local current
    current="$(awk -F= -v k="$key" '$1==k{print $2}' "$LAB_ENV" | tail -n1)"
    if [[ -n "${current}" && "${current}" != "replace_with_64_hex_chars" && "${current}" != "replace_with_32_hex_chars" && "${current}" != "replace_with_32_plus_chars" ]]; then
      return
    fi
    # Replace existing line
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' "s|^${key}=.*|${key}=${value}|" "$LAB_ENV"
    else
      sed -i "s|^${key}=.*|${key}=${value}|" "$LAB_ENV"
    fi
  else
    echo "${key}=${value}" >> "$LAB_ENV"
  fi
}

set_var_if_empty "CREDS_KEY" "$(rand_hex 32)"
set_var_if_empty "CREDS_IV" "$(rand_hex 16)"
set_var_if_empty "JWT_SECRET" "$(rand_hex 32)"
set_var_if_empty "JWT_REFRESH_SECRET" "$(rand_hex 32)"
set_var_if_empty "MEILI_MASTER_KEY" "$(rand_hex 24)"

chmod 600 "$LAB_ENV"
echo "Secrets generated/updated in $LAB_ENV"
