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
from app.research.search import DirectWebSearchProvider
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


def _role_bridge_lines(run: RunModel) -> list[str]:
    lines = ["ROLE BRIDGE:"]
    if not run.role_bridge_reports:
        lines.append("none")
        return lines
    for report in run.role_bridge_reports:
        lines.extend(
            [
                f"CANDIDATE: {report.candidate}",
                f"ROLE QUERIES: {report.role_queries}",
                f"PUBLIC SOURCES: {report.sources_discovered}",
                f"FETCHED: {report.sources_fetched}",
                f"ROLE: {report.role_title or 'unknown'}",
                f"ROLE CONFIDENCE: {report.role_confidence}",
                f"CURRENTNESS: {report.currentness}",
                f"FUNCTION: {report.function or 'unknown'}",
                f"FUNCTION CONFIDENCE: {report.function_confidence}",
                f"OWNERSHIP: {report.ownership}",
                f"WHY: {report.why}",
            ]
        )
    return lines


def render_live_report(run: RunModel) -> str:
    rec = run.recommendation
    signal = run.signals[0].label if run.signals else "unknown"
    function = run.functions[0].label if run.functions else "unknown"
    selected = next((person for person in run.people if person.selection_status == "verified_person"), None)
    lines = [
        f"SEARCH PROVIDER = {run.search_mode}",
        f"SEARCH URL: {run.search_endpoint or 'none'}",
        f"TOTAL QUERIES: {run.queries_executed}",
        f"TOTAL RESULTS: {run.results_examined}",
        f"role_queries: {run.role_queries}",
        f"role_results: {run.role_results}",
        f"role_hits: {run.role_hits}",
        f"role_resolutions: {run.role_resolutions}",
        f"role_failures: {run.role_failures}",
        f"candidates: {run.candidates_retained}",
        f"role sources found: {run.role_results}",
        f"role resolutions: {run.role_resolutions}",
        "current roles: "
        + str(sum(person.role_state in {"current", "probable_current"} for person in run.people)),
        "current functions: "
        + str(sum(person.function_level in {"explicit", "strong"} for person in run.people)),
        "strong owners: "
        + str(sum(person.ownership_level in {"explicit", "strong"} for person in run.people)),
        "TIER_A: "
        + str(sum(row.opportunity_tier == "TIER_A_VERIFIED_OWNER" for row in run.person_opportunities)),
        "TIER_B: "
        + str(sum(row.opportunity_tier == "TIER_B_PROBABLE_OWNER" for row in run.person_opportunities)),
        "TIER_C: "
        + str(sum(row.opportunity_tier == "TIER_C_RELEVANT_PERSON" for row in run.person_opportunities)),
        "TIER_D: "
        + str(sum(row.opportunity_tier == "TIER_D_INSUFFICIENT" for row in run.person_opportunities)),
        f"ACCOUNT: {run.account_name}",
        *_role_bridge_lines(run),
        "TECHNICAL SIGNAL: " + signal,
        "TECHNICAL SIGNALS: " + (", ".join(item.label for item in run.signals) or signal),
        "AFFECTED FUNCTIONS: " + (", ".join(run.affected_functions) or "unknown"),
        "ARTIFACTS FOUND:",
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
        "DISCOVERY",
        f"Queries: {run.discovery_queries_used or run.queries_executed}",
        f"Results examined: {run.results_examined}",
        f"Names extracted: {run.names_extracted}",
        f"Duplicates: {run.names_duplicated}",
        f"Rejected: {run.names_rejected}",
        f"Retained: {run.candidates_retained}",
        f"QUERIES EXECUTED: {run.queries_executed}",
        f"SEARCH RESULTS EXAMINED: {run.results_examined}",
        f"POTENTIAL NAMES DISCOVERED: {len({lead.name for lead in run.snippet_leads})}",
        "QUERIES:",
        "PERSON-SPECIFIC EVIDENCE:",
        "PERSON SEARCH TRACE:",
        f"CANDIDATES DISCOVERED: {run.candidates_discovered or len(run.people)}",
        f"CANDIDATES REJECTED: {run.candidates_rejected}",
        f"CANDIDATES PRIORITIZED: {run.candidates_prioritized}",
        f"DEEP-RESEARCHED: {run.deep_researched_count}",
        "CURRENT AFFILIATIONS RESOLVED: "
        + str(len([person for person in run.people if person.affiliation in {"current", "probable"}])),
        "CURRENT ROLES RESOLVED: "
        + str(len([person for person in run.people if person.role_state in {"current", "probable_current"}])),
        "CURRENT FUNCTIONS RESOLVED: "
        + str(len([person for person in run.people if person.function_level in {"explicit", "strong", "probable"}])),
        "STRONG OWNERSHIP CANDIDATES: "
        + str(len([person for person in run.people if person.ownership_level == "strong"])),
        "CURRENT OWNERS VERIFIED: "
        + str(len([person for person in run.people if person.candidate_state == "verified_current_owner"])),
        "ACTIONABLE OPPORTUNITIES: "
        + str(len([row for row in run.person_opportunities if row.decision == "contact_now"])),
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
    artifact_at = lines.index("ARTIFACTS FOUND:") + 1
    artifact_lines = [
        f"- {item.kind} | {item.topic} | {item.author} | {item.published_at or 'undated'} | {item.source_url}"
        for item in run.artifacts
    ]
    lines[artifact_at:artifact_at] = artifact_lines or ["- none"]
    chain = ["ATTRIBUTION CHAIN:"]
    by_artifact = {item.id or item.evidence_id: item for item in run.artifacts}
    people_by_name = {person.name: person for person in run.people}
    for link in run.artifact_links:
        artifact = by_artifact.get(link.artifact_id)
        if artifact is None:
            continue
        person = people_by_name.get(link.person_name)
        opportunity = next((row for row in run.person_opportunities if row.person_name == link.person_name), None)
        query = next((trace.query for trace in run.search_traces if trace.result_url == artifact.url), "")
        role = person.title if person is not None and person.title else "unknown"
        function = person.function_level if person is not None else "unknown"
        ownership = person.ownership_level if person is not None else "unknown"
        tier = opportunity.opportunity_tier if opportunity is not None else "TIER_D_INSUFFICIENT"
        chain.append(
            f"QUERY {query or '-'} → RESULT {artifact.url} → ARTIFACT {artifact.kind} "
            f"→ PERSON {link.person_name or artifact.author} ({link.relationship}) "
            f"→ CURRENT ROLE {role} → FUNCTION {function} → OWNERSHIP {ownership} → OPPORTUNITY TIER {tier}"
        )
    lines[artifact_at + len(artifact_lines or ["- none"]) : artifact_at + len(artifact_lines or ["- none"])] = (
        chain or ["ATTRIBUTION CHAIN:", "none"]
    )
    candidate_at = lines.index("CURRENT CANDIDATES:") + 1
    candidate_lines = []
    opportunity_by_person = {row.person_id: row for row in run.person_opportunities}
    for person in run.people:
        candidate_lines.append(
            "\n".join(
                [
                    f"DISCOVERED PERSONS: {person.name}",
                    f"NAME: {person.name}",
                    f"CURRENT EMPLOYER: {person.current_employer or person.company or 'unknown'}",
                    f"SOURCE: {person.candidate_source_type or 'unknown'}",
                    f"CURRENT AFFILIATION: {person.affiliation}",
                    f"CURRENT ROLE: {person.title or 'unknown'}",
                    f"ROLE SOURCE: {person.role_source or 'none'}",
                    f"ROLE DATE: {person.role_as_of or 'undated'}",
                    f"ROLE CONFIDENCE: {person.role_confidence}",
                    f"ROLE STATE: {person.role_state}",
                    "CURRENT ROLE EVIDENCE: " + (", ".join(person.role_evidence_ids) or "none"),
                    f"TECHNICAL ATTRIBUTION: {person.technical_activity}",
                    f"CURRENT FUNCTION: {person.function_level}",
                    f"FUNCTION SOURCE: {person.function_source or 'none'}",
                    "FUNCTION EVIDENCE: " + (", ".join(person.person_function_evidence_ids) or "none"),
                    f"TECHNICAL ARTIFACT: {person.technical_activity}",
                    f"TECHNICAL RESPONSIBILITY: {person.technical_responsibility or 'unknown'}",
                    f"ACCOUNT TRIGGER: {person.trigger_to_function or 'unknown'}",
                    f"TRIGGER → FUNCTION: {person.trigger_to_function or 'none'}",
                    f"TRIGGER → PERSON: {person.trigger_to_person or 'none'}",
                    f"OWNERSHIP LEVEL: {person.ownership_level}",
                    "OWNERSHIP EVIDENCE: " + (", ".join(person.ownership_evidence_ids) or "none"),
                    f"OWNERSHIP CONFIDENCE: {person.ownership_level}",
                    f"CANDIDATE STATE: {person.candidate_state}",
                    f"PRIORITY: {person.candidate_priority_reason or 'not prioritized'}",
                    f"TECHNICAL RELEVANCE: {person.function_level}",
                    f"REDIS HYPOTHESIS: {_opportunity_field(opportunity_by_person.get(person.id), 'redis_hypothesis')}",
                    f"WHY NOW: {_opportunity_field(opportunity_by_person.get(person.id), 'why_now')}",
                    f"CONTACTABILITY: {_opportunity_field(opportunity_by_person.get(person.id), 'contact')}",
                    f"OPPORTUNITY TIER: {_opportunity_field(opportunity_by_person.get(person.id), 'tier')}",
                    f"TIER EVIDENCE: {_opportunity_field(opportunity_by_person.get(person.id), 'evidence')}",
                    f"ACTIONABILITY: {_opportunity_field(opportunity_by_person.get(person.id), 'action')}",
                    f"DECISION: {'deep-researched' if person.deep_researched else 'not deep-researched'}",
                    f"NEXT: {person.next_query or 'none'}",
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


def _opportunity_field(row: object, field: str) -> str:
    if row is None:
        return "unknown"
    from app.domain.models import PersonOpportunity

    if not isinstance(row, PersonOpportunity):
        return "unknown"
    if field == "redis_hypothesis":
        return row.redis_hypothesis or "unknown"
    if field == "why_now":
        return row.why_now or "unknown"
    if field == "contact":
        return row.contactability.level
    if field == "tier":
        return row.opportunity_tier
    if field == "evidence":
        return row.tier_evidence or "none"
    if field == "action":
        return row.decision
    return "unknown"


def _run(account: str, domain: str) -> RunModel:
    settings = Settings(search_provider="direct", sheets_provider="mock", laya_mode="shadow")
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    client = httpx.Client(timeout=settings.search_timeout_seconds, follow_redirects=True)
    search = DirectWebSearchProvider(
        timeout=settings.search_timeout_seconds,
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
