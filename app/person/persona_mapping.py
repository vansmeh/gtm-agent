"""Map a title onto an approved playbook persona. Unmapped stays unmapped."""

from app.playbook.selection import Playbook


def map_persona(title: str, playbook: Playbook) -> str | None:
    lowered = title.lower()
    best: tuple[int, str] | None = None
    for persona in playbook.personas:
        for keyword in persona.title_keywords:
            if keyword in lowered and (best is None or len(keyword) > best[0]):
                best = (len(keyword), persona.id)
    return None if best is None else best[1]
