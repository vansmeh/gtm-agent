"""Select a cadence and template from signal, persona, and timing."""

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

_SLOT = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_ALLOWED_SLOTS = frozenset(
    {
        "person_name",
        "role",
        "account_name",
        "signal_summary",
        "why_now",
        "hypothesis",
        "unknowns",
        "alternatives",
    }
)


class Persona(BaseModel):
    id: str
    title_keywords: list[str]


class Cadence(BaseModel):
    id: str
    auto_send: bool = False


class Template(BaseModel):
    id: str
    channel: str
    persona_ids: list[str]
    signal_types: list[str]
    timing: list[str]
    approved: bool = True
    subject: str
    body: str


class Playbook(BaseModel):
    version: str
    personas: list[Persona]
    cadences: list[Cadence]
    templates: list[Template] = Field(default_factory=list)


def load_playbook(path: Path) -> Playbook:
    return Playbook.model_validate(json.loads(path.read_text(encoding="utf-8")))


def compatible_templates(
    playbook: Playbook,
    *,
    persona_id: str | None,
    signal_types: set[str],
    why_now_types: set[str],
) -> list[Template]:
    if not persona_id:
        return []
    matched: list[Template] = []
    for template in playbook.templates:
        if not template.approved:
            continue
        if persona_id not in template.persona_ids:
            continue
        if not (set(template.signal_types) & signal_types):
            continue
        if not (set(template.timing) & why_now_types):
            continue
        matched.append(template)
    return matched


def choose_template(templates: list[Template], signal_types: set[str]) -> Template | None:
    if not templates:
        return None

    def overlap(template: Template) -> int:
        return len(set(template.signal_types) & signal_types)

    return max(templates, key=overlap)


def render_template(template: Template, slots: dict[str, str]) -> str:
    safe = {key: value.replace("{{", "").replace("}}", "") for key, value in slots.items()}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in _ALLOWED_SLOTS:
            return "[blocked]"
        return safe.get(key, "[unknown]")

    rendered = _SLOT.sub(replace, f"{template.subject}\n\n{template.body}")
    return rendered + "\n\n— draft for human review, not sent"
