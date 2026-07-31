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
It does not submit invoices to KSeF.

### Run

Install/sync dependencies, provide the repair-agent keys, and start the local
server:

```bash
uv sync --locked
export DEEPSEEK_API_KEY="..."
export LANGSMITH_API_KEY="..."
uv run python -m src.review_ui
```

Open `http://127.0.0.1:8000`.

When either key is missing, the existing model configuration prompts for it in
the terminal. Do not commit keys or put them in invoice/review data.

### Supported input

The review UI currently accepts one ordinary Polish domestic VAT invoice as a
single-page, native/text-based PDF. Scans, OCR, photos, multi-page PDFs,
correction invoices, advance invoices, non-domestic invoices, and arbitrary PDF
layouts are outside this slice.

### Repair boundary

The agent receives only fields with usable extracted candidates and may only
promote one of those existing values. It cannot invent replacements or edit
`summary.*` source totals. Fields with no legal candidate go directly to human
review; mixed invoices let the agent repair its safe subset first.

The human-review screen shows the original invoice beside unresolved fields,
keeps successful agent changes as a read-only diff, and allows the reviewer to
select an extracted candidate or enter an explicit canonical correction. Human
changes are applied as one attributed batch and rerun through the same
correctness pipeline.

A successful local run ends at `READY_FOR_KSEF` with downloadable FA(3) XML.
Remote KSeF submission remains an explicit separate capability.

## Validation

Repository gates:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
```

The CI build also builds the wheel and smoke-tests the installed FA(3) schema
bundle.
