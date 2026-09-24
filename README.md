# redis-gtm-agent

A minimal FastAPI service that manages GTM (go-to-market) **leads** backed by
**Redis**. It demonstrates a working Python + Redis development environment:
leads are stored in Redis hashes and ranked by an engagement score held in a
Redis sorted set.

## Stack

- Python 3.12
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- [redis-py](https://redis.readthedocs.io/) talking to a local Redis server

## Quick start

```bash
# 1. Install system deps (Redis, python venv) + Python packages
bash scripts/install.sh

# 2. Start Redis (idempotent)
bash scripts/start-redis.sh

# 3. Run the API
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

The API listens on `http://localhost:8000` (interactive docs at `/docs`).

## Configuration

| Env var     | Default                      | Purpose                     |
| ----------- | ---------------------------- | --------------------------- |
| `REDIS_URL` | `redis://localhost:6379/0`   | Redis connection string     |
| `APP_NAME`  | `redis-gtm-agent`            | Service display name        |

## API

| Method | Path                 | Description                                     |
| ------ | -------------------- | ----------------------------------------------- |
| GET    | `/health`            | Liveness + Redis connectivity                   |
| POST   | `/leads`             | Create a lead (`name`, `email`, `company`)      |
| GET    | `/leads`             | List leads, ranked by score (highest first)     |
| GET    | `/leads/{id}`        | Fetch a single lead                             |
| POST   | `/leads/{id}/score`  | Atomically bump a lead's score (`?points=N`)    |

### Example

```bash
curl -s -X POST localhost:8000/leads \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ada Lovelace","email":"ada@analytical.io","company":"AE"}'

curl -s -X POST "localhost:8000/leads/<id>/score?points=5"
curl -s localhost:8000/leads
```

## Tests

```bash
source .venv/bin/activate
python -m pytest -q
```

Tests use Redis DB index `15` and flush it around each test, so they never
touch application data in DB `0`.

## Cloud Agent environment

`.cursor/environment.json` wires this up for Cursor Cloud Agents:

- `install` — installs Redis + Python venv module, creates `.venv`, installs deps
- `start` — starts Redis (idempotent, with a readiness check)
- `terminals` — runs the Uvicorn dev server and tails the Redis log
