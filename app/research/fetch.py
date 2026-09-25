"""Fetch public pages. LinkedIn and non-HTTP URLs are refused."""

from datetime import date
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel

from app.domain.models import StructuredFact
from app.research.search import DocumentRecord, is_allowed_public_url


class FetchedPage(BaseModel):
    url: str
    title: str
    text: str
    source_type: str
    published_at: date | None
    status: str
    error: str = ""
    facts: list[StructuredFact] = []


def classify_source_type(url: str) -> str:
    path = urlparse(url).path.lower()
    host = (urlparse(url).hostname or "").lower()
    if host == "github.com" or host.endswith(".github.io"):
        return "public_code"
    if any(part in path for part in ("/career", "/jobs", "/job")):
        return "job_posting"
    if any(part in path for part in ("/blog", "/engineering", "/news")):
        return "blog"
    if any(part in path for part in ("/speaker", "/talk", "/conference")):
        return "conference"
    if any(part in path for part in ("/team", "/leadership", "/about", "/bio")):
        return "biography"
    return "untrusted_web"


@runtime_checkable
class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage:
        """Return extracted text for a public URL."""


class FixtureFetcher:
    def __init__(self, documents: list[DocumentRecord]) -> None:
        self._by_url = {doc.url: doc for doc in documents}

    def fetch(self, url: str) -> FetchedPage:
        if not is_allowed_public_url(url):
            return FetchedPage(
                url=url,
                title="",
                text="",
                source_type="blocked",
                published_at=None,
                status="blocked",
                error="url is not an allowed public http(s) page",
            )
        doc = self._by_url.get(url)
        if doc is None:
            return FetchedPage(
                url=url,
                title="",
                text="",
                source_type="missing",
                published_at=None,
                status="error",
                error="not in fixture corpus",
            )
        published: date | None = date.fromisoformat(doc.published_at) if doc.published_at else None
        return FetchedPage(
            url=doc.url,
            title=doc.title,
            text=doc.text,
            source_type=doc.source_type,
            published_at=published,
            status="ok",
        )


class HttpxPageFetcher:
    """Fetch HTML with httpx and extract text with trafilatura, falling back to BeautifulSoup."""

    def __init__(self, client: object) -> None:
        self._client = client

    def fetch(self, url: str) -> FetchedPage:
        import httpx
        import trafilatura
        from bs4 import BeautifulSoup

        if not is_allowed_public_url(url):
            return FetchedPage(
                url=url,
                title="",
                text="",
                source_type="blocked",
                published_at=None,
                status="blocked",
                error="LinkedIn and non-http URLs are not fetched",
            )
        if not isinstance(self._client, httpx.Client):
            raise TypeError("HttpxPageFetcher requires an httpx.Client")
        try:
            response = self._client.get(
                url,
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "redis-gtm-agent/0.1 (public-page research)"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchedPage(
                url=url,
                title="",
                text="",
                source_type="untrusted_web",
                published_at=None,
                status="error",
                error=str(exc)[:200],
            )
        final = str(response.url)
        if not is_allowed_public_url(final):
            return FetchedPage(
                url=url,
                title="",
                text="",
                source_type="blocked",
                published_at=None,
                status="blocked",
                error="redirected to a blocked host",
            )
        html = response.text[:500_000]
        extracted = trafilatura.extract(html, url=url, include_comments=False) or ""
        metadata = trafilatura.extract_metadata(html)
        title = ""
        published: date | None = None
        if metadata is not None:
            title = str(metadata.title or "")
            raw_date = getattr(metadata, "date", None)
            if isinstance(raw_date, str) and len(raw_date) >= 10:
                try:
                    published = date.fromisoformat(raw_date[:10])
                except ValueError:
                    published = None
        if not title:
            soup = BeautifulSoup(html, "lxml")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        if not extracted:
            soup = BeautifulSoup(html, "lxml")
            extracted = soup.get_text(" ", strip=True)[:8000]
        from app.research.structured import extract_structured

        facts = extract_structured(html, final)
        if facts:
            extracted = (extracted + "\n" + "\n".join(fact.sentence for fact in facts if fact.sentence))[:8000]
        host = urlparse(final).hostname or "web"
        return FetchedPage(
            url=final,
            title=title or host,
            text=extracted,
            source_type=classify_source_type(final),
            published_at=published,
            status="ok" if extracted or facts else "error",
            error="" if extracted or facts else "no text extracted",
            facts=facts,
        )
