import httpx
from app.research.fetch import HttpxPageFetcher
from app.research.search import SearXNGSearchProvider
from app.sheets.provider import MockSheetsProvider, build_sheets_provider


def test_searxng_filters_linkedin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://www.linkedin.com/in/x", "title": "skip", "content": "no"},
                    {"url": "https://acme.example/post", "title": "Post", "content": "public"},
                ]
            },
        )

    hits = SearXNGSearchProvider("http://searx.local", transport=httpx.MockTransport(handler)).search("acme", limit=5)
    assert [hit.url for hit in hits] == ["https://acme.example/post"]


def test_http_fetcher_extracts_text() -> None:
    html = "<html><head><title>Acme</title></head><body><p>Acme launched search.</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    page = HttpxPageFetcher(httpx.Client(transport=httpx.MockTransport(handler))).fetch("https://acme.example/p")
    assert page.status == "ok"
    assert "Acme" in page.title or "search" in page.text


def test_http_fetcher_blocks_linkedin() -> None:
    page = HttpxPageFetcher(httpx.Client()).fetch("https://www.linkedin.com/in/someone")
    assert page.status == "blocked"


def test_sheets_factory_defaults_to_mock() -> None:
    provider = build_sheets_provider(provider="google", spreadsheet_id=None, credentials_file=None)
    assert isinstance(provider, MockSheetsProvider)
    provider.ensure_tabs()
    provider.append("OUTCOMES", {"action_id": "a", "result": "pending", "notes": "", "ranking_updated": "false"})
    assert provider.read("OUTCOMES")[0]["result"] == "pending"
