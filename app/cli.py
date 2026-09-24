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
        "TECHNICAL SIGNAL: " + signal,
        "TECHNICAL SIGNALS: " + (", ".join(item.label for item in run.signals) or signal),
        "AFFECTED FUNCTIONS: " + (", ".join(run.affected_functions) or "unknown"),
        "CURRENT FUNCTION EVIDENCE: " + (", ".join(run.function_evidence_ids) or "none"),
        f"LIKELY FUNCTION: {function}",
        "LIKELY FUNCTIONS: "
        + (
            "; ".join(
                f"{item.signal_label}: {', '.join(item.likely_functions)}" for item in run.person_hypotheses
            )
            or ", ".join(item.label for item in run.functions)
            or function
        ),
        f"QUERIES EXECUTED: {run.queries_executed}",
        f"SEARCH RESULTS EXAMINED: {run.results_examined}",
        f"POTENTIAL NAMES DISCOVERED: {len({lead.name for lead in run.snippet_leads})}",
        "QUERIES:",
        "PERSON-SPECIFIC EVIDENCE:",
        "PERSON SEARCH TRACE:",
        "CANDIDATES DISCOVERED: "
        + str(len({trace.candidate for trace in run.person_traces if trace.candidate}) or len(run.people)),
        "CANDIDATES REJECTED: "
        + str(len([trace for trace in run.person_traces if trace.decision == "reject" and trace.candidate])),
        *[
            f"- {trace.candidate}: {trace.reason}"
            for trace in run.person_traces
            if trace.decision == "reject" and trace.candidate
        ],
        "CANDIDATES VERIFIED: "
        + str(len([person for person in run.people if person.selection_status == "verified_person"])),
        f"PERSONOPPORTUNITIES: {len(run.person_opportunities)}",
        "CURRENT CANDIDATES:",
        "VERIFIED PEOPLE:",
    ]
    query_at = lines.index("QUERIES:") + 1
    query_lines = [f"- {item.query} ({item.result_count} results)" for item in run.search_log] or ["- none"]
    lines[query_at:query_at] = query_lines
    evidence_at = lines.index("PERSON-SPECIFIC EVIDENCE:") + 1
    named_evidence = [
        f"- {item.source_url} | {item.excerpt}"
        for item in run.evidence
        if any(person.name in item.excerpt for person in run.people)
    ]
    lines[evidence_at:evidence_at] = named_evidence[:8] or ["- none"]
    candidate_at = lines.index("CURRENT CANDIDATES:") + 1
    candidate_lines = []
    for person in run.people:
        candidate_lines.append(
            "\n".join(
                [
                    f"NAME: {person.name}",
                    f"CURRENT ROLE: {person.title or 'unknown'}",
                    f"CURRENTNESS: {person.role_freshness}",
                    f"OWNERSHIP LEVEL: {person.ownership_level}",
                    "OWNERSHIP EVIDENCE: " + (", ".join(person.ownership_evidence_ids) or "none"),
                    "TECHNICAL EVIDENCE: " + (", ".join(person.footprint_topics) or "none"),
                    f"PERSON/PROBLEM FIT: {_fit_line(person)}",
                    f"WHY NOW: {person.current_ownership or 'unknown'}",
                ]
            )
        )
    lines[candidate_at:candidate_at] = candidate_lines or ["none"]
    owners = [person for person in run.people if person.ownership_level in {"explicit", "strong"}]
    final_at = lines.index("VERIFIED PEOPLE:")
    lines.insert(
        final_at,
        "FINAL: " + (f"VERIFIED CURRENT OWNER: {owners[0].name}" if owners else "NO CURRENT OWNER FOUND"),
    )
    trace_at = lines.index("PERSON SEARCH TRACE:") + 1
    trace_lines = [
        f"- query={trace.query or '-'} candidate={trace.candidate or '-'} "
        f"source={trace.source or '-'} decision={trace.decision} reason={trace.reason}"
        for trace in run.person_traces
    ] or ["- none"]
    lines[trace_at:trace_at] = trace_lines
    verified_ids = {person.id for person in run.people if person.selection_status == "verified_person"}
    verified_rows = [row for row in run.person_opportunities if row.person_id in verified_ids]
    if not verified_rows:
        lines.append("none")
        historical = [
            person
            for person in run.people
            if person.historical_expertise or person.role_freshness == "historical"
        ]
        if historical:
            lines.append("HISTORICAL CANDIDATES:")
        for person in historical[:5]:
            lines.append(
                f"- {person.name}: role_freshness={person.role_freshness} "
                f"current_ownership={person.current_ownership or 'unknown'}"
            )
    evidence_by_id = {item.id: item for item in run.evidence}
    for row in verified_rows:
        matched = [item for item in run.people if item.id == row.person_id]
        subject = matched[0] if matched else None
        kind = {
            "problem_owner": "PROBLEM OWNER",
            "access_path": "ACCESS PATH",
            "executive": "EXECUTIVE",
        }[row.person_kind]
        fit = "not scored" if row.person_fit is None else _fit_line(subject) if subject else "not scored"
        footprint = "none" if subject is None else ", ".join(subject.footprint_topics) or "none"
        support = [
            f"- {evidence_by_id[item_id].source_url} | {evidence_by_id[item_id].excerpt}"
            for item_id in row.supporting_evidence_ids
            if item_id in evidence_by_id
        ][:3]
        contra = [
            f"- {evidence_by_id[item_id].source_url} | {evidence_by_id[item_id].excerpt}"
            for item_id in row.contradicting_evidence_ids
            if item_id in evidence_by_id
        ][:3]
        lines.extend(
            [
                f"NAME: {row.person_name}",
                f"CURRENT ROLE: {row.person_title or 'unknown'}",
                f"ROLE FRESHNESS: {subject.role_freshness if subject else 'unknown'}",
                "CURRENT OWNERSHIP: "
                + (subject.current_ownership if subject and subject.current_ownership else "unknown"),
                "HISTORICAL EXPERTISE: "
                + (
                    "; ".join(subject.historical_expertise)
                    if subject and subject.historical_expertise
                    else "none"
                ),
                f"TECHNICAL RELEVANCE: {fit}",
                f"ACCOUNT TRIGGER: {row.account_trigger or 'unknown'}",
                f"TRIGGER → PERSON LINK: {row.trigger_link or 'none'}",
                f"PERSON-SPECIFIC TRIGGER: {row.trigger_strength}",
                f"ROLE / RESPONSIBILITY: {row.person_title or 'unknown'} ({kind})",
                f"WHY THIS PERSON: {row.angle}",
                f"TECHNICAL FOOTPRINT: {footprint}",
                f"WHY NOW: {row.why_now}",
                f"CONTACTABILITY: {row.contactability.level}",
                f"REDIS HYPOTHESIS: {row.redis_hypothesis or 'none'}",
                "ALTERNATIVES: " + (", ".join(row.alternative_technologies) or "none"),
                "SUPPORTING EVIDENCE:",
                *(support or ["- none"]),
                "CONTRADICTING EVIDENCE:",
                *(contra or ["- none"]),
                "UNKNOWN: " + ("; ".join(subject.contradictions) if subject and subject.contradictions else "none"),
                f"RECOMMENDED CHANNEL: {row.recommended_channel}",
                f"PLAYBOOK: {row.template_id or 'none'}",
                f"DECISION: {row.decision}",
            ]
        )
    primary = next((row for row in run.person_opportunities if row.thread_role == "primary_contact"), None)
    secondary = next((row for row in run.person_opportunities if row.thread_role == "secondary_contact"), None)
    executive = next((row for row in run.person_opportunities if row.thread_role == "executive_thread"), None)
    verified = [person for person in run.people if person.selection_status == "verified_person"]
    if not verified or (primary is None and secondary is None and executive is None):
        lines.append("NO ACTIONABLE PERSON OPPORTUNITY")
    else:
        lines.append("PRIMARY CONTACT: " + (primary.person_name if primary else "none"))
        lines.append("SECONDARY CONTACT: " + (secondary.person_name if secondary else "none"))
        lines.append("EXECUTIVE THREAD: " + (executive.person_name if executive else "none"))
    if selected is None:
        lines.append("FINAL: NO VERIFIED PERSON")
    else:
        lines.append(f"FINAL: SELECTED PERSON: {selected.name}")
    redis_primary = next((item for item in run.opportunities if item.is_primary), None)
    lines.append(
        "REDIS HYPOTHESIS: "
        + (
            "none"
            if redis_primary is None
            else f"{redis_primary.use_case_id} relevance={redis_primary.relevance}. {redis_primary.hypothesis}"
        )
    )
    lines.append("ALTERNATIVES: " + ("none" if redis_primary is None else ", ".join(redis_primary.alternatives)))
    unknowns = [] if rec is None else rec.unknown
    lines.append("UNKNOWN:")
    lines.extend(f"- {item}" for item in unknowns[:8])
    if run.research_missing:
        lines.append("MISSING:")
        lines.extend(f"- {item}" for item in run.research_missing)
        lines.append(f"NEXT RESEARCH QUESTION: {run.next_research_question}")
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
