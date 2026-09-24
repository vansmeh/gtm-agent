"""Merge repeated public mentions of the same name. Conflicting titles lower confidence."""

from collections import defaultdict


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
