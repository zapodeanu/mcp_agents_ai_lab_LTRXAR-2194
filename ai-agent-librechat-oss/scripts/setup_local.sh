#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${SRC_DIR:-$ROOT_DIR/librechat-src}"
LIBRECHAT_REPO="${LIBRECHAT_REPO:-https://github.com/danny-avila/LibreChat.git}"
LIBRECHAT_REF="${LIBRECHAT_REF:-8d3da9bbb220a0a96be9330a2e1cbd385fb786d5}"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
REQUIRED_NODE_VERSION="v24.22.1"
REQUIRED_NPM_VERSION="11.13.0"

if [[ -s "$NVM_DIR/nvm.sh" ]]; then
  # shellcheck disable=SC1090
  . "$NVM_DIR/nvm.sh"
  nvm use "${REQUIRED_NODE_VERSION#v}" >/dev/null
fi

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required."
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node is required for LibreChat."
  echo "Install Node.js $REQUIRED_NODE_VERSION with nvm."
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required for LibreChat."
  exit 1
fi
if [[ "$(node --version)" != "$REQUIRED_NODE_VERSION" ]]; then
  echo "ERROR: LibreChat requires Node.js $REQUIRED_NODE_VERSION; found $(node --version)."
  echo "Use nvm install 24.22.1 && nvm use 24.22.1"
  exit 1
fi
if [[ "$(npm --version)" != "$REQUIRED_NPM_VERSION" ]]; then
  echo "ERROR: LibreChat requires npm $REQUIRED_NPM_VERSION; found $(npm --version)."
  echo "Run: npm install -g npm@$REQUIRED_NPM_VERSION"
  exit 1
fi

if [[ ! -f "$LAB_ENV" ]]; then
  echo "ERROR: missing $LAB_ENV"
  echo "Copy the lab root .env.example to $LAB_ENV and configure it first."
  exit 1
fi

if [[ ! -d "$SRC_DIR/.git" ]]; then
  echo "Cloning LibreChat into $SRC_DIR ..."
  git clone "$LIBRECHAT_REPO" "$SRC_DIR"
fi

cd "$SRC_DIR"
git fetch --all --tags
git checkout "$LIBRECHAT_REF"
if git symbolic-ref --quiet HEAD >/dev/null; then
  git pull --ff-only
fi

cd "$ROOT_DIR"
LAB_ENV="$LAB_ENV" bash "$ROOT_DIR/scripts/gen_secrets.sh"
LAB_ENV="$LAB_ENV" bash "$ROOT_DIR/scripts/sync_config.sh"

cd "$SRC_DIR"
echo "Installing dependencies and building LibreChat..."
npm run reinstall

UI_PATCH="$ROOT_DIR/patches/compact-mcp-selector.patch"
UI_OVERRIDE="$ROOT_DIR/overrides/client/src/components/Chat/Input/Composer/CompactMCPSelect.tsx"
UI_TARGET="$SRC_DIR/client/src/components/Chat/Input/Composer/CompactMCPSelect.tsx"

if git apply --reverse --check "$UI_PATCH" >/dev/null 2>&1; then
  echo "Compact MCP selector patch already applied."
else
  git apply --check "$UI_PATCH"
  git apply "$UI_PATCH"
fi
cp "$UI_OVERRIDE" "$UI_TARGET"
npm run build:client

echo ""
echo "Setup complete."
echo "Start the complete lab from the repository root with: make up"
