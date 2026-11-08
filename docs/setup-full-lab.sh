#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAB_ENV="${LAB_ENV:-$HOME/lab.env}"
NVM_VERSION="v0.40.8"
NODE_VERSION="24.22.1"
NPM_VERSION="11.13.0"

if [[ ! -f /etc/os-release ]]; then
  echo "ERROR: This installer requires Ubuntu 22.04 or 24.04."
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "ERROR: This installer supports Ubuntu only."
  echo "Detected: ${PRETTY_NAME:-unknown operating system}"
  exit 1
fi

case "${VERSION_ID:-}" in
  22.04)
    MONGODB_UBUNTU_CODENAME="jammy"
    ;;
  24.04)
    MONGODB_UBUNTU_CODENAME="noble"
    ;;
  *)
    echo "ERROR: This installer supports Ubuntu 22.04 and 24.04 only."
    echo "Detected: ${PRETTY_NAME:-unknown operating system}"
    exit 1
    ;;
esac

echo "[1/8] Installing Ubuntu packages..."
sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  gnupg \
  less \
  lsof \
  make \
  nginx \
  openssl \
  pipx \
  python3-pip \
  python3-venv

echo "[2/8] Installing MongoDB Community 8.0..."
if [[ ! -f /usr/share/keyrings/mongodb-server-8.0.gpg ]]; then
  curl -fsSL https://pgp.mongodb.com/server-8.0.asc | \
    sudo gpg --batch --yes \
      -o /usr/share/keyrings/mongodb-server-8.0.gpg \
      --dearmor
fi

echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${MONGODB_UBUNTU_CODENAME}/mongodb-org/8.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list >/dev/null

sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl enable --now mongod

echo "[3/8] Installing nvm, Node.js, and npm..."
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  NVM_INSTALLER="$(mktemp)"
  trap 'rm -f "$NVM_INSTALLER"' EXIT
  curl -fsSL \
    "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" \
    -o "$NVM_INSTALLER"
  PROFILE="$HOME/.bashrc" bash "$NVM_INSTALLER"
  rm -f "$NVM_INSTALLER"
  trap - EXIT
fi

# shellcheck disable=SC1090
. "$NVM_DIR/nvm.sh"
nvm install "$NODE_VERSION"
nvm alias default "$NODE_VERSION"
nvm use "$NODE_VERSION"
npm install -g "npm@$NPM_VERSION"

echo "[4/8] Installing Python 3.13 with uv..."
pipx ensurepath
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  pipx install uv
fi
uv python install 3.13

echo "[5/8] Creating the shared Python environment..."
cd "$LAB_ROOT"
if [[ ! -s "$LAB_ROOT/requirements.lock" ]]; then
  echo "ERROR: Dependency lock not found: $LAB_ROOT/requirements.lock"
  exit 1
fi
if [[ ! -x "$LAB_ROOT/.venv/bin/python3" ]] || \
  ! "$LAB_ROOT/.venv/bin/python3" -c \
    'import sys; raise SystemExit(sys.version_info[:2] != (3, 13))'; then
  uv venv --python 3.13 --seed --clear .venv
fi
# shellcheck disable=SC1091
source "$LAB_ROOT/.venv/bin/activate"
uv pip install \
  --python "$LAB_ROOT/.venv/bin/python" \
  -r "$LAB_ROOT/requirements.lock"
python3 -m pip check

echo "[6/8] Preparing the private lab environment..."
if [[ ! -f "$LAB_ENV" ]]; then
  cp "$LAB_ROOT/.env.example" "$LAB_ENV"
  echo "Created $LAB_ENV from the safe template."
fi
chmod 600 "$LAB_ENV"
LAB_ENV="$LAB_ENV" bash "$LAB_ROOT/ai-agent-librechat-oss/scripts/gen_secrets.sh"

echo "[7/8] Validating required lab settings..."
cd "$LAB_ROOT"
LAB_ENV="$LAB_ENV" python3 scripts/validate_lab_env.py

echo "[8/8] Installing LibreChat..."
cd "$LAB_ROOT/ai-agent-librechat-oss"
LAB_ENV="$LAB_ENV" bash scripts/setup_local.sh

echo ""
echo "Full lab installation complete."
echo "Start complete lab: cd \"$LAB_ROOT\" && make up"
echo "Check status:       cd \"$LAB_ROOT\" && make status"
echo "Stop complete lab:  cd \"$LAB_ROOT\" && make down"
