# AlfredoTheClerk

[![CI](https://github.com/komaksym/AlfredoTheClerk/actions/workflows/ci.yml/badge.svg)](https://github.com/komaksym/AlfredoTheClerk/actions/workflows/ci.yml)

Evidence-constrained invoice repair for KSeF FA(3).

Alfredo extracts a supported legacy invoice PDF into a canonical domestic VAT
shell, repairs only fields supported by source evidence, sends ambiguous fields
to a human, validates the result, and exports FA(3) XML.

```text
PDF invoice
  -> deterministic extraction
  -> evidence-constrained repair
  -> human review when needed
  -> local correctness checks
  -> FA(3) XML
```

## Application

### Upload an invoice

![Upload invoice screen](docs/screenshots/upload-invoice.png)

### Review unresolved fields

![Human invoice review screen](docs/screenshots/human-review.png)

The review workspace keeps the original PDF visible, shows accepted automated
changes as a read-only audit trail, and exposes only unresolved fields for human
correction.

## Evaluation

Latest merged-code regression:

- commit: `3227d2c`
- model: `deepseek:deepseek-v4-flash`
- corpus: `agentic-repair-hard-v1`
- runs: 30 cases × 3 repeats

| Metric | Result | Definition |
| --- | ---: | --- |
| Repair precision | **96.6%** · 85/88 | Correct repairs among attempted repairs |
| Repair coverage | **91.7%** · 88/96 | Repairable fields the agent attempted |
| Safe-escalation rate | **100.0%** · 9/9 | Ambiguous fields correctly sent to a human |
| Field-decision accuracy | **89.5%** · 94/105 | Correct repairs and correct escalations across all agent fields |
| Manual-correction reduction | **57.8%** · 85/147 | Known defects removed from the human queue |
| Straight-through rate | **50.0%** · 45/90 | Case-runs completed without human correction |

The hard corpus is a **development regression set**, not an untouched held-out
benchmark: its cases were inspected while designing safe abstention. These
numbers demonstrate controlled behavior on synthetic data, not production
generalization or accountant time savings.

## Run locally

Requirements: Python 3.13, `uv`, and a DeepSeek API key.

```bash
uv sync --locked
export DEEPSEEK_API_KEY="..."
uv run python -m src.review_ui
```

Open `http://127.0.0.1:8000`.

The local app does not automatically submit invoices to KSeF. Model-bound field
evidence is sent to the configured DeepSeek API when agent repair is required.

## Supported input

The current UI accepts one single-page, native-text Polish domestic VAT invoice
PDF. Scans, photos, OCR, multi-page documents, correction invoices, advance
invoices, and arbitrary layouts are outside this implementation slice.

## Safety boundary

- The model may select only existing extracted candidates; it cannot invent a
  replacement value.
- Every agent field receives exactly one explicit `repair` or `human_review`
  decision in a single tool call.
- Repairs are applied atomically. Unresolved fields remain in human review, and
  automated and human changes pass through the same correctness pipeline.
- A successful local result must pass shell validation, totals reconciliation,
  FA(3) mapping, and XSD validation before XML download is enabled.

## Validate

```bash
uv run ruff check .
uv run pyright src tests
uv run pytest -q -m "not browser_e2e and not ksef_live"
uv run playwright install chromium
uv run pytest -q -m browser_e2e
uv build --wheel
```

A separate strict CI job submits a synthetic invoice to KSeF TEST using repository
secrets. Missing credentials or a rejected submission fail the gate.
