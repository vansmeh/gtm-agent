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


def _person_why_now(run: RunModel, name: str, *, selected: bool) -> str:
    named = [
        item.excerpt
        for item in run.evidence
        if name in item.excerpt
        and item.published_at is not None
        and any(item.id in event.evidence_ids for event in run.why_now)
    ]
    if named:
        return named[0]
    if selected:
        account = next((event.summary for event in run.why_now if event.event_type != "unknown"), "")
        if account:
            return account
    return "unknown"


def _fit_line(person: object) -> str:
    from app.domain.models import PersonRecord

    if not isinstance(person, PersonRecord) or person.fit is None:
        return "not scored"
    fit = person.fit
    return (
        f"role_relevance={fit.role_relevance} problem_ownership={fit.problem_ownership} "
        f"technical_relevance={fit.technical_relevance} timing_relevance={fit.timing_relevance} "
        f"public_evidence={fit.public_evidence} seniority={fit.seniority} "
        f"contact_confidence={fit.contact_confidence}"
    )


def render_live_report(run: RunModel) -> str:
    rec = run.recommendation
    signal = run.signals[0].label if run.signals else "unknown"
    function = run.functions[0].label if run.functions else "unknown"
    selected = next((person for person in run.people if person.selection_status == "verified_person"), None)
    lines = [
        f"ACCOUNT: {run.account_name}",
        f"TECHNICAL SIGNAL: {signal}",
        f"LIKELY FUNCTION: {function}",
        "CANDIDATE PEOPLE:",
    ]
    if not run.people:
        lines.append("none")
    for person in run.people:
        evidence_lines = [
            f"- {item.source_url} | {item.excerpt}" for item in run.evidence if person.name in item.excerpt
        ][:4]
        if person.identity_excerpt and person.source_urls:
            identity_line = f"- {person.source_urls[0]} | {person.identity_excerpt}"
            if identity_line not in evidence_lines:
                evidence_lines.insert(0, identity_line)
        why = _person_why_now(run, person.name, selected=person.selection_status == "verified_person")
        matter = "" if person.dossier is None else person.dossier.appears_to_own
        contradictions = "; ".join(person.contradictions) if person.contradictions else "none"
        lines.extend(
            [
                f"NAME: {person.name}",
                f"TITLE: {person.title or 'unknown'}",
                f"WHY THEY MATTER: {matter}",
                f"RESPONSIBILITY: {person.responsibility_status}",
                f"PERSON/PROBLEM FIT: {_fit_line(person)}",
                f"WHY NOW: {why}",
                "EVIDENCE:",
                *(evidence_lines or ["- none"]),
                f"CONTRADICTIONS: {contradictions}",
                (
                    f"CONFIDENCE: identity={person.identity_confidence} "
                    f"validity={person.validity} selection={person.selection_status}"
                ),
            ]
        )
    if selected is None:
        lines.append("FINAL: NO VERIFIED PERSON")
    else:
        lines.append(f"FINAL: SELECTED PERSON: {selected.name}")
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
