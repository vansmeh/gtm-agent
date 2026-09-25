"""SearchProvider: public web search, SearXNG, and an in-memory mock."""

import re
import time
from typing import Protocol, runtime_checkable
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "and", "for", "with", "that", "this", "from", "into", "are"})


class SearchHit(BaseModel):
    url: str
    title: str
    snippet: str
    published_at: str | None = None
    engine: str = ""
    provider: str = ""
    source: str = ""
    latency_ms: float = 0.0


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

    mode = "MOCK"

    def __init__(self, documents: list[DocumentRecord], *, mode: str = "MOCK") -> None:
        self.documents = documents
        self.mode = mode
        self.endpoint = "fixture://documents"

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
            hits.append(
                SearchHit(
                    url=doc.url,
                    title=doc.title,
                    snippet=doc.text[:240],
                    provider="mock" if self.mode == "MOCK" else "demo",
                    source="fixture",
                )
            )
        return hits


class SearXNGSearchProvider:
    """Local or remote SearXNG JSON API. A localhost shim is not a live provider."""

    endpoint_kind = "searxng"

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
        self.endpoint = self.base_url
        host = urlparse(self.base_url).hostname or ""
        self.mode = "COMPAT" if host in {"localhost", "127.0.0.1"} else "LIVE"

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


class DirectWebSearchProvider:
    """Public web search. This is the live provider. It does not read a fixture corpus."""

    mode = "LIVE"
    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, *, timeout: float = 15.0, budget: int = 12, client: object | None = None) -> None:
        self.timeout = timeout
        self.budget = budget
        self.calls = 0
        self._client = client

    def search(self, query: str, limit: int = 3) -> list[SearchHit]:
        import httpx

        if self.calls >= self.budget:
            return []
        self.calls += 1
        started = time.perf_counter()
        client = self._client if isinstance(self._client, httpx.Client) else httpx.Client(timeout=self.timeout)
        close = self._client is None
        try:
            response = client.post(
                self.endpoint,
                data={"q": query},
                headers={"User-Agent": "redis-gtm-agent/0.1"},
                follow_redirects=True,
            )
            response.raise_for_status()
            hits = parse_duckduckgo_html(response.text, limit=limit)
        finally:
            if close:
                client.close()
        latency = (time.perf_counter() - started) * 1000
        stamped: list[SearchHit] = []
        for hit in hits:
            source = hit.source or "duckduckgo"
            stamped.append(hit.model_copy(update={"provider": "direct-web", "latency_ms": latency, "source": source}))
        return stamped


def parse_duckduckgo_html(html: str, *, limit: int) -> list[SearchHit]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    hits: list[SearchHit] = []
    for node in soup.select("a.result__a"):
        href = node.get("href", "")
        if not isinstance(href, str):
            continue
        if "uddg=" in href:
            href = unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if not is_allowed_public_url(href):
            continue
        snippet = ""
        parent = node.find_parent("div", class_="result")
        if parent is not None:
            snippet_el = parent.select_one(".result__snippet")
            if snippet_el is not None:
                snippet = snippet_el.get_text(" ", strip=True)
        hits.append(
            SearchHit(
                url=href,
                title=node.get_text(" ", strip=True),
                snippet=snippet[:240],
                provider="direct-web",
                source=urlparse(href).hostname or "duckduckgo",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def provider_mode(provider: object) -> str:
    mode = getattr(provider, "mode", "MOCK")
    if mode not in {"LIVE", "MOCK", "DEMO"}:
        return "MOCK"
    return str(mode)


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
                provider="searxng",
                source=str(engine) or (urlparse(url).hostname or ""),
            )
        )
        if len(hits) >= limit:
            break
    return hits
