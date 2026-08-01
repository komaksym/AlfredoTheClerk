# AlfredoTheClerk

AlfredoTheClerk turns supported legacy-system invoice PDFs into reviewable,
locally validated KSeF FA(3) XML. It keeps invoice data in a canonical domestic
VAT shell, limits automated repair to extracted evidence candidates, and falls
back to human review when automation cannot finish safely.

## Local human-review app

The current local product path is:

```text
single-page native-text PDF
-> deterministic extraction + evidence
-> evidence-constrained agent repair when legal
-> shared correctness pipeline
   -> READY_FOR_KSEF -> download FA(3) XML
   -> unresolved     -> human review -> correctness -> READY_FOR_KSEF
```

The app is intentionally single-user, in-memory, and bound to `127.0.0.1`.
It does not submit invoices to KSeF. Agent repair still calls the configured
DeepSeek API, so model-bound invoice fields and source snippets leave the local
machine when an agent repair is attempted.

### Run

Install/sync dependencies, provide the repair-agent key, and start the local
server:

```bash
uv sync --locked
export DEEPSEEK_API_KEY="..."
uv run python -m src.review_ui
```

The same key can be stored as `DEEPSEEK_API_KEY=...` in a repository-root
`.env`; it is loaded automatically. When the key is missing, startup prompts for
it in the terminal. Do not commit keys or put them in invoice/review data.

LangSmith tracing is not enabled or required by default. To opt in explicitly,
set your own LangSmith environment variables before startup, for example:

```bash
export LANGSMITH_TRACING="true"
export LANGSMITH_API_KEY="..."
```

When tracing is enabled, startup forces LangSmith input, output, and metadata
hiding so invoice payloads are not recorded in traces. Tracing still creates an
outbound observability connection and trace metadata, so enable it only under an
approved data-handling policy.

Open `http://127.0.0.1:8000`.

### Supported input

The review UI currently accepts one ordinary Polish domestic VAT invoice as a
single-page, native/text-based PDF. Scans, OCR, photos, multi-page PDFs,
correction invoices, advance invoices, non-domestic invoices, and arbitrary PDF
layouts are outside this slice.

Two deliberately broken smoke fixtures are available under
`data/synthetic_data`:

- `BROKEN_agent_ambiguous_seller_nip.pdf` routes an ambiguous seller NIP to the
  evidence-constrained agent.
- `BROKEN_human_missing_buyer_nip.pdf` has no buyer-NIP candidate and requires a
  manual correction; its intended buyer NIP is `5423511615`.

### Repair boundary

The agent receives only fields with usable extracted candidates and may only
promote one of those existing values. It cannot invent replacements or edit
`summary.*` source totals. Fields with no legal candidate go directly to human
review; mixed invoices let the agent repair its safe subset first.

The human-review screen shows the original invoice beside unresolved fields,
keeps successful agent changes as a read-only diff, and allows the reviewer to
select an extracted candidate or enter an explicit canonical correction. Human
changes are applied as one attributed batch and rerun through the same
correctness pipeline. Source-total mismatches keep their extracted totals
immutable while exposing the canonical line-item inputs that determine those
totals.

A successful local run ends at `READY_FOR_KSEF` with downloadable FA(3) XML.
Remote KSeF submission remains an explicit separate capability.

## Industry context, not a benchmark baseline

Invoice exceptions are a material accounts-payable bottleneck, but published AP
statistics cover much broader workflows than Alfredo's field-repair boundary.
APQC reports a 12-hour median cycle time from invoice receipt until data entry
across 2,461 organizations. Ardent Partners' 2025 State of ePayables benchmark
reports an average invoice-processing cost of $9.84, an 8.2-day processing time,
and an 18.4% exception rate.

Sources:

- [APQC: cycle time from invoice receipt to system entry](https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/cycle-time-hours-receipt-invoice-until)
- [Ardent Partners: 2025 AP benchmarks](https://payablesplace.ardentpartners.com/2026/01/state-of-epayables-part-nine-ap-benchmarks-and-best-in-class-performance/)

These figures explain the business context only. They include waiting, approvals,
matching, supplier communication, and other AP work, so they are not used as
Alfredo's baseline and are not converted into claimed time or cost savings.

## Controlled synthetic benchmark

The repository includes a persisted 200-case controlled synthetic benchmark for
the agentic decision layer. It measures whether the existing LangGraph agent
selects the ground-truth evidence candidate or safely takes no action. It does
not regenerate cases during evaluation.

The checked-in corpus contains:

- 80 single-field repairable cases;
- 40 multi-field repairable cases;
- 40 mixed agent-plus-human cases;
- 20 human-only cases with no legal agent action; and
- 20 ambiguous cases where the expected safe action is no tool call.

Candidate order and confidence vary. The correct candidate is not tied to a
fixed index or to the highest confidence value.

### Baseline and metrics

The agent-disabled baseline requires one human correction for every persisted
known defect. Only an automated candidate selection that exactly matches ground
truth counts as removed human work. Wrong, missing, or errored actions remain in
the human-work total.

The report publishes:

- **manual-correction reduction** — correct automated repairs divided by all
  known defects;
- **candidate-selection accuracy** — correct automated repairs divided by all
  agent-eligible fields;
- **safe-escalation rate** — ambiguous fields correctly left unchanged divided
  by all safe-escalation opportunities;
- **straight-through rate** — case-runs completed with no residual human
  correction; and
- raw per-case actions, errors, median latency, and p95 latency.

### Run the live benchmark

Provide the same DeepSeek key used by the repair agent, then run three complete
repeats:

```bash
export DEEPSEEK_API_KEY="..."
uv run python -m src.agentic_repair.benchmark_runner \
  --runs 3 \
  --json-out reports/agentic-repair-benchmark.json \
  --markdown-out reports/agentic-repair-benchmark.md
```

Use `--limit 5` for a small credential and integration smoke run. The full run
writes an auditable JSON file and a human-readable Markdown summary. The manual
GitHub Actions workflow uploads both files as the
`agentic-repair-benchmark` artifact.

This controlled synthetic result does not establish production generalization,
accountant speed, cost savings, or end-to-end accounts-payable cycle-time
improvement. Those claims require an untouched real-invoice evaluation set or a
human timing study.

## Validation

Repository gates:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
```

CI additionally:

- captures a headless-Chrome human-fallback screenshot;
- submits the manual correction and captures the resulting `READY_FOR_KSEF`
  screen;
- uploads both screenshots as the `human-review-browser-smoke` artifact;
- builds the wheel; and
- smoke-tests the installed FA(3) schema and packaged UI resources.
