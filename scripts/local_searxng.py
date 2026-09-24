#!/usr/bin/env python3
"""SearXNG-compatible JSON endpoint for local demos.

The application talks only to the SearXNG JSON API. This process implements that
API and fills it from public DuckDuckGo HTML when a SearXNG server is not running.
It does not scrape LinkedIn.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


def search_public(query: str) -> list[dict[str, str]]:
    response = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": "redis-gtm-agent/0.1"},
        timeout=15.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    hits: list[dict[str, str]] = []
    for node in soup.select("a.result__a"):
        href = node.get("href", "")
        if not isinstance(href, str):
            continue
        if "uddg=" in href:
            href = unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        host = (urlparse(href).hostname or "").lower()
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            continue
        if not href.startswith("http"):
            continue
        snippet_node = node.find_parent("div", class_="result")
        snippet = ""
        if snippet_node is not None:
            snippet_el = snippet_node.select_one(".result__snippet")
            if snippet_el is not None:
                snippet = snippet_el.get_text(" ", strip=True)
        hits.append({"url": href, "title": node.get_text(" ", strip=True), "content": snippet})
        if len(hits) >= 8:
            break
    return hits


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        import json

        parsed = urlparse(self.path)
        if parsed.path != "/search":
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query).get("q", [""])[0]
        try:
            results = search_public(query)
            body = json.dumps({"query": query, "results": results}).encode()
            status = 200
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"query": query, "results": [], "error": str(exc)[:200]}).encode()
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"local-searxng {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    print("local searxng-compatible search on http://127.0.0.1:8080")
    server.serve_forever()
