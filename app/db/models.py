"""Normalized application tables. Redis is not used as a datastore."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchRunRow(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(40))
    cycle_count: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search_provider: Mapped[str] = mapped_column(String(40))
    laya_mode: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObservationRow(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(80))
    published_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text_sha256: Mapped[str] = mapped_column(String(64))
    poisoned: Mapped[bool] = mapped_column(Boolean, default=False)
    cycle: Mapped[int] = mapped_column(Integer)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    excerpt: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(80))
    published_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float)
    lineage_json: Mapped[str] = mapped_column(Text)
    topics_json: Mapped[str] = mapped_column(Text)
    supports_problem: Mapped[bool] = mapped_column(Boolean)
    contradicts_redis: Mapped[bool] = mapped_column(Boolean)
    is_explicit_gap: Mapped[bool] = mapped_column(Boolean)


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    signal_type: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_ids_json: Mapped[str] = mapped_column(Text)


class OwningFunctionRow(Base):
    __tablename__ = "owning_functions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    function_id: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text)


class PersonRow(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")
    identity_confidence: Mapped[float] = mapped_column(Float)
    persona_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    seniority: Mapped[float] = mapped_column(Float, default=0)
    role_relevance: Mapped[float] = mapped_column(Float, default=0)
    problem_ownership: Mapped[float] = mapped_column(Float, default=0)
    technical_relevance: Mapped[float] = mapped_column(Float, default=0)
    timing_relevance: Mapped[float] = mapped_column(Float, default=0)
    public_evidence: Mapped[float] = mapped_column(Float, default=0)
    contact_confidence: Mapped[float] = mapped_column(Float, default=0)
    dossier_json: Mapped[str] = mapped_column(Text, default="{}")
    source_urls_json: Mapped[str] = mapped_column(Text, default="[]")


class WhyNowRow(Base):
    __tablename__ = "why_now"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    event_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    strength: Mapped[float] = mapped_column(Float)
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    buying_intent: Mapped[bool] = mapped_column(Boolean, default=False)


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    use_case_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(Text)
    relevance: Mapped[str] = mapped_column(String(40))
    hypothesis: Mapped[str] = mapped_column(Text)
    falsifier: Mapped[str] = mapped_column(Text)
    alternatives_json: Mapped[str] = mapped_column(Text)
    unknowns_json: Mapped[str] = mapped_column(Text)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text)
    contradicting_evidence_ids_json: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class LayaDecisionRow(Base):
    __tablename__ = "laya_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    mode: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(80))
    checkpoint_trained_for_redis_gtm: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text)


class RecommendationRow(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    person_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(Text)
    why_this_person: Mapped[str] = mapped_column(Text)
    technical_signal: Mapped[str] = mapped_column(Text)
    why_now: Mapped[str] = mapped_column(Text)
    redis_hypothesis: Mapped[str] = mapped_column(Text)
    unknowns_json: Mapped[str] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    answers_json: Mapped[str] = mapped_column(Text)
    brief_json: Mapped[str] = mapped_column(Text)


class ActionRow(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"))
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    draft: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchLogRow(Base):
    __tablename__ = "research_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    node: Mapped[str] = mapped_column(String(80))
    cycle: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)


class OutcomeRow(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"))
    result: Mapped[str] = mapped_column(String(80), default="pending")
    notes: Mapped[str] = mapped_column(Text, default="")
    ranking_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
