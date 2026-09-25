"""Merge public mentions. A person record requires name, company, title, URL, and excerpt."""

from collections import defaultdict
from datetime import date

from app.person.discovery import Mention

_STALE_DAYS = 540


def merge_identities(
    mentions: list[tuple[str, str, str]],
) -> list[tuple[str, str, list[str], float]]:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, title, url in mentions:
        grouped[name].append((title, url))
    merged: list[tuple[str, str, list[str], float]] = []
    for name, rows in grouped.items():
        titles = [title for title, _url in rows]
        urls = list(dict.fromkeys(url for _title, url in rows))
        unique_titles = list(dict.fromkeys(titles))
        title = unique_titles[0] if unique_titles else ""
        confidence = 0.75 if len(urls) >= 2 and len(unique_titles) == 1 else 0.45
        if len(unique_titles) > 1:
            confidence = 0.3
        merged.append((name, title, urls, confidence))
    return merged


class Identity:
    def __init__(
        self,
        name: str,
        title: str,
        company: str,
        urls: list[str],
        excerpt: str,
        confidence: float,
        contradictions: list[str],
        first_seen: date | None,
        last_seen: date | None,
        role_published_at: date | None,
    ) -> None:
        self.name = name
        self.title = title
        self.company = company
        self.urls = urls
        self.excerpt = excerpt
        self.confidence = confidence
        self.contradictions = contradictions
        self.first_seen = first_seen
        self.last_seen = last_seen
        self.role_published_at = role_published_at


def identities_from_mentions(mentions: list[Mention], company: str, *, observed_on: date) -> list[Identity]:
    grouped: dict[str, list[Mention]] = defaultdict(list)
    for mention in mentions:
        attributed = mention.excerpt.startswith(("Author:", "Speaker:"))
        if not mention.name or not mention.url or not mention.excerpt:
            continue
        if not mention.title and not attributed:
            continue
        grouped[mention.name].append(mention)
    built: list[Identity] = []
    for name, rows in grouped.items():
        titles = list(dict.fromkeys(row.title for row in rows if row.title)) or [""]
        urls = list(dict.fromkeys(row.url for row in rows))
        dates = [row.published_at for row in rows if row.published_at is not None]
        contradictions: list[str] = []
        distinct = list(dict.fromkeys(_norm_title(item) for item in titles))
        if len(distinct) > 1:
            contradictions.append("Conflicting public titles: " + " vs ".join(titles) + ".")
        title = _newest_title(rows) if len(distinct) == 1 else titles[0]
        excerpt = _excerpt_for_title(rows, title)
        confidence = _confidence(urls, distinct, excerpt)
        first_seen = min(dates) if dates else None
        last_seen = max(dates) if dates else None
        role_dates = [row.published_at for row in rows if row.title == title and row.published_at is not None]
        role_published = max(role_dates) if role_dates else last_seen
        if not excerpt or (confidence < 0.45 and not contradictions):
            continue
        built.append(
            Identity(
                name=name,
                title=title,
                company=company,
                urls=urls,
                excerpt=excerpt,
                confidence=confidence,
                contradictions=contradictions,
                first_seen=first_seen,
                last_seen=last_seen,
                role_published_at=role_published,
            )
        )
    del observed_on
    return built


def validity_for(last_seen: date | None, *, observed_on: date) -> str:
    if last_seen is None:
        return "unknown"
    if (observed_on - last_seen).days > _STALE_DAYS:
        return "stale"
    return "current"


def _newest_title(rows: list[Mention]) -> str:
    dated = [row for row in rows if row.published_at is not None]
    if not dated:
        return rows[0].title
    return max(dated, key=lambda row: row.published_at or date.min).title


def _excerpt_for_title(rows: list[Mention], title: str) -> str:
    for row in rows:
        if row.title == title and row.excerpt:
            return row.excerpt
    return rows[0].excerpt if rows else ""


def _norm_title(title: str) -> str:
    words = title.lower().replace(",", " ").split()
    if words and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def _confidence(urls: list[str], titles: list[str], excerpt: str) -> float:
    if len(titles) > 1:
        return 0.3
    if not excerpt:
        return 0.0
    if len(urls) >= 2:
        return 0.8
    return 0.5
