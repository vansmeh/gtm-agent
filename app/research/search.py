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
    """SearXNG JSON API. Results pointing at LinkedIn are dropped."""

    def __init__(self, base_url: str, client: object) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client

    def search(self, query: str, limit: int = 3) -> list[SearchHit]:
        import httpx

        if not isinstance(self._client, httpx.Client):
            raise TypeError("SearXNGSearchProvider requires an httpx.Client")
        response = self._client.get(
            f"{self.base_url}/search",
            params={"q": query, "format": "json"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        hits: list[SearchHit] = []
        results = payload.get("results", [])
        if not isinstance(results, list):
            return hits
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            if not is_allowed_public_url(url):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title", "")),
                    snippet=str(item.get("content", ""))[:240],
                )
            )
            if len(hits) >= limit:
                break
        return hits
