---
name: evidence-person-intelligence
description: Use when changing evidence extraction, person fit, why-now, or Redis relevance.
---

# Evidence and person intelligence

- Every factual claim keeps source URL, title, type, publication date when known, observed date, excerpt, confidence, and lineage.
- Extract excerpts from public text. Do not invent people. Do not scrape LinkedIn.
- Person modules live in `app/person/` and stay separate: discovery, identity, role, responsibility, public activity, technical footprint, triggers, persona, fit, ranking.
- Fit dimensions stay explicit. Ranking must not use seniority as the primary key.
- Opportunities include supporting evidence, contradicting evidence, unknowns, alternatives, and a falsifier.
- Do not upgrade relevance to strongly_supported without an explicit requirement in evidence.
- Why-now does not imply buying intent or an automatic send.
