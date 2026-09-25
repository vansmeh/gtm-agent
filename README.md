# Redis GTM Intelligence Agent

Person-centric technical GTM research for a Redis SDR. The person is the unit of action. The account is context.

V1 answers who to consider, why that person, which technical problem is relevant, which public evidence connects them, why now, which Redis use case is plausible, what is unknown, and what to do next. The next step is human review. The agent does not send outreach.

## Stack

- Python 3.12, FastAPI, LangGraph, Pydantic v2, SQLAlchemy 2, SQLite
- httpx, trafilatura, BeautifulSoup
- SearchProvider with a SearXNG client and a mock provider
- Laya decision adapter in shadow mode
- Google Sheets adapter and a mock that runs without credentials

Redis is the product being researched. It is not the application database.

## Run

```bash
bash scripts/install.sh
source .venv/bin/activate
python -m app.demo
uvicorn app.main:app --port 8000
```

`POST /demo/acme-ai` runs the synthetic account. `GET /health` checks SQLite. `POST /actions/{id}/outcomes` stores a human outcome and does not change ranking.

## Checks

```bash
pytest
ruff check app tests
mypy
```
