---
name: gtm-architecture
description: Use when changing the Redis GTM agent architecture, graph, database, or providers.
---

# GTM architecture

- Application state is SQLite/SQLAlchemy. Redis is the GTM product under research, not the database.
- The LangGraph in `app/graph/builder.py` is the only pipeline. Do not add an agent swarm or a CRM.
- Search goes through `SearchProvider`. Fetch goes through `PageFetcher`. Sheets go through `SheetsProvider`.
- Laya is a `DecisionKernel` behind `LLMClient`. Do not call a model vendor from person, signal, or opportunity code.
- Keep research bounded: `max_research_cycles` is 3, with search and page caps on the run.
