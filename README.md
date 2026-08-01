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

Tracing can send agent inputs and outputs—including invoice field values and
extracted source snippets—to LangSmith. Enable it only under an approved data-
handling policy and configure suitable input/output masking for real invoices.

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
