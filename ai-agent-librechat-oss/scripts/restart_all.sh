#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Restarting Network AI Hub stack..."
bash "$ROOT_DIR/scripts/stop_suite.sh"
sleep 1
exec bash "$ROOT_DIR/scripts/start_all.sh"
