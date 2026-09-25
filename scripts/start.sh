#!/usr/bin/env bash
# Per-boot setup. Creates the SQLite data directory. Does not start Redis.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data
echo "start.sh: sqlite data directory ready. Redis is not the application database."
