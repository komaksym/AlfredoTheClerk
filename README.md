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
