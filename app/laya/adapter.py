"""Ask Laya nine separate questions and clamp answers to the evidence case."""

from typing import Literal

from app.domain.models import LayaDecisionSet, RedisRelevance, RunModel
from app.laya.decisions import (
    SYSTEM_PROMPT,
    ChannelDecision,
    DecisionCase,
    EvidenceSufficientDecision,
    NextStepDecision,
    OwningFunctionDecision,
    PersonDecision,
    RedisUseCaseDecision,
    ShadowHeuristicLLM,
    StrongestProblemDecision,
    TemplateDecision,
    TimingDecision,
)
from app.laya.llm import LLMClient
from app.signals.detection import PROBLEM_SIGNAL_TYPES

_RELEVANCE_RANK = {
    "not_relevant": 0,
    "insufficient_information": 1,
    "competing_solution_likely": 2,
    "plausible": 3,
    "strongly_supported": 4,
}


class LayaAdapter:
    def __init__(self, client: LLMClient, *, mode: str = "shadow") -> None:
        self.client = client
        self.mode = mode if mode in {"shadow", "active"} else "shadow"

    def decide(self, run: RunModel) -> LayaDecisionSet:
        case = build_case(run)
        payload = case.model_dump_json()
        notes: list[str] = [
            "Laya checkpoint_trained_for_redis_gtm is false.",
            "Excerpts were passed as data inside the structured case.",
        ]
        sufficient = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=EvidenceSufficientDecision
        )
        problem = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=StrongestProblemDecision
        )
        use_case = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=RedisUseCaseDecision
        )
        function = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=OwningFunctionDecision
        )
        person = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=PersonDecision
        )
        timing = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=TimingDecision
        )
        step = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=NextStepDecision
        )
        channel = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=ChannelDecision
        )
        template = self.client.complete_structured(
            system=SYSTEM_PROMPT, user=payload, schema=TemplateDecision
        )

        problem_id = problem.problem_id if problem.problem_id in case.problem_ids else None
        if problem.problem_id and problem_id is None:
            notes.append("Rejected problem id that was not in the case.")
        function_id = function.function_id if function.function_id in case.function_ids else None
        if function.function_id and function_id is None:
            notes.append("Rejected function id that was not in the case.")
        person_id = person.person_id if person.person_id in case.person_ids else None
        if person.person_id and person_id is None:
            notes.append("Rejected person id that was not in the case.")
        template_id = template.template_id if template.template_id in case.template_ids else None
        if template.template_id and template_id is None:
            notes.append("Rejected template id that was not an approved compatible template.")

        relevance = use_case.relevance
        use_case_id = use_case.use_case_id
        known = {str(row["id"]): str(row["relevance"]) for row in case.use_cases}
        if use_case_id not in known:
            use_case_id = None
            relevance = None
            if use_case.use_case_id:
                notes.append("Rejected use case that was not in the catalog assessment.")
        elif relevance is not None and use_case_id is not None:
            assessed = known[use_case_id]
            if _RELEVANCE_RANK[relevance] > _RELEVANCE_RANK.get(assessed, 0):
                notes.append(f"Clamped use-case relevance from {relevance} to {assessed}.")
                relevance = _as_known(assessed)

        allowed_channels = set(case.template_channels.values())
        chosen_channel = channel.channel if channel.channel in allowed_channels else None
        if channel.channel and chosen_channel is None:
            notes.append("Rejected a channel that no compatible template uses.")

        mode: Literal["shadow", "active"] = "shadow" if self.mode != "active" else "active"
        return LayaDecisionSet(
            mode=mode,
            provider=self.client.name,
            checkpoint_trained_for_redis_gtm=False,
            evidence_sufficient=sufficient.sufficient,
            strongest_problem=problem_id,
            plausible_use_case=use_case_id,
            use_case_relevance=relevance,
            owning_function=function_id,
            most_relevant_person_id=person_id,
            timing_strong_enough=timing.strong_enough,
            next_step=step.next_step,
            channel=chosen_channel,
            template_id=template_id,
            notes=notes,
            sent=False,
        )


def build_case(run: RunModel) -> DecisionCase:
    problems = [item.signal_type for item in run.signals if item.signal_type in PROBLEM_SIGNAL_TYPES]
    summaries: list[dict[str, float | str]] = []
    for person in run.people:
        fit = person.fit
        summaries.append(
            {
                "id": person.id,
                "problem_ownership": 0.0 if fit is None else fit.problem_ownership,
                "technical_relevance": 0.0 if fit is None else fit.technical_relevance,
                "public_evidence": 0.0 if fit is None else fit.public_evidence,
                "seniority": 0.0 if fit is None else fit.seniority,
            }
        )
    use_cases: list[dict[str, str | int]] = [
        {
            "id": item.use_case_id,
            "relevance": item.relevance,
            "supporting": len(item.supporting_evidence_ids),
        }
        for item in run.opportunities
    ]
    return DecisionCase(
        evidence_count=len(run.evidence),
        source_count=len({item.source_url for item in run.evidence}),
        signal_ids=[item.signal_type for item in run.signals],
        problem_ids=problems,
        function_ids=[item.function_id for item in run.functions],
        person_ids=[item.id for item in run.people],
        person_summaries=summaries,
        use_cases=use_cases,
        why_now_types=[item.event_type for item in run.why_now],
        template_ids=list(run.compatible_template_ids),
        template_channels=dict(run.template_channels),
    )


def _as_known(value: str) -> RedisRelevance | None:
    allowed: tuple[RedisRelevance, ...] = (
        "strongly_supported",
        "plausible",
        "competing_solution_likely",
        "insufficient_information",
        "not_relevant",
    )
    for item in allowed:
        if item == value:
            return item
    return None


def default_kernel(mode: str) -> LayaAdapter:
    return LayaAdapter(ShadowHeuristicLLM(), mode=mode)
