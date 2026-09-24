#!/usr/bin/env bash
# Idempotent repository bootstrap for the Cloud Agent environment.
# Creates a virtualenv and installs pinned Python dependencies.
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure durable system dependencies are installed: Redis server and the
# Python venv module (not bundled with the base python3 on Debian/Ubuntu).
NEEDED_PKGS=()
command -v redis-server >/dev/null 2>&1 || NEEDED_PKGS+=(redis-server)
python3 -c "import ensurepip" >/dev/null 2>&1 || NEEDED_PKGS+=(python3-venv)
if [ "${#NEEDED_PKGS[@]}" -gt 0 ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq "${NEEDED_PKGS[@]}"
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

echo "install.sh: dependencies ready."
