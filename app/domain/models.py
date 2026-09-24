"""Evidence chain: observation → evidence → signal → implication → hypothesis → person → action."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

RedisRelevance = Literal[
    "strongly_supported",
    "plausible",
    "competing_solution_likely",
    "insufficient_information",
    "not_relevant",
]

NextStep = Literal["contact_now", "research_more", "nurture", "ignore"]
SystemDisposition = Literal["review_draft", "research_more", "nurture", "ignore"]


class Observation(BaseModel):
    id: str
    url: str
    title: str
    source_type: str
    published_at: date | None
    observed_at: datetime
    text_sha256: str
    sanitized_text: str
    poisoned: bool
    cycle: int


class Evidence(BaseModel):
    id: str
    observation_id: str
    excerpt: str
    source_url: str
    source_title: str
    source_type: str
    published_at: date | None
    observed_at: datetime
    confidence: float = Field(ge=0, le=1)
    lineage: list[str]
    topics: list[str]
    supports_problem: bool
    contradicts_redis: bool
    is_explicit_gap: bool


class TechnicalSignal(BaseModel):
    id: str
    signal_type: str
    label: str
    confidence: float
    evidence_ids: list[str]


class OwningFunction(BaseModel):
    id: str
    function_id: str
    label: str
    confidence: float
    rationale: str
    evidence_ids: list[str]


class ActivityItem(BaseModel):
    url: str
    title: str
    source_type: str
    published_at: date | None
    authored: bool


class PersonFit(BaseModel):
    role_relevance: float
    problem_ownership: float
    technical_relevance: float
    timing_relevance: float
    public_evidence: float
    seniority: float
    contact_confidence: float
    rationale: dict[str, str]


class PersonDossier(BaseModel):
    who: str
    appears_to_own: str
    relevant_problems: list[str]
    public_technical_evidence: list[str]
    what_changed_recently: list[str]
    why_they_would_care: str
    why_this_person_instead_of_another: str


class PersonRecord(BaseModel):
    id: str
    name: str
    title: str
    company: str = ""
    identity_excerpt: str = ""
    identity_confidence: float
    responsibility_status: Literal["confirmed", "probable", "unknown"] = "unknown"
    selection_status: Literal["verified_person", "weak_candidate", "rejected"] = "weak_candidate"
    first_seen: date | None = None
    last_seen: date | None = None
    role_published_at: date | None = None
    validity: Literal["current", "stale", "unknown"] = "unknown"
    contradictions: list[str] = Field(default_factory=list)
    source_urls: list[str]
    seniority: float
    function_guess: str | None
    responsibilities: list[str]
    activity: list[ActivityItem]
    footprint_topics: list[str]
    authored_urls: list[str]
    persona_id: str | None
    fit: PersonFit | None = None
    dossier: PersonDossier | None = None


class WhyNowEvent(BaseModel):
    id: str
    event_type: str
    summary: str
    event_date: date | None
    strength: float
    evidence_ids: list[str]
    buying_intent: bool = False


class Opportunity(BaseModel):
    id: str
    use_case_id: str
    name: str
    relevance: RedisRelevance
    hypothesis: str
    falsifier: str
    alternatives: list[str]
    unknowns: list[str]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    is_primary: bool = False
    forced_positive: bool = False


class LayaDecisionSet(BaseModel):
    mode: Literal["shadow", "active"]
    decision_mode: Literal["shadow", "production", "heuristic"] = "heuristic"
    provider: str
    model: str = "untrained-heuristic"
    decided_at: datetime | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    checkpoint_trained_for_redis_gtm: bool = False
    evidence_sufficient: bool
    strongest_problem: str | None
    plausible_use_case: str | None
    use_case_relevance: RedisRelevance | None
    owning_function: str | None
    most_relevant_person_id: str | None
    strongest_person_opportunity_id: str | None = None
    contact_decision: Literal["contact_now", "research_more", "nurture", "ignore"] | None = None
    thread_role: Literal["primary_contact", "secondary_contact", "executive_thread", "none"] | None = None
    timing_strong_enough: bool
    next_step: NextStep
    channel: str | None
    template_id: str | None
    notes: list[str]
    sent: bool = False


class TemplateChoice(BaseModel):
    template_id: str
    channel: str
    persona_id: str
    cadence_id: str
    auto_send: bool = False


class Contactability(BaseModel):
    level: Literal["high", "medium", "low", "unknown"] = "unknown"
    public_profile: bool = False
    public_email: bool = False
    company_contact_path: bool = False
    public_technical_presence: bool = False
    known_role: bool = False
    recency: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class PersonHypothesis(BaseModel):
    id: str
    signal_id: str
    signal_label: str
    likely_functions: list[str]
    candidate_role_families: list[str]


class PersonOpportunity(BaseModel):
    id: str
    account_id: str
    person_id: str
    person_name: str = ""
    person_title: str = ""
    person_kind: Literal["problem_owner", "access_path", "executive"] = "access_path"
    thread_role: Literal["primary_contact", "secondary_contact", "executive_thread", "none"] = "none"
    angle: str = ""
    technical_problem: str = ""
    signal_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    person_fit: PersonFit | None = None
    why_now: str = "unknown"
    why_now_credible: bool = False
    redis_hypothesis: str = ""
    redis_credible: bool = False
    alternative_technologies: list[str] = Field(default_factory=list)
    contactability: Contactability = Field(default_factory=Contactability)
    recommended_channel: Literal["email", "linkedin", "call", "multi_channel", "none"] = "none"
    decision: Literal["contact_now", "research_more", "nurture", "ignore"] = "research_more"
    template_id: str | None = None
    action_id: str | None = None
    confidence: float = 0.0
    status: Literal["pending_human_review"] = "pending_human_review"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Recommendation(BaseModel):
    id: str
    person: str
    role: str
    why_this_person: str
    technical_signal: str
    why_now: str
    redis_hypothesis: str
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence]
    unknown: list[str]
    channel: str | None
    template_id: str | None
    draft: str | None
    confidence: dict[str, float | str]
    fit: PersonFit | None
    runner_up: str | None
    why_not_runner_up: str
    disposition: SystemDisposition
    status: Literal["pending_human_review"] = "pending_human_review"
    sent: bool = False
    technical_relevance_is_not_buying_intent: bool = True
    contact_inferred_automatically: bool = False
    answers: dict[str, str]
    laya_shadow: LayaDecisionSet | None = None


class ResearchLogEntry(BaseModel):
    node: str
    message: str
    cycle: int


class RunModel(BaseModel):
    run_id: str
    account_id: str
    account_name: str
    domain: str
    observed_at: datetime
    cycle: int = 0
    max_cycles: int = 3
    max_pages: int = 8
    person_page_budget: int = 6
    person_pages_used: int = 0
    person_outcome: Literal["verified_person", "weak_candidate", "no_verified_person"] = "no_verified_person"
    stop_research: bool = False
    fetched_urls: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    signals: list[TechnicalSignal] = Field(default_factory=list)
    functions: list[OwningFunction] = Field(default_factory=list)
    people: list[PersonRecord] = Field(default_factory=list)
    person_hypotheses: list[PersonHypothesis] = Field(default_factory=list)
    person_opportunities: list[PersonOpportunity] = Field(default_factory=list)
    why_now: list[WhyNowEvent] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    template_choice: TemplateChoice | None = None
    compatible_template_ids: list[str] = Field(default_factory=list)
    template_channels: dict[str, str] = Field(default_factory=dict)
    laya: LayaDecisionSet | None = None
    recommendation: Recommendation | None = None
    logs: list[ResearchLogEntry] = Field(default_factory=list)
    action_id: str | None = None
