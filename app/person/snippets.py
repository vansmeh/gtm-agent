"""Turn a public search snippet into an unverified candidate. Snippets are not identity."""

from app.person.discovery import Mention, _names_in
from app.research.search import SearchHit


def candidates_from_hits(hits: list[SearchHit], account_name: str, query: str) -> list[Mention]:
    """A snippet can name someone only when the name, company, and role are all explicit."""
    account = account_name.strip().lower()
    found: list[Mention] = []
    seen: set[tuple[str, str, str]] = set()
    for hit in hits:
        text = f"{hit.title}. {hit.snippet}"
        if account not in text.lower():
            continue
        for name, title in _names_in(text):
            key = (name, title, hit.url)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Mention(
                    name=name,
                    title=title,
                    url=hit.url,
                    excerpt=" ".join(text.split())[:500],
                    published_at=None,
                )
            )
    del query
    return found
