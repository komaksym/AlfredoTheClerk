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
-> exact-label deterministic repair when uniquely proven
-> optional evidence-constrained agent repair when ambiguity remains
   -> safe selection -> shared correctness pipeline
   -> abstain/fail   -> human review
-> READY_FOR_KSEF -> download FA(3) XML
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

Three deliberately broken smoke fixtures are available under
`data/synthetic_data`:

- `BROKEN_agent_ambiguous_seller_nip.pdf` contains competing seller-NIP
  candidates; the unique literal `NIP:` evidence is resolved deterministically.
- `BROKEN_human_missing_buyer_nip.pdf` has no buyer-NIP candidate and requires a
  manual correction; its intended buyer NIP is `5423511615`.
- `BROKEN_mixed_agent_and_human_nips.pdf` automatically repairs seller NIP
  `8637940261`, then asks the reviewer to enter buyer NIP `5423511615`.

### Repair boundary

The agent receives only fields with usable extracted candidates and may only
promote one of those existing values. It cannot invent replacements or edit
`summary.*` source totals. Tool use is optional: when the supplied evidence does
not safely distinguish candidates, the model must abstain and the invoice moves
to human review without promoting a value. Fields with no legal candidate go
directly to human review.

Accepted automated repairs record truthful provenance as either
`Deterministic rule` or `Agent`; deterministic work is never counted as a model
tool call. The human-review screen shows the original invoice beside unresolved
fields, keeps successful automated changes as a read-only diff, and allows the
reviewer to select an extracted candidate or enter an explicit canonical
correction. Human changes are applied as one attributed batch and rerun through
the same correctness pipeline. Source-total mismatches keep their extracted
totals immutable while exposing the canonical line-item inputs that determine
those totals.

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

The benchmark separates two persisted datasets with different purposes:

- `agentic_repair_hard_v1.json` contains 30 separately authored held-out cases
  and is the only corpus accepted by the headline benchmark CLI;
- `agentic_repair_v1.json` contains 200 deterministically generated cases and is
  retained as reproducible tool-contract and scoring sanity coverage.

The held-out hard split contains 12 single-field repair cases, six multi-field
cases, six mixed agent-plus-human cases, three human-only cases, and three
ambiguous cases whose expected action is abstention. Its candidate metadata does
not expose rule names or rejection flags. Correct answers occur at every
candidate position and at high, middle, and low confidence ranks.

The generated 200-case split is not eligible for headline metrics because its
visible evidence and ground truth originate from the same generation rules. It
remains useful for deterministic regression coverage and byte-for-byte corpus
regeneration checks.

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

Scoring requires the exact Cartesian product of every selected case and every
configured repeat. A missing case-run aborts report generation instead of
silently publishing metrics from a partial subset.

### Run the live benchmark

Provide the same DeepSeek key used by the repair agent, then run three complete
repeats:

```bash
export DEEPSEEK_API_KEY="..."
uv run python -m src.agentic_repair.benchmark_runner \
  --runs 3 \
  --max-error-rate 0.05 \
  --json-out reports/agentic-repair-benchmark.json \
  --markdown-out reports/agentic-repair-benchmark.md
```

Use `--limit 5` for a small credential and integration smoke run. The CLI writes
both diagnostic reports before checking publication eligibility. It exits
nonzero when all model-evaluated attempts fail or when the model-attempt error
rate exceeds the configured threshold. Human-only cases are excluded from that
error-rate denominator.

The `Agentic repair benchmark` GitHub Actions workflow runs the complete 30-case
held-out split automatically on every push and on pull requests whose branch is
inside this repository. Automatic runs use three repeats; manual dispatch remains
available for a custom repeat count. Concurrent push and pull-request events for
the same branch are deduplicated, fork pull requests are skipped because GitHub
does not expose repository secrets to them, and diagnostic JSON/Markdown reports
are uploaded even when the benchmark itself fails after starting.

This controlled synthetic result does not establish production generalization,
accountant speed, cost savings, or end-to-end accounts-payable cycle-time
improvement. Those claims require an untouched real-invoice evaluation set or a
human timing study.

## Validation

Repository gates:

```bash
uv run ruff check .
uv run pyright src tests
uv run pytest -q -m "not browser_e2e and not ksef_live"
uv run playwright install chromium
uv run pytest -q -m browser_e2e
uv run python -m compileall src tests
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py \
  dist/alfredotheclerk-*.whl
```

Pyright checks the full `src` and `tests` trees in basic mode. The configuration
contains a narrow explicit ignore list for known pre-existing type debt; all new
and modified files remain inside the gate.

CI runs the gates in lint → typecheck → tests → browser E2E → screenshot → build
order. The Playwright test uploads a PDF, focuses and fills the manual correction,
verifies JavaScript selected the correct hidden mode, uses the PDF download and
fullscreen controls, submits through the visible button, reaches
`READY_FOR_KSEF`, and downloads the generated XML.

CI also captures normal and forced-dark Chrome screenshots and uploads them as
the `human-review-browser-smoke` artifact, builds the wheel, and smoke-tests the
installed FA(3) schema and packaged UI resources.

### Strict KSeF TEST gate

Every push, pull request, and manual workflow run executes a real synthetic
invoice submission to KSeF TEST after the local `main` job succeeds. The
`ksef-live` job requires `KSEF_TEST_TOKEN` and `KSEF_TEST_CONTEXT_NIP`; missing
credentials, transport failures, rejection, or timeout fail CI rather than
skipping the proof. Each invoice number is unique to avoid duplicate collisions.
Fork pull requests cannot pass unless GitHub makes the required repository
secrets available, which is intentional for this strict gate.
