"""Pipeline nodes. Each one reads evidence already on the run and writes structured results."""

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    Evidence,
    PersonRecord,
    PersonSearchTrace,
    Recommendation,
    ResearchLogEntry,
    RunModel,
    SearchExecution,
    SnippetLead,
    TemplateChoice,
)
from app.graph.state import GraphState, dump_run, load_run
from app.laya.adapter import LayaAdapter
from app.opportunity.person_opportunity import (
    apply_redis,
    apply_why_now,
    assign_threads,
    build_opportunities,
    c_suite_without_specialist_role,
    decide_channel,
    decide_contact,
    footprint_queries,
    hypotheses_for,
    hypothesis_queries,
    research_gap,
    trigger_queries,
)
from app.opportunity.redis_mapper import map_opportunities
from app.opportunity.why_now import detect_why_now
from app.person.discovery import discover_mentions
from app.person.identity import identities_from_mentions, validity_for
from app.person.person_account_fit import assess_fit
from app.person.persona_mapping import map_persona
from app.person.public_activity import collect_activity
from app.person.ranking import build_dossier, explain_pair, rank_people, selection_status_for
from app.person.responsibility import classify_responsibility, extract_responsibilities
from app.person.role import function_guess_from_title, seniority_from_title
from app.person.snippets import candidates_from_hits
from app.person.technical_footprint import build_footprint
from app.playbook.selection import (
    Playbook,
    choose_template,
    compatible_templates,
    render_template,
)
from app.research.bounds import evidence_is_sufficient, person_discovery_queries, queries_for, source_rank
from app.research.extract import extract_evidence, observation_from_page
from app.research.fetch import PageFetcher
from app.research.search import SearchProvider
from app.sheets.provider import SheetsProvider
from app.signals.detection import detect_signals, strongest_problem
from app.signals.functions import detect_functions


@dataclass
class PipelineDeps:
    search: SearchProvider
    fetcher: PageFetcher
    sheets: SheetsProvider
    kernel: LayaAdapter
    playbook: Playbook
    observed_at: datetime
    max_searches_per_cycle: int = 4
    person_query_budget: int = 6
    search_provider_name: str = "mock"


def _log(run: RunModel, node: str, message: str) -> None:
    run.logs.append(ResearchLogEntry(node=node, message=message, cycle=run.cycle))


def intake(state: GraphState) -> GraphState:
    run = load_run(state)
    _log(run, "intake", f"Account intake for {run.account_name}.")
    return dump_run(run)


def plan_search(state: GraphState) -> GraphState:
    run = load_run(state)
    run.cycle += 1
    if run.cycle > run.max_cycles:
        run.stop_research = True
        _log(run, "plan_search", "Research cap reached.")
    else:
        _log(run, "plan_search", f"Starting research cycle {run.cycle}.")
    return dump_run(run)


def _ingest_page(
    run: RunModel,
    deps: PipelineDeps,
    url: str,
    published_hint: str | None = None,
    *,
    person_slot: bool = False,
) -> None:
    from datetime import date

    if url in run.fetched_urls:
        return
    if person_slot:
        if run.person_pages_used >= run.person_page_budget:
            return
    elif len(run.fetched_urls) >= run.max_pages:
        return
    page = deps.fetcher.fetch(url)
    run.fetched_urls.append(url)
    if person_slot:
        run.person_pages_used += 1
    if page.status != "ok":
        _log(run, "fetch", f"Skipped {url}: {page.status} {page.error}")
        return
    if page.published_at is None and published_hint:
        try:
            page = page.model_copy(update={"published_at": date.fromisoformat(published_hint[:10])})
        except ValueError:
            page = page
    observation = observation_from_page(page, observed_at=deps.observed_at, cycle=run.cycle)
    if any(existing.text_sha256 == observation.text_sha256 for existing in run.observations):
        _log(run, "extract", f"Skipped duplicate content at {url}.")
        return
    run.observations.append(observation)
    if observation.poisoned:
        _log(run, "extract", f"Quarantined untrusted instructions at {url}.")
        return
    found = extract_evidence(observation)
    run.evidence.extend(found)
    _log(run, "extract", f"Extracted {len(found)} evidence items from {url}.")


