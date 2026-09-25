import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import (
    AccountRow,
    ActionRow,
    EvidenceRow,
    LayaDecisionRow,
    ObservationRow,
    OpportunityRow,
    OutcomeRow,
    OwningFunctionRow,
    PersonOpportunityRow,
    PersonRow,
    RecommendationRow,
    ResearchLogRow,
    ResearchRunRow,
    SignalRow,
    WhyNowRow,
)
from app.domain.models import RunModel


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


class Store:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_account(self, account_id: str, name: str, domain: str, created_at: datetime) -> None:
        self.session.add(AccountRow(id=account_id, name=name, domain=domain, created_at=created_at))

    def save_run(
        self,
        run: RunModel,
        *,
        search_provider: str,
        laya_mode: str,
        created_at: datetime,
    ) -> None:
        self.session.add(
            ResearchRunRow(
                id=run.run_id,
                account_id=run.account_id,
                status="pending_human_review",
                cycle_count=run.cycle,
                observed_at=run.observed_at,
                search_provider=search_provider,
                laya_mode=laya_mode,
                created_at=created_at,
            )
        )
        for obs in run.observations:
            self.session.add(
                ObservationRow(
                    id=obs.id,
                    run_id=run.run_id,
                    url=obs.url,
                    title=obs.title,
                    source_type=obs.source_type,
                    published_at=obs.published_at.isoformat() if obs.published_at else None,
                    observed_at=obs.observed_at,
                    text_sha256=obs.text_sha256,
                    poisoned=obs.poisoned,
                    cycle=obs.cycle,
                )
            )
        for item in run.evidence:
            self.session.add(
                EvidenceRow(
                    id=item.id,
                    run_id=run.run_id,
                    observation_id=item.observation_id,
                    excerpt=item.excerpt,
                    source_url=item.source_url,
                    source_title=item.source_title,
                    source_type=item.source_type,
                    published_at=item.published_at.isoformat() if item.published_at else None,
                    observed_at=item.observed_at,
                    confidence=item.confidence,
                    lineage_json=json.dumps(item.lineage),
                    topics_json=json.dumps(item.topics),
                    supports_problem=item.supports_problem,
                    contradicts_redis=item.contradicts_redis,
                    is_explicit_gap=item.is_explicit_gap,
                )
            )
        for signal in run.signals:
            self.session.add(
                SignalRow(
                    id=signal.id,
                    run_id=run.run_id,
                    signal_type=signal.signal_type,
                    label=signal.label,
                    confidence=signal.confidence,
                    evidence_ids_json=json.dumps(signal.evidence_ids),
                )
            )
        for function in run.functions:
            self.session.add(
                OwningFunctionRow(
                    id=function.id,
                    run_id=run.run_id,
                    function_id=function.function_id,
                    label=function.label,
                    confidence=function.confidence,
                    rationale=function.rationale,
                    evidence_ids_json=json.dumps(function.evidence_ids),
                )
            )
        for person in run.people:
            fit = person.fit
            self.session.add(
                PersonRow(
                    id=person.id,
                    run_id=run.run_id,
                    name=person.name,
                    title=person.title,
                    company=person.company,
                    identity_excerpt=person.identity_excerpt,
                    identity_confidence=person.identity_confidence,
                    responsibility_status=person.responsibility_status,
                    selection_status=person.selection_status,
                    first_seen=person.first_seen.isoformat() if person.first_seen else None,
                    last_seen=person.last_seen.isoformat() if person.last_seen else None,
                    role_published_at=person.role_published_at.isoformat() if person.role_published_at else None,
                    validity=person.validity,
                    contradictions_json=json.dumps(person.contradictions),
                    persona_id=person.persona_id,
                    seniority=fit.seniority if fit else person.seniority,
                    role_relevance=fit.role_relevance if fit else 0,
                    problem_ownership=fit.problem_ownership if fit else 0,
                    technical_relevance=fit.technical_relevance if fit else 0,
                    timing_relevance=fit.timing_relevance if fit else 0,
                    public_evidence=fit.public_evidence if fit else 0,
                    contact_confidence=fit.contact_confidence if fit else 0,
                    dossier_json=person.dossier.model_dump_json() if person.dossier else "{}",
                    source_urls_json=json.dumps(person.source_urls),
                )
            )
        for opportunity in run.person_opportunities:
            fit_json = "{}" if opportunity.person_fit is None else opportunity.person_fit.model_dump_json()
            self.session.add(
                PersonOpportunityRow(
                    id=opportunity.id,
                    run_id=run.run_id,
                    account_id=opportunity.account_id,
                    person_id=opportunity.person_id,
                    technical_problem=opportunity.technical_problem,
                    signal_ids_json=json.dumps(opportunity.signal_ids),
                    evidence_ids_json=json.dumps(opportunity.evidence_ids),
                    supporting_evidence_ids_json=json.dumps(opportunity.supporting_evidence_ids),
                    contradicting_evidence_ids_json=json.dumps(opportunity.contradicting_evidence_ids),
                    person_fit_json=fit_json,
                    why_now=opportunity.why_now,
                    redis_hypothesis=opportunity.redis_hypothesis,
                    alternative_technologies_json=json.dumps(opportunity.alternative_technologies),
                    contactability_json=opportunity.contactability.model_dump_json(),
                    recommended_channel=opportunity.recommended_channel,
                    decision=opportunity.decision,
                    template_id=opportunity.template_id,
                    action_id=opportunity.action_id,
                    confidence=opportunity.confidence,
                    status=opportunity.status,
                    person_kind=opportunity.person_kind,
                    thread_role=opportunity.thread_role,
                    angle=opportunity.angle,
                    created_at=opportunity.created_at,
                    updated_at=opportunity.updated_at,
                )
            )
        for trace in run.search_traces:
            self.session.add(
                ResearchLogRow(
                    id=str(uuid.uuid4()),
                    run_id=run.run_id,
                    created_at=trace.timestamp,
                    node="search",
                    cycle=run.cycle,
                    message=(
                        f"{trace.provider_mode} {trace.provider} q={trace.query} "
                        f"n={trace.result_count} url={trace.result_url} source={trace.result_source} "
                        f"latency_ms={trace.search_latency_ms:.0f}"
                    ),
                )
            )
        for event in run.why_now:
            self.session.add(
                WhyNowRow(
                    id=event.id,
                    run_id=run.run_id,
                    event_type=event.event_type,
                    summary=event.summary,
                    event_date=event.event_date.isoformat() if event.event_date else None,
                    strength=event.strength,
                    evidence_ids_json=json.dumps(event.evidence_ids),
                    buying_intent=event.buying_intent,
                )
            )
        for opp in run.opportunities:
            self.session.add(
                OpportunityRow(
                    id=opp.id,
                    run_id=run.run_id,
                    use_case_id=opp.use_case_id,
                    name=opp.name,
                    relevance=opp.relevance,
                    hypothesis=opp.hypothesis,
                    falsifier=opp.falsifier,
                    alternatives_json=json.dumps(opp.alternatives),
                    unknowns_json=json.dumps(opp.unknowns),
                    supporting_evidence_ids_json=json.dumps(opp.supporting_evidence_ids),
                    contradicting_evidence_ids_json=json.dumps(opp.contradicting_evidence_ids),
                    is_primary=opp.is_primary,
                )
            )
        if run.laya is not None:
            self.session.add(
                LayaDecisionRow(
                    id=str(uuid.uuid4()),
                    run_id=run.run_id,
                    mode=run.laya.mode,
                    decision_mode=run.laya.decision_mode,
                    provider=run.laya.provider,
                    model=run.laya.model,
                    decided_at=run.laya.decided_at,
                    probabilities_json=json.dumps(run.laya.probabilities),
                    checkpoint_trained_for_redis_gtm=run.laya.checkpoint_trained_for_redis_gtm,
                    payload_json=run.laya.model_dump_json(),
                )
            )
        rec = run.recommendation
        if rec is not None:
            self.session.add(
                RecommendationRow(
                    id=rec.id,
                    run_id=run.run_id,
                    person_name=rec.person,
                    role=rec.role,
                    why_this_person=rec.why_this_person,
                    technical_signal=rec.technical_signal,
                    why_now=rec.why_now,
                    redis_hypothesis=rec.redis_hypothesis,
                    unknowns_json=json.dumps(rec.unknown),
                    channel=rec.channel,
                    template_id=rec.template_id,
                    draft=rec.draft,
                    confidence_json=json.dumps(rec.confidence),
                    status=rec.status,
                    sent=rec.sent,
                    answers_json=json.dumps(rec.answers),
                    brief_json=rec.model_dump_json(),
                )
            )
            if run.action_id:
                self.session.add(
                    ActionRow(
                        id=run.action_id,
                        run_id=run.run_id,
                        recommendation_id=rec.id,
                        channel=rec.channel,
                        template_id=rec.template_id,
                        status=rec.status,
                        sent=False,
                        draft=rec.draft,
                    )
                )
                self.session.add(
                    OutcomeRow(
                        id=str(uuid.uuid4()),
                        action_id=run.action_id,
                        result="pending",
                        notes="Awaiting human review. Rankings are not auto-updated.",
                        ranking_updated=False,
                        recorded_at=created_at,
                    )
                )
        for entry in run.logs:
            self.session.add(
                ResearchLogRow(
                    id=str(uuid.uuid4()),
                    run_id=run.run_id,
                    created_at=created_at,
                    node=entry.node,
                    cycle=entry.cycle,
                    message=entry.message,
                )
            )

    def record_outcome(self, action_id: str, result: str, notes: str, recorded_at: datetime) -> OutcomeRow:
        row = OutcomeRow(
            id=str(uuid.uuid4()),
            action_id=action_id,
            result=result,
            notes=notes,
            ranking_updated=False,
            recorded_at=recorded_at,
        )
        self.session.add(row)
        return row
