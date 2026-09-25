---
name: run-and-verify
description: Use when testing the GTM agent or running the synthetic Acme AI demo.
---

# Run and verify

```bash
source .venv/bin/activate
pytest
ruff check app tests
mypy
python -m app.demo
```

The Acme AI demo must select a person from fixture evidence. Do not hard-code that person in `app/person`, `app/graph`, `app/signals`, `app/opportunity`, `app/laya`, or `app/research`.

Expect a pending human review, `sent=false`, a plausible Redis hypothesis, contradicting evidence where an incumbent is named, and quarantined injection text producing no person.
