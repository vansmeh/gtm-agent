#!/usr/bin/env bash
# Idempotent, per-boot Redis startup. Safe to run repeatedly.
set -euo pipefail

DATA_DIR="${REDIS_DATA_DIR:-/tmp/redis}"
mkdir -p "$DATA_DIR"

if redis-cli ping >/dev/null 2>&1; then
  echo "start-redis.sh: Redis already running."
  exit 0
fi

redis-server --daemonize yes --dir "$DATA_DIR" --logfile "$DATA_DIR/redis.log"

# Wait for readiness (up to ~10s).
for _ in $(seq 1 20); do
  if redis-cli ping >/dev/null 2>&1; then
    echo "start-redis.sh: Redis is ready."
    exit 0
  fi
  sleep 0.5
done

echo "start-redis.sh: Redis failed to become ready." >&2
exit 1
