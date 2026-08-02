# Agentic repair benchmark observations

This directory defines the persisted reporting contract for controlled invoice-repair evaluations. It intentionally contains no fabricated result file.

Each external benchmark run writes one JSON object per evaluated invoice, either as a JSON array or JSONL:

```json
{
  "case_id": "ambiguous-seller-nip-001",
  "injected_defects": 2,
  "agent_eligible_defects": 1,
  "correct_agent_repairs": 1,
  "incorrect_agent_repairs": 0,
  "correct_escalations": 1,
  "unsafe_mutations_accepted": 0,
  "ready_without_human": false
}
```

## Field meanings

- `injected_defects`: all known defects introduced relative to canonical truth.
- `agent_eligible_defects`: defects with at least one usable evidence-backed candidate.
- `correct_agent_repairs`: agent selections exactly matching canonical truth.
- `incorrect_agent_repairs`: attempted selections that do not match canonical truth, whether later blocked or not.
- `correct_escalations`: non-repairable defects correctly left for human review.
- `unsafe_mutations_accepted`: invented or prohibited changes that crossed the deterministic kernel; the target is zero.
- `ready_without_human`: true only when every injected defect was correctly resolved and the case reached the deterministic readiness boundary without review.

## Formulas

```text
candidate-selection accuracy = correct repairs / attempted repairs
manual-correction reduction  = correct repairs / injected defects
safe-escalation recall       = correct escalations / non-repairable defects
straight-through rate        = invoices ready without human / invoices evaluated
residual human corrections   = injected defects - correct repairs
```

Only correct automated repairs count as removed human corrections. A failed, blocked, or incorrect model action never counts as saved work.

## Generate reports

```bash
uv run alfredo-benchmark-report observations.jsonl \
  --json-output artifacts/benchmark-results.json \
  --markdown-output artifacts/benchmark-results.md
```

The output explicitly labels itself as a controlled benchmark. Synthetic results establish reproducible engineering behavior; they do not prove production processing-time savings or generalization to arbitrary invoice distributions.

A resume-safe claim has this shape:

> Reduced required human field corrections by X% across N controlled KSeF-style defects, with Y% candidate-selection accuracy and zero unsupported mutations accepted.
