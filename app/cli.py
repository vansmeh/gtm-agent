"""Live research commands. They recommend. They do not send."""

import argparse
from datetime import UTC, datetime

import httpx

from app.brief import render_brief
from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.domain.models import RunModel
from app.pipeline import PLAYBOOK_PATH, build_kernel, execute_run
from app.playbook.selection import load_playbook
from app.research.fetch import HttpxPageFetcher
from app.research.search import SearXNGSearchProvider
from app.sheets.provider import build_sheets_provider


def render_live_report(run: RunModel) -> str:
    rec = run.recommendation
    signal = run.signals[0].label if run.signals else "unknown"
    function = run.functions[0].label if run.functions else "unknown"
    lines = [
        f"ACCOUNT: {run.account_name}",
        f"TECHNICAL SIGNAL: {signal}",
        f"LIKELY FUNCTION: {function}",
        "TOP PEOPLE:",
    ]
    if not run.people:
        lines.append("1. unknown")
    for index, person in enumerate(run.people[:3], start=1):
        fit = person.fit
        evidence = [item.excerpt for item in run.evidence if person.name in item.excerpt][:3]
        why_now = next((event.summary for event in run.why_now if event.event_type != "unknown"), "unknown")
        if not any(event.event_type != "unknown" for event in run.why_now):
            why_now = "unknown"
        lines.extend(
            [
                f"{index}. {person.name}",
                f"WHY THIS PERSON: {'' if person.dossier is None else person.dossier.appears_to_own}",
                "EVIDENCE:",
                *([f"- {item}" for item in evidence] or ["- none"]),
                "PERSON/PROBLEM FIT: "
                + (
                    "not scored"
                    if fit is None
                    else (
                        f"role_relevance={fit.role_relevance} problem_ownership={fit.problem_ownership} "
                        f"technical_relevance={fit.technical_relevance} timing_relevance={fit.timing_relevance} "
                        f"public_evidence={fit.public_evidence} seniority={fit.seniority} "
                        f"contact_confidence={fit.contact_confidence}"
                    )
                ),
                f"WHY NOW: {why_now}",
                f"CONFIDENCE: {person.identity_confidence}",
            ]
        )
    primary = next((item for item in run.opportunities if item.is_primary), None)
    lines.append(
        "REDIS HYPOTHESIS: "
        + ("none" if primary is None else f"{primary.use_case_id} relevance={primary.relevance}. {primary.hypothesis}")
    )
    lines.append("ALTERNATIVES: " + ("none" if primary is None else ", ".join(primary.alternatives)))
    unknowns = [] if rec is None else rec.unknown
    lines.append("UNKNOWN:")
    lines.extend(f"- {item}" for item in unknowns[:8])
    lines.append("RECOMMENDED ACTION: " + ("review only" if rec is None else rec.disposition))
    lines.append("CHANNEL: " + ("none" if rec is None or not rec.channel else rec.channel))
    lines.append("TEMPLATE: " + ("none" if rec is None or not rec.template_id else rec.template_id))
    lines.append("HUMAN REVIEW REQUIRED")
    lines.append("STATUS: pending_human_review")
    lines.append("SENT: false")
    if rec is not None and rec.laya_shadow is not None:
        shadow = rec.laya_shadow
        lines.append(
            f"LAYA: decision_mode={shadow.decision_mode} provider={shadow.provider} "
            f"model={shadow.model} next_step={shadow.next_step}"
        )
    lines.append("---")
    lines.append(render_brief(run))
    return "\n".join(lines)


def _run(account: str, domain: str) -> RunModel:
    settings = Settings(search_provider="searxng", sheets_provider="mock", laya_mode="shadow")
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    client = httpx.Client(timeout=settings.search_timeout_seconds, follow_redirects=True)
    search = SearXNGSearchProvider(
        settings.searxng_base_url,
        timeout=settings.search_timeout_seconds,
        retries=settings.search_retries,
        budget=settings.search_budget,
    )
    with session_scope(factory) as session:
        return execute_run(
            settings=settings,
            account_name=account,
            domain=domain,
            search=search,
            fetcher=HttpxPageFetcher(client),
            sheets=build_sheets_provider(provider="mock", spreadsheet_id=None, credentials_file=None),
            kernel=build_kernel(settings),
            playbook=load_playbook(PLAYBOOK_PATH),
            session=session,
            observed_at=datetime.now(UTC),
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("research-person", "research-account"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--account", required=True)
        cmd.add_argument("--domain", required=True)
    args = parser.parse_args()
    run = _run(args.account, args.domain)
    print(render_live_report(run))


if __name__ == "__main__":
    main()
