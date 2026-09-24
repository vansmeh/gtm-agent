"""Infer the likely owning function from ownership and hiring evidence."""

import uuid

from app.domain.models import Evidence, OwningFunction


def detect_functions(evidence: list[Evidence]) -> list[OwningFunction]:
    functions: list[OwningFunction] = []
    platform = [
        item
        for item in evidence
        if set(item.topics) & {"ownership_platform", "reports_platform", "hiring_platform"}
    ]
    if platform:
        owned = [item for item in platform if "ownership_platform" in item.topics or "reports_platform" in item.topics]
        confidence = 0.82 if owned else 0.48
        rationale = (
            "Sources describe platform engineering as owning or hiring for the search path."
            if owned
            else "A platform hiring post exists without an ownership statement."
        )
        functions.append(
            OwningFunction(
                id=str(uuid.uuid4()),
                function_id="platform_engineering",
                label="Platform Engineering",
                confidence=confidence,
                rationale=rationale,
                evidence_ids=[item.id for item in platform],
            )
        )
    ml = [item for item in evidence if "hiring_ml" in item.topics]
    if ml:
        functions.append(
            OwningFunction(
                id=str(uuid.uuid4()),
                function_id="ml_infrastructure",
                label="ML Infrastructure",
                confidence=0.4,
                rationale="An ML infrastructure hiring post exists. It does not say this team owns search retrieval.",
                evidence_ids=[item.id for item in ml],
            )
        )
    functions.sort(key=lambda item: item.confidence, reverse=True)
    return functions
