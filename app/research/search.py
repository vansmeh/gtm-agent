"""SearchProvider: SearXNG-compatible HTTP search and an in-memory mock."""

import re
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "and", "for", "with", "that", "this", "from", "into", "are"})


class SearchHit(BaseModel):
    url: str
    title: str
    snippet: str
    published_at: str | None = None
    engine: str = ""


@runtime_checkable
class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 3) -> list[SearchHit]:
        """Return public search hits. Snippets are not evidence."""


def is_allowed_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return False
    return True


def _tokens(text: str) -> set[str]:
    return {tok for tok in _TOKEN.findall(text.lower()) if len(tok) > 2 and tok not in _STOP}


class DocumentRecord(BaseModel):
    url: str
    title: str
    source_type: str
    published_at: str | None
    text: str


class MockSearchProvider:
    """Keyword overlap over a fixture corpus. Used for tests and the synthetic demo."""

    def __init__(self, documents: list[DocumentRecord]) -> None:
        self.documents = documents

    def search(self, query: str, limit: int = 3) -> list[SearchHit]:
        needed = _tokens(query)
        scored: list[tuple[int, DocumentRecord]] = []
        for doc in self.documents:
            if not is_allowed_public_url(doc.url):
                continue
            overlap = len(needed & _tokens(f"{doc.title} {doc.text}"))
            if overlap:
                scored.append((overlap, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits: list[SearchHit] = []
        for _score, doc in scored[:limit]:
            hits.append(SearchHit(url=doc.url, title=doc.title, snippet=doc.text[:240]))
        return hits


class SearXNGSearchProvider:
    """Local or remote SearXNG JSON API. No API key. LinkedIn results are dropped."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 8.0,
        retries: int = 2,
        budget: int = 12,
        transport: object | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.budget = budget
        self.calls = 0
        self._categories = ("general", "it", "science")
        self._transport = transport

    def search(self, query: str, limit: int = 3) -> list[SearchHit]:
        import asyncio

        return asyncio.run(self.search_async(query, limit=limit))

    async def search_async(self, query: str, limit: int = 3) -> list[SearchHit]:

        import httpx

        if self.calls >= self.budget:
            return []
        self.calls += 1
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:  # type: ignore[arg-type]
            payload = await self._fetch_json(client, query)
        return normalize_searxng_results(payload, limit=limit)

    async def _fetch_json(self, client: object, query: str) -> dict[str, object]:
        import asyncio

        import httpx

        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("async search requires httpx.AsyncClient")
        last_error = ""
        for attempt in range(self.retries + 1):
            try:
                category = self._categories[(self.calls - 1) % len(self._categories)]
                response = await client.get(
                    f"{self.base_url}/search",
                    params={"q": query, "format": "json", "categories": category},
                )
                if response.status_code >= 500:
                    last_error = f"status {response.status_code}"
                else:
                    response.raise_for_status()
                    body = response.json()
                    if isinstance(body, dict):
                        return body
                    return {}
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last_error = str(exc)[:160]
            if attempt < self.retries:
                await asyncio.sleep(0.2 * (attempt + 1))
        return {"results": [], "error": last_error}


def normalize_searxng_results(payload: dict[str, object], *, limit: int) -> list[SearchHit]:
    raw = payload.get("results", [])
    if not isinstance(raw, list):
        return []
    hits: list[SearchHit] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        if not is_allowed_public_url(url):
            continue
        published = item.get("publishedDate") or item.get("pubdate") or item.get("published_date")
        engine = item.get("engine") or item.get("engines") or ""
        if isinstance(engine, list):
            engine = ",".join(str(part) for part in engine)
        hits.append(
            SearchHit(
                url=url,
                title=str(item.get("title", "")),
                snippet=str(item.get("content", ""))[:240],
                published_at=published[:10] if isinstance(published, str) and len(published) >= 10 else None,
                engine=str(engine),
            )
        )
        if len(hits) >= limit:
            break
    return hits
