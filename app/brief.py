"""Plain-text recommendation for human review."""

from app.domain.models import Recommendation, RunModel


def render_brief(run: RunModel) -> str:
    rec = run.recommendation
    if rec is None:
        return "No recommendation was produced."
    lines = [
        f"PERSON: {rec.person}",
        f"ROLE: {rec.role}",
        f"WHY THIS PERSON: {rec.why_this_person}",
        f"TECHNICAL SIGNAL: {rec.technical_signal}",
        f"WHY NOW: {rec.why_now}",
        f"REDIS HYPOTHESIS: {rec.redis_hypothesis}",
        "SUPPORTING EVIDENCE:",
        *_evidence_lines(rec, supporting=True),
        "CONTRADICTING EVIDENCE:",
        *_evidence_lines(rec, supporting=False),
        "UNKNOWN:",
        *[f"- {item}" for item in rec.unknown],
        f"CHANNEL: {rec.channel or 'none'}",
        f"TEMPLATE: {rec.template_id or 'none'}",
        "DRAFT:",
        rec.draft or "(no approved template matched)",
        f"CONFIDENCE: {rec.confidence}",
        f"STATUS: {rec.status}",
        f"SENT: {str(rec.sent).lower()}",
        f"RUNNER UP: {rec.runner_up or 'none'}",
        f"WHY NOT RUNNER UP: {rec.why_not_runner_up}",
    ]
    if rec.laya_shadow is not None:
        shadow = rec.laya_shadow
        lines.extend(
            [
                f"LAYA MODE: {shadow.mode}",
                f"LAYA PROVIDER: {shadow.provider}",
                f"LAYA TRAINED FOR REDIS GTM: {str(shadow.checkpoint_trained_for_redis_gtm).lower()}",
                f"LAYA NEXT STEP: {shadow.next_step}",
                f"LAYA SENT: {str(shadow.sent).lower()}",
            ]
        )
    lines.append("ANSWERS:")
    lines.extend(f"- {key} {value}" for key, value in rec.answers.items())
    return "\n".join(lines)


def _evidence_lines(rec: Recommendation, *, supporting: bool) -> list[str]:
    rows = rec.supporting_evidence if supporting else rec.contradicting_evidence
    if not rows:
        return ["- none"]
    return [f"- {item.source_title} | {item.source_url} | {item.excerpt}" for item in rows]
