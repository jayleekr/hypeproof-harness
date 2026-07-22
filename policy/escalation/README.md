# Human Escalation Queue

An ambiguous case — "neither the big side's nor the small side's, but a
human's" — must not disappear into an `UNKNOWN` bucket. It becomes a first-class
work item here with a named **owner**, and a validator that fails closed if any
pending case is not actually routed to a person.

- **Queue** (data): [`queue.yaml`](queue.yaml)
- **CLI + validator**: [`../../scripts/escalation/escalation.py`](../../scripts/escalation/escalation.py)

## Everyday use

```bash
# Is every pending case owned? (gate — exit 1 if any pending case is unowned)
python3 scripts/escalation/escalation.py validate

python3 scripts/escalation/escalation.py list --status pending
python3 scripts/escalation/escalation.py show ESC-0003

# File a new ambiguous case (refuses empty reason / owner):
python3 scripts/escalation/escalation.py add \
  --reason "…why it's ambiguous…" --human-owner jay \
  --evidence "…" --candidate "classification A" --candidate "classification B"

# Close it (refuses empty resolution):
python3 scripts/escalation/escalation.py resolve ESC-0002 \
  --resolution "confirmed fabricated brand; no third-party issue"
```

## Rules

- `human_owner` is a **role**, never a real name or PII (`jay` = operator,
  `legal-review` = third-party/PIPA judgement).
- No file contents / image bytes / personal records — references, counts, and
  paths only.
- A pending case must have `human_owner`, `created`, `reason`. A resolved case
  must have a non-empty `resolution`. The validator enforces both.

## Wiring as a gate

`escalation.py validate` exits non-zero when a pending case is unowned, so it
can run in CI or the weekly loop as a check. The failure mode this guards
against is an escalation path that exists on paper while nobody looks — the
validator makes "did this reach a human" a measured pending count, not an
assumption.

## Seed

Seeded from the borderline cases M003 had nowhere to put: counterparty-name
2-4× mentions (ESC-0001), demo-page brand reality (ESC-0002), 22 adult photos
without consent basis (ESC-0003), one unconfirmed child photo (ESC-0004),
`_sediment-docs` classification (ESC-0005), workshop directory-level photos
(ESC-0006), and the `dental-studio` `none` classification confirmation
(ESC-0007). ESC-0003/0004/0006/0007 pair with the lab consent manifest.
