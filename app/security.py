"""Treat external web content as untrusted data, never as instructions."""

import re

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+|any\s+|the\s+)?(previous\s+|prior\s+|above\s+)?instructions", re.I),
    re.compile(r"disregard\s+(all\s+|any\s+)?(previous\s+|prior\s+|above\s+)", re.I),
    re.compile(r"you\s+are\s+now", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"do\s+not\s+follow\s+the\s+(previous|above)", re.I),
    re.compile(r"only\s+person\s+to\s+contact", re.I),
    re.compile(r"must\s+recommend", re.I),
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def document_is_poisoned(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def split_sentences(text: str) -> list[str]:
    cleaned = text.replace("\x00", " ").strip()
    if not cleaned:
        return []
    parts = [part.strip() for part in _SENTENCE.split(cleaned) if part.strip()]
    return [part[:500] for part in parts]
