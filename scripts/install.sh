#!/usr/bin/env bash
# Idempotent bootstrap. Application state is SQLite. Redis is the GTM product
# under research, not a service this script starts.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data
echo "install.sh: dependencies ready."