def _search_and_fetch(run: RunModel, deps: PipelineDeps) -> None:
    if run.stop_research:
        return
    queries = queries_for(run.account_name, run.cycle)[: deps.max_searches_per_cycle]
    for query in queries:
        if len(run.fetched_urls) >= run.max_pages:
            _log(run, "search", "Account page budget reached.")
            break
        hits = deps.search.search(query, limit=4)
        _note_search(run, query, hits)
        _record_snippet_leads(run, hits, query)
        _log(run, "search", f"Query {query!r} returned {len(hits)} hits.")
        for hit in hits:
            _ingest_page(run, deps, hit.url, hit.published_at)


def search_and_extract(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        _search_and_fetch(run, deps)
        return dump_run(run)

    return node


def assess(state: GraphState) -> GraphState:
    run = load_run(state)
    topics: set[str] = set()
    for item in run.evidence:
        topics.update(item.topics)
    urls = {item.source_url for item in run.evidence}
    if run.cycle >= run.max_cycles or evidence_is_sufficient(topics, urls):
        run.stop_research = True
        _log(run, "assess", f"Stopping research after cycle {run.cycle}.")
    else:
        _log(run, "assess", "Evidence is thin. Another cycle is allowed.")
    return dump_run(run)


def route_after_assess(state: GraphState) -> str:
    run = load_run(state)
    if run.stop_research or run.cycle >= run.max_cycles:
        return "detect_signals"
    return "plan_search"


def detect_signal_node(state: GraphState) -> GraphState:
    run = load_run(state)
    run.signals = detect_signals(run.evidence)
    _log(run, "signals", f"Detected {len(run.signals)} technical signals.")
    return dump_run(run)


def detect_function_node(state: GraphState) -> GraphState:
    run = load_run(state)
    run.functions = detect_functions(run.evidence)
    _log(run, "functions", f"Detected {len(run.functions)} owning functions.")
    return dump_run(run)


def generate_person_hypotheses(state: GraphState) -> GraphState:
    run = load_run(state)
    run.person_hypotheses = hypotheses_for(run.signals)
    labels = [item.signal_label for item in run.person_hypotheses] or ["none"]
    _log(run, "hypotheses", f"Person hypothesis tree for {', '.join(labels)}.")
    return dump_run(run)


def discover_people(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        function_label = run.functions[0].label if run.functions else ""
        signal_label = " ".join(item.label for item in run.signals[:2]) or "technical"
        queries = (
            person_discovery_queries(run.account_name, run.domain, function_label, signal_label)
            + hypothesis_queries(run.account_name, run.person_hypotheses)
        )[: deps.person_query_budget]
        collected: list[tuple[int, str, str | None]] = []
        seen_hits: set[str] = set()
        for query in queries:
            hits = deps.search.search(query, limit=4)
            _note_search(run, query, hits)
            _record_snippet_leads(run, hits, query)
            _log(run, "people", f"Person discovery query {query!r} returned {len(hits)} hits.")
            run.person_traces.append(
                PersonSearchTrace(
                    query=query,
                    finding=f"{len(hits)} public hits",
                    decision="accept" if hits else "reject",
                    reason="hits returned" if hits else "no public hits",
                )
            )
            for hit in hits:
                if hit.url in seen_hits:
                    continue
                seen_hits.add(hit.url)
                collected.append((source_rank(hit.url, run.domain), hit.url, hit.published_at))
        collected.sort(key=lambda item: item[0])
        discovery_page_cap = max(1, run.person_page_budget - 2)
        for _rank, url, published in collected:
            if run.person_pages_used >= discovery_page_cap:
                break
            _ingest_page(run, deps, url, published, person_slot=True)
        observed_on = run.observed_at.date()
        mentions = discover_mentions(run.observations, run.account_name)
        _verify_snippet_leads(run, deps, mentions)
        mentions = discover_mentions(run.observations, run.account_name)
        topic = signal_label or "architecture"
        followed = 0
        for mention in mentions:
            if c_suite_without_specialist_role(mention.title):
                run.person_traces.append(
                    PersonSearchTrace(
                        query="",
                        candidate=mention.name,
                        source=mention.url,
                        finding=mention.title,
                        decision="reject",
                        reason="C-suite title without a specialist role or ownership evidence",
                    )
                )
                continue
            if followed >= 2 or run.person_pages_used >= run.person_page_budget:
                run.person_traces.append(
                    PersonSearchTrace(
                        query="",
                        candidate=mention.name,
                        source=mention.url,
                        finding=mention.title,
                        decision="reject",
                        reason="person search budget exhausted before footprint research",
                    )
                )
                continue
            stages = footprint_queries(mention.name, run.account_name, topic) + trigger_queries(
                mention.name, run.account_name
            )
            fetched_followups = 0
            for index, query in enumerate(stages):
                follow = deps.search.search(query, limit=4)
                _note_search(run, query, follow)
                run.person_traces.append(
                    PersonSearchTrace(
                        query=query,
                        candidate=mention.name,
                        source=mention.url,
                        finding=f"{len(follow)} follow-up hits",
                        decision="accept" if follow else "reject",
                        reason="checking technical footprint and a person-specific trigger",
                    )
                )
                # The first footprint query and the first trigger query may fetch.
                # Later queries are stored. Extra pages stay inside the person budget.
                may_fetch = index in {0, len(footprint_queries(mention.name, run.account_name, topic))}
                if not may_fetch or run.person_pages_used >= run.person_page_budget or fetched_followups >= 4:
                    continue
                fresh = [hit for hit in follow if hit.url not in run.fetched_urls]
                for hit in fresh[:2]:
                    if run.person_pages_used >= run.person_page_budget or fetched_followups >= 4:
                        break
                    _ingest_page(run, deps, hit.url, hit.published_at, person_slot=True)
                    fetched_followups += 1
            followed += 1
        mentions = discover_mentions(run.observations, run.account_name)
        if mentions:
            lead = mentions[0].name
            check_query = f"{lead} {run.account_name} former OR previously"
            check = deps.search.search(check_query, limit=3)
            _note_search(run, check_query, check)
            _log(run, "people", f"Contradiction check for {lead} returned {len(check)} hits.")
            for hit in check[:1]:
                _ingest_page(run, deps, hit.url, hit.published_at, person_slot=True)
            mentions = discover_mentions(run.observations, run.account_name)
        people: list[PersonRecord] = []
        for identity in identities_from_mentions(mentions, run.account_name, observed_on=observed_on):
            _attach_ownership_window(run, identity.name)
            status, responsibility_lines = classify_responsibility(
                identity.name, identity.title, run.evidence, function_label
            )
            record = PersonRecord(
                id=str(uuid.uuid4()),
                name=identity.name,
                title=identity.title,
                company=identity.company,
                identity_excerpt=identity.excerpt,
                identity_confidence=identity.confidence,
                responsibility_status=status,  # type: ignore[arg-type]
                first_seen=identity.first_seen,
                last_seen=identity.last_seen,
                role_published_at=identity.role_published_at,
                validity=validity_for(identity.last_seen, observed_on=observed_on),  # type: ignore[arg-type]
                contradictions=identity.contradictions,
                source_urls=identity.urls,
                seniority=seniority_from_title(identity.title),
                function_guess=function_guess_from_title(identity.title),
                responsibilities=responsibility_lines or extract_responsibilities(identity.name, run.evidence),
                activity=collect_activity(identity.name, run.observations, run.evidence),
                footprint_topics=build_footprint(identity.name, run.evidence, run.observations),
                authored_urls=[],
                persona_id=map_persona(identity.title, deps.playbook),
            )
            record.authored_urls = [item.url for item in record.activity if item.authored]
            if identity.contradictions:
                reason = "contradictory identity"
                decision = "reject"
            elif record.validity == "stale":
                reason = "role evidence is older than the freshness window"
                decision = "reject"
            elif status == "unknown":
                reason = "responsibility not supported after verification"
                decision = "reject"
            else:
                reason = "identity, role, and responsibility evidence found"
                decision = "accept"
            run.person_traces.append(
                PersonSearchTrace(
                    query="",
                    candidate=identity.name,
                    source=identity.urls[0] if identity.urls else "",
                    finding=identity.excerpt[:180],
                    decision=decision,  # type: ignore[arg-type]
                    reason=reason,
                )
            )
            people.append(record)
        run.people = people
        _log(run, "verify", f"Verified {len(people)} people from fetched pages.")
        return dump_run(run)

    return node


def _attach_ownership_window(run: RunModel, name: str) -> None:
    """Keep a short public window when ownership is split across neighboring sentences."""
    from app.research.extract import classify_sentence

    for obs in run.observations:
        text = obs.sanitized_text
        idx = text.find(name)
        if idx < 0:
            continue
        window = " ".join(text[idx : idx + 700].split())
        if "teams are building" not in window.lower():
            continue
        owner_at = window.lower().find("teams are building")
        if re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+,", window[len(name) : owner_at]):
            continue
        topics, supports, contradicts, gap = classify_sentence(window)
        if not topics:
            continue
        already = [
            item
            for item in run.evidence
            if name in item.excerpt and item.source_url == obs.url and len(item.excerpt) > 240
        ]
        if already:
            return
        run.evidence.append(
            Evidence(
                id=str(uuid.uuid4()),
                observation_id=obs.id,
                excerpt=window[:500],
                source_url=obs.url,
                source_title=obs.title,
                source_type=obs.source_type,
                published_at=obs.published_at,
                observed_at=obs.observed_at,
                confidence=0.62,
                lineage=[obs.id],
                topics=topics,
                supports_problem=supports,
                contradicts_redis=contradicts,
                is_explicit_gap=gap,
            )
        )
        return


def _note_search(run: RunModel, query: str, hits: Sequence[object]) -> None:
    from app.research.search import SearchHit

    typed = [hit for hit in hits if isinstance(hit, SearchHit)]
    run.queries_executed += 1
    run.results_examined += len(typed)
    run.search_log.append(SearchExecution(query=query, result_count=len(typed), urls=[hit.url for hit in typed]))


def _record_snippet_leads(run: RunModel, hits: Sequence[object], query: str) -> None:
    from app.research.search import SearchHit

    typed = [hit for hit in hits if isinstance(hit, SearchHit)]
    for mention in candidates_from_hits(typed, run.account_name, query):
        if any(lead.name == mention.name and lead.url == mention.url for lead in run.snippet_leads):
            continue
        run.snippet_leads.append(
            SnippetLead(
                name=mention.name,
                title=mention.title,
                url=mention.url,
                excerpt=mention.excerpt,
                query=query,
            )
        )
        run.person_traces.append(
            PersonSearchTrace(
                query=query,
                candidate=mention.name,
                source=mention.url,
                finding=mention.excerpt[:180],
                decision="accept",
                reason="snippet names the person, company, and role; identity is not verified yet",
            )
        )


def _verify_snippet_leads(run: RunModel, deps: PipelineDeps, mentions: Sequence[object]) -> None:
    known = {getattr(mention, "name", "") for mention in mentions}
    for lead in run.snippet_leads:
        if lead.name in known:
            continue
        if run.person_pages_used >= run.person_page_budget:
            run.person_traces.append(
                PersonSearchTrace(
                    query=lead.query,
                    candidate=lead.name,
                    source=lead.url,
                    finding=lead.title,
                    decision="reject",
                    reason="snippet candidate was not fetched from an independent source before the page budget ended",
                )
            )
            continue
        query = f'"{lead.name}" {run.account_name}'
        hits = deps.search.search(query, limit=3)
        _note_search(run, query, hits)
        if lead.url not in run.fetched_urls and run.person_pages_used < run.person_page_budget:
            _ingest_page(run, deps, lead.url, None, person_slot=True)
        fresh = [hit for hit in hits if hit.url not in run.fetched_urls and hit.url != lead.url]
        for hit in fresh[:1]:
            if run.person_pages_used >= run.person_page_budget:
                break
            _ingest_page(run, deps, hit.url, hit.published_at, person_slot=True)
        run.person_traces.append(
            PersonSearchTrace(
                query=query,
                candidate=lead.name,
                source=lead.url,
                finding=f"{len(fresh)} independent hits",
                decision="accept" if fresh else "reject",
                reason=(
                    "searching an independent source for the snippet candidate"
                    if fresh
                    else "no independent public page was found for the snippet candidate"
                ),
            )
        )


def verify_people(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    del deps
    return match_people


def research_people(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    del deps

    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        run.signals = detect_signals(run.evidence)
        run.functions = detect_functions(run.evidence) or run.functions
        _log(run, "people", f"Technical footprint recorded for {len(run.people)} people.")
        return dump_run(run)

    return node


def match_people(state: GraphState) -> GraphState:
    run = load_run(state)
    observed_on = run.observed_at.date()
    for person in run.people:
        person.fit = assess_fit(
            person,
            run.evidence,
            run.functions,
            observed_on=observed_on,
            window_days=180,
        )
        person.selection_status = selection_status_for(person)  # type: ignore[assignment]
    verified = [person for person in run.people if person.selection_status == "verified_person"]
    weak = [person for person in run.people if person.selection_status == "weak_candidate"]
    if verified:
        run.person_outcome = "verified_person"
    elif weak:
        run.person_outcome = "weak_candidate"
    else:
        run.person_outcome = "no_verified_person"
    run.people = rank_people(run.people)
    problem = strongest_problem(run.signals)
    label = problem.label if problem else ""
    if len(run.people) >= 2:
        comparison = explain_pair(run.people[0], run.people[1])
    elif run.people:
        comparison = "No second public person was available to compare."
    else:
        comparison = "No public person was established."
    for index, person in enumerate(run.people):
        other = comparison if index == 0 else "Ranked behind the lead person on the explicit fit dimensions."
        person.dossier = build_dossier(person, comparison=other, problem_label=label)
    _log(run, "match", "Scored role, ownership, technical fit, timing, evidence, seniority, and contact confidence.")
    return dump_run(run)


def why_now_node(state: GraphState) -> GraphState:
    run = load_run(state)
    run.why_now = detect_why_now(run.evidence, observed_on=run.observed_at.date(), window_days=180)
    apply_why_now(run.person_opportunities, run.why_now, run.evidence)
    _log(run, "why_now", f"Recorded {len(run.why_now)} why-now events. Buying intent remains false.")
    return dump_run(run)


def map_redis(state: GraphState) -> GraphState:
    run = load_run(state)
    run.opportunities = map_opportunities(run.evidence)
    primary = next((item for item in run.opportunities if item.is_primary), None)
    apply_redis(run.person_opportunities, run.opportunities)
    label = "none" if primary is None else f"{primary.use_case_id}:{primary.relevance}"
    _log(run, "redis", f"Primary Redis hypothesis is {label}.")
    return dump_run(run)


def build_person_opportunities(state: GraphState) -> GraphState:
    run = load_run(state)
    run.person_opportunities = build_opportunities(
        account_id=run.account_id,
        people=run.people,
        signals=run.signals,
        evidence=run.evidence,
        observed_at=run.observed_at,
    )
    _log(run, "person_opportunity", f"Built {len(run.person_opportunities)} person opportunities.")
    return dump_run(run)


def decide_contact_node(state: GraphState) -> GraphState:
    run = load_run(state)
    by_id = {person.id: person for person in run.people}
    for row in run.person_opportunities:
        row.decision = decide_contact(row, by_id.get(row.person_id))  # type: ignore[assignment]
        row.updated_at = run.observed_at
    _log(run, "decide_contact", "Contact decision uses problem, ownership, trigger, and Redis hypothesis.")
    return dump_run(run)


def decide_channel_node(state: GraphState) -> GraphState:
    run = load_run(state)
    for row in run.person_opportunities:
        row.recommended_channel = decide_channel(row)  # type: ignore[assignment]
    assign_threads(run.person_opportunities)
    _log(run, "decide_channel", "Channel and thread are per person. The same message is not reused.")
    return dump_run(run)


def select_templates(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        person = next((item for item in run.people if item.selection_status == "verified_person"), None)
        signals = {item.signal_type for item in run.signals}
        timings = {item.event_type for item in run.why_now}
        persona = None if person is None else person.persona_id
        matched = compatible_templates(
            deps.playbook,
            persona_id=persona,
            signal_types=signals,
            why_now_types=timings,
        )
        run.compatible_template_ids = [item.id for item in matched]
        run.template_channels = {item.id: item.channel for item in matched}
        chosen = choose_template(matched, signals)
        cadence = deps.playbook.cadences[0].id if deps.playbook.cadences else "technical_review_first"
        if chosen is not None and person is not None and person.persona_id is not None:
            run.template_choice = TemplateChoice(
                template_id=chosen.id,
                channel=chosen.channel,
                persona_id=person.persona_id,
                cadence_id=cadence,
                auto_send=False,
            )
            primary = next(
                (row for row in run.person_opportunities if row.person_id == person.id),
                None,
            )
            if primary is not None and primary.recommended_channel == chosen.channel:
                primary.template_id = chosen.id
        _log(run, "playbook", f"Compatible templates: {run.compatible_template_ids or ['none']}.")
        return dump_run(run)

    return node


def laya_node(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        run.laya = deps.kernel.decide(run)
        if run.laya is not None and run.laya.decision_mode == "heuristic":
            primary = next(
                (row for row in run.person_opportunities if row.thread_role == "primary_contact"),
                None,
            )
            run.laya.strongest_person_opportunity_id = None if primary is None else primary.id
            run.laya.contact_decision = "research_more"
            run.laya.thread_role = "none" if primary is None else primary.thread_role
            run.laya.notes.append("Shadow Laya is not trained for Redis GTM and does not emit contact_now.")
        _log(
            run,
            "laya",
            f"Shadow provider {run.laya.provider} next_step={run.laya.next_step}. Not sent.",
        )
        return dump_run(run)

    return node


def _evidence_by_id(run: RunModel) -> dict[str, object]:
    return {item.id: item for item in run.evidence}


def recommend(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        person = next((item for item in run.people if item.selection_status == "verified_person"), None)
        others = [item for item in run.people if person is None or item.id != person.id]
        runner = others[0] if others else None
        problem = strongest_problem(run.signals)
        primary = next((item for item in run.opportunities if item.is_primary), None)
        by_id = {item.id: item for item in run.evidence}
        supporting = []
        contradicting = []
        if primary is not None:
            supporting = [by_id[item_id] for item_id in primary.supporting_evidence_ids if item_id in by_id]
            contradicting = [
                by_id[item_id] for item_id in primary.contradicting_evidence_ids if item_id in by_id
            ]
        unknowns = [
            "No verified public email or phone.",
            "Buying authority is not established.",
            "Technical relevance is not buying intent.",
        ]
        if primary is not None:
            unknowns.extend(primary.unknowns)
        signal_text = problem.label if problem else "No technical problem was established from public evidence."
        why = (
            " ".join(event.summary for event in run.why_now)
            if run.why_now
            else "No recent public trigger was established."
        )
        if primary is None:
            hypothesis = "No Redis use case was mapped."
        else:
            mappings = [
                f"{item.use_case_id}={item.relevance}"
                for item in run.opportunities
                if item.id != primary.id
            ]
            hypothesis = (
                f"{primary.name} is {primary.relevance}. {primary.hypothesis} "
                f"Falsifier: {primary.falsifier} Other mappings: {', '.join(mappings)}."
            )
        fit = None if person is None else person.fit
        ready = (
            person is not None
            and fit is not None
            and fit.problem_ownership >= 0.6
            and fit.technical_relevance >= 0.4
            and fit.public_evidence >= 0.5
            and primary is not None
            and primary.relevance in {"plausible", "strongly_supported"}
            and run.template_choice is not None
        )
        disposition = "review_draft" if ready else "research_more"
        if not run.signals and not run.people:
            disposition = "ignore"
        elif primary is not None and primary.relevance == "not_relevant" and not run.people:
            disposition = "ignore"
        draft = None
        channel = None
        template_id = None
        if person is not None and run.template_choice is not None and disposition == "review_draft":
            template = next(
                item for item in deps.playbook.templates if item.id == run.template_choice.template_id
            )
            channel = template.channel
            template_id = template.id
            draft = render_template(
                template,
                {
                    "person_name": person.name,
                    "role": person.title,
                    "account_name": run.account_name,
                    "signal_summary": signal_text,
                    "why_now": why,
                    "hypothesis": hypothesis,
                    "unknowns": "; ".join(dict.fromkeys(unknowns)),
                    "alternatives": ", ".join(primary.alternatives) if primary else "[unknown]",
                },
            )
        why_person = "No public person was established from evidence."
        why_not = ""
        if person is not None and person.dossier is not None:
            why_person = person.dossier.why_this_person_instead_of_another
            why_person = f"{person.dossier.appears_to_own} {why_person}"
        if runner is not None and person is not None:
            why_not = explain_pair(person, runner)
        answers = {
            "WHO should I contact?": "unknown" if person is None else person.name,
            "WHY this person?": why_person,
            "WHAT technical problem is relevant?": signal_text,
            "WHAT evidence connects this person to it?": _connection(run, person.name) if person else "none",
            "WHY NOW?": why,
            "WHAT Redis use case could plausibly matter?": hypothesis,
            "WHAT is unknown?": "; ".join(dict.fromkeys(unknowns)),
            "WHAT should I do next?": (
                "Review the draft. Do not send it."
                if disposition == "review_draft"
                else "Research more before preparing outreach."
                if disposition == "research_more"
                else "Ignore for now."
            ),
        }
        confidence: dict[str, float | str] = {
            "label": "medium" if ready else "low",
            "contact_inferred_automatically": 0,
        }
        if fit is not None:
            confidence.update(
                {
                    "role_relevance": fit.role_relevance,
                    "problem_ownership": fit.problem_ownership,
                    "technical_relevance": fit.technical_relevance,
                    "timing_relevance": fit.timing_relevance,
                    "public_evidence": fit.public_evidence,
                    "seniority": fit.seniority,
                    "contact_confidence": fit.contact_confidence,
                }
            )
        problem = strongest_problem(run.signals)
        primary_case = next((item for item in run.opportunities if item.is_primary), None)
        account_hypothesis = primary_case is not None and primary_case.relevance in {
            "plausible",
            "strongly_supported",
        }
        missing, question = research_gap(
            account_name=run.account_name,
            problem=problem.label if problem else "",
            has_owner=any(person.selection_status == "verified_person" for person in run.people),
            has_trigger=any(row.why_now_credible for row in run.person_opportunities),
            has_hypothesis=account_hypothesis or any(row.redis_credible for row in run.person_opportunities),
        )
        run.research_missing = missing
        run.next_research_question = question
        if missing:
            _log(run, "research_more", "MISSING: " + "; ".join(missing) + f" NEXT: {question}")
        run.action_id = str(uuid.uuid4())
        for row in run.person_opportunities:
            if row.thread_role == "primary_contact":
                row.action_id = run.action_id
        run.recommendation = Recommendation(
            id=str(uuid.uuid4()),
            person="unknown" if person is None else person.name,
            role="unknown" if person is None else person.title,
            why_this_person=why_person,
            technical_signal=signal_text,
            why_now=why,
            redis_hypothesis=hypothesis,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            unknown=list(dict.fromkeys(unknowns)),
            channel=channel,
            template_id=template_id,
            draft=draft,
            confidence=confidence,
            fit=fit,
            runner_up=None if runner is None else runner.name,
            why_not_runner_up=why_not,
            disposition=disposition,  # type: ignore[arg-type]
            laya_shadow=run.laya,
            answers=answers,
        )
        _log(run, "recommend", f"Disposition {disposition}. Status pending_human_review. sent=false.")
        return dump_run(run)

    return node


def _connection(run: RunModel, name: str) -> str:
    lines = [item.excerpt for item in run.evidence if name in item.excerpt]
    return " | ".join(lines[:4]) if lines else "No excerpt names this person on the technical problem."


def write_sheets(deps: PipelineDeps) -> Callable[[GraphState], GraphState]:
    def node(state: GraphState) -> GraphState:
        run = load_run(state)
        rec = run.recommendation
        deps.sheets.ensure_tabs()
        deps.sheets.append(
            "ACCOUNTS",
            {
                "account_id": run.account_id,
                "name": run.account_name,
                "domain": run.domain,
                "run_id": run.run_id,
                "observed_at": run.observed_at.isoformat(),
            },
        )
        for person in run.people:
            fit = person.fit
            deps.sheets.append(
                "PEOPLE",
                {
                    "person_id": person.id,
                    "name": person.name,
                    "role": person.title,
                    "role_relevance": "" if fit is None else f"{fit.role_relevance:.2f}",
                    "problem_ownership": "" if fit is None else f"{fit.problem_ownership:.2f}",
                    "technical_relevance": "" if fit is None else f"{fit.technical_relevance:.2f}",
                    "timing_relevance": "" if fit is None else f"{fit.timing_relevance:.2f}",
                    "public_evidence": "" if fit is None else f"{fit.public_evidence:.2f}",
                    "seniority": "" if fit is None else f"{fit.seniority:.2f}",
                    "contact_confidence": "" if fit is None else f"{fit.contact_confidence:.2f}",
                    "why_this_person": (
                        "" if person.dossier is None else person.dossier.why_this_person_instead_of_another
                    ),
                    "sources": ", ".join(person.source_urls),
                },
            )
        for opp in run.opportunities:
            deps.sheets.append(
                "OPPORTUNITIES",
                {
                    "id": opp.id,
                    "use_case": opp.use_case_id,
                    "relevance": opp.relevance,
                    "hypothesis": opp.hypothesis,
                    "supporting_evidence": ", ".join(opp.supporting_evidence_ids),
                    "contradicting_evidence": ", ".join(opp.contradicting_evidence_ids),
                    "unknowns": " | ".join(opp.unknowns),
                    "alternatives": ", ".join(opp.alternatives),
                    "falsifier": opp.falsifier,
                    "is_primary": str(opp.is_primary).lower(),
                },
            )
        if rec is not None:
            deps.sheets.append(
                "ACTIONS",
                {
                    "action_id": run.action_id or "",
                    "person": rec.person,
                    "channel": rec.channel or "",
                    "template": rec.template_id or "",
                    "status": rec.status,
                    "sent": "false",
                    "draft": rec.draft or "",
                },
            )
        for entry in run.logs:
            deps.sheets.append(
                "RESEARCH LOG",
                {"cycle": str(entry.cycle), "node": entry.node, "message": entry.message},
            )
        deps.sheets.append(
            "OUTCOMES",
            {
                "action_id": run.action_id or "",
                "result": "pending",
                "notes": "V1 stores outcomes and does not change ranking.",
                "ranking_updated": "false",
            },
        )
        _log(run, "sheets", "Wrote ACCOUNTS, PEOPLE, OPPORTUNITIES, ACTIONS, RESEARCH LOG, OUTCOMES.")
        return dump_run(run)

    return node
