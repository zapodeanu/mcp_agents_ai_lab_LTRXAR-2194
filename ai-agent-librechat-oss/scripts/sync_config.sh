#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${SRC_DIR:-$ROOT_DIR/librechat-src}"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: LibreChat source not found at: $SRC_DIR"
  echo "Run: bash scripts/setup_local.sh"
  exit 1
fi

if [[ ! -f "$LAB_ENV" ]]; then
  echo "ERROR: missing $LAB_ENV"
  echo "Copy the lab root .env.example to $LAB_ENV and configure it first."
  exit 1
fi

umask 077
RUNTIME_ENV="$(mktemp "$SRC_DIR/.env.tmp.XXXXXX")"
trap 'rm -f "$RUNTIME_ENV"' EXIT
awk '
  /^(MONGO_URI|ALLOW_EMAIL_LOGIN|ALLOW_REGISTRATION)=/ ||
  /^(CREDS_KEY|CREDS_IV|JWT_SECRET|JWT_REFRESH_SECRET|MEILI_MASTER_KEY)=/ ||
  /^BEDROCK_/ ||
  /^LITELLM_API_KEY=/ ||
  /^MCP_API_KEY=/ ||
  /^(SPLUNK_MCP_BEARER|SPLUNK_MCP_EP)=/ ||
  /^THOUSANDEYES_API_KEY=/ ||
  /^NODE_EXTRA_CA_CERTS=/ {
    print
  }
' "$LAB_ENV" > "$RUNTIME_ENV"
mv "$RUNTIME_ENV" "$SRC_DIR/.env"
trap - EXIT
cp "$ROOT_DIR/librechat.yaml" "$SRC_DIR/librechat.yaml"
chmod 600 "$SRC_DIR/.env"
echo "Synced the least-privilege LibreChat environment and librechat.yaml into $SRC_DIR"
