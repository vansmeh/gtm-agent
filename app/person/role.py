"""Read seniority and a function hint from a public title. The hint is not ownership."""

_SENIORITY: tuple[tuple[str, float], ...] = (
    ("chief", 0.95),
    ("vice president", 0.9),
    ("vp ", 0.9),
    ("vp,", 0.9),
    ("head of", 0.8),
    ("director", 0.75),
    ("principal", 0.6),
    ("staff", 0.55),
)


def seniority_from_title(title: str) -> float:
    lowered = title.lower()
    for needle, score in _SENIORITY:
        if needle in lowered or lowered.startswith(needle.strip()):
            return score
    if title:
        return 0.35
    return 0.1


def function_guess_from_title(title: str) -> str | None:
    lowered = title.lower()
    if "platform" in lowered:
        return "platform_engineering"
    if "ml infrastructure" in lowered or "machine learning" in lowered:
        return "ml_infrastructure"
    if lowered.startswith("vp") or "vice president" in lowered:
        return "engineering_leadership"
    return None
