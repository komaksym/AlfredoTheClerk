# CURRENT IMPLEMENTATION SPEC

This file is the ground truth for the current implementation sequence. Update it
when work is completed, reprioritized, or materially re-scoped.

`ROADMAP.md` defines durable product direction. `AGENTS.md` defines development
and repository rules.

## Completed foundations

### Shared post-repair correctness

`src/invoice_gen/invoice_correctness.py` is the common acceptance boundary for
unchanged, agent-repaired, and human-repaired invoices:

```text
canonical shell
-> full shell validation
-> recompute monetary summary
-> reconcile against extracted PDF totals
-> map to FA(3)
-> serialize XML
-> local XSD validation
-> READY_FOR_KSEF
```

Expected local states remain:

- `READY_FOR_KSEF`
- `INVALID_SHELL`
- `TOTALS_MISMATCH`
- `FA3_MAPPING_FAILED`
- `XML_SERIALIZATION_FAILED`
- `XSD_VALIDATION_FAILED`

Extracted `summary.*` totals are immutable evidence. They are reconciled against
values computed from canonical line items rather than edited by agent or human
repair.

### Human-review backend

`src/agentic_repair/human_review.py` provides retryable review cases, candidate
selection, explicit manual canonical corrections, reviewer attribution, atomic
batch validation/application, decision history, and re-entry into the same
correctness pipeline.

The backend rejects unsupported paths, summary mutation, incompatible runtime
value types, duplicate paths, invalid candidate selections, and unattributed
changes before applying a batch.

### Controlled agentic-repair benchmark

The repository contains two persisted synthetic benchmark corpora with separate
purposes:

- `data/benchmark_cases/agentic_repair_hard_v1.json` contains 30 separately
  authored held-out cases and is the only corpus accepted for headline metrics;
- `data/benchmark_cases/agentic_repair_v1.json` contains 200 deterministically
  generated cases retained for schema, graph/tool-contract, scoring, and
  byte-for-byte regeneration coverage.

The held-out corpus includes single-field, multi-field, mixed agent-plus-human,
human-only, and ambiguous no-action cases. Candidate metadata does not expose
rule names or rejection flags, and correct choices vary across candidate indexes
and confidence ranks. The generated corpus is not eligible for headline claims
because its visible evidence and expected outcomes originate from the same
rules.

The benchmark reports correct automated repairs, incorrect selections, missed
repairs, safe escalation, residual human corrections, straight-through cases,
model errors, and latency. The agent-disabled baseline requires one human
correction per known defect. Only a ground-truth-matching candidate promotion
counts as removed human work.

Scoring requires the complete Cartesian product of selected cases and configured
repeats. The CLI writes diagnostic JSON and Markdown before enforcing publication
eligibility, then exits nonzero when there are no model-evaluated attempts, every
model attempt fails, or the model-attempt error rate exceeds the configured
threshold.

The live DeepSeek run remains a separate manual-only workflow. It accepts a
custom repeat count, requires `DEEPSEEK_API_KEY`, and uploads JSON and Markdown
reports. Ordinary push and pull-request CI does not call DeepSeek or spend model
credits. Synthetic results do not establish production generalization,
accountant speed, AP cost savings, or end-to-end cycle-time improvement.

### KSeF TEST submission proof

The TEST-only KSeF boundary under `src/ksef/` is complete and remains separate
from the local review product:

```text
READY_FOR_KSEF
-> TEST token authentication
-> encrypted online FA(3) session
-> one invoice submission
-> poll or reconcile ambiguous transport outcome
-> ACCEPTED / REJECTED / PENDING / FAILED
```

Implemented properties include TEST-only origin configuration, dynamic public
certificate discovery, key-rotation handling, one-shot token redemption,
AES-256-CBC + RSA-OAEP encryption, duplicate-safe ambiguous-response
reconciliation, bounded polling, best-effort close, secret redaction, fake-HTTP
coverage, and an opt-in `ksef_live` integration test.

A real synthetic TEST submission has been run successfully through the opt-in
workflow. This proof demonstrates the remote protocol boundary; it does not make
durable KSeF orchestration part of the minimal UI product.

## Current slice: local agent-first human-review UI

Design:
`docs/superpowers/specs/2026-07-31-human-review-ui-design.md`

Implementation plan:
`docs/superpowers/plans/2026-07-31-human-review-ui.md`

Pull request: `#7` on branch `feat/human-review-ui`.

### Goal

Make the existing backend usable as a minimal local product:

```text
single-page native-text PDF
-> extraction + evidence + diagnostics
-> deterministic repair routing
-> evidence-constrained agent repair when legal
-> shared correctness
   -> READY_FOR_KSEF -> success + FA(3) XML
   -> unresolved     -> side-by-side human review
                       -> atomic correction batch
                       -> shared correctness
                       -> READY_FOR_KSEF
```

### Runtime boundary

- FastAPI + Jinja + small vanilla JavaScript.
- One process, one local reviewer, one active invoice.
- Bind to `127.0.0.1` only.
- In-memory state only; restart loses the active case.
- No database, queue, accounts, roles, background workers, React/Node build, or
  deployment infrastructure.

### Supported input

- ordinary Polish domestic VAT invoice;
- native/text-based PDF;
- exactly one page;
- current supported extraction layouts only.

Multi-page PDFs, scans, OCR, photos, correction invoices, advance invoices,
non-domestic invoices, and arbitrary PDF reliability remain outside this slice.

### Agent-first repair invariant

A field goes to the agent only when at least one usable evidence-backed candidate
exists. The agent may select candidates but may not invent a value.

- usable candidate exists -> agent gets the first repair opportunity;
- no evidence -> human;
- no candidates -> human;
- all candidate values are `None` -> human;
- `summary.*` -> immutable evidence, never direct repair.

For mixed invoices, the agent repairs the legal subset first. Human review then
contains the residual problems only, while successful agent changes remain
visible in a read-only diff.

Technical agent exceptions are contained as structured `AGENT_FAILED` workflow
results and fall back to human review without mutating the extracted shell.

### Review UI

The review screen is side-by-side:

```text
original rendered PDF + evidence overlays | agent diff + unresolved field cards
```

Each residual field displays available validation/evidence context. The reviewer
may select an extracted candidate or enter a manual canonical value. The browser
accumulates changes and submits one `Review & Validate` batch; browser events do
not mutate the canonical invoice directly.

Failed transport parsing or backend review validation stays on the same review
case with entered values/errors preserved.

Non-field correctness failures such as FA(3), XML, or XSD failure are shown as
explicit local correctness blockers rather than being mistaken for readiness.

### Successful output

`READY_FOR_KSEF` exposes generated FA(3) XML for download. The UI does not submit
to KSeF and has no remote status/UPO controls.

### Acceptance

The slice is complete only when regression coverage and final gates prove:

- known-good PDF -> real extraction -> local `READY_FOR_KSEF`;
- fully agent-repaired -> no human form + visible agent diff;
- mixed agent + human -> agent-fixed fields are audit-only, residual fields are
  editable;
- blocking-only -> human review without an illegal agent action;
- agent technical failure -> warning + human fallback;
- candidate and manual human corrections use the existing atomic backend;
- malformed human input produces display-safe retryable errors with no partial
  mutation;
- successful human review reaches the same correctness boundary and XML output;
- PDF evidence overlays reuse existing bbox geometry;
- invalid, non-text, and multi-page input fail clearly;
- no UI action submits to KSeF;
- package assets and FA(3) schemas work from the built installation.

## Parallel product work: real legacy invoices

When real invoices become available:

```text
real named-system invoice
-> annotate canonical ground truth
-> measure failure stage
-> add evidence-driven source support
-> preserve regression
```

Keep synthetic fixtures as controlled regression data. Add source-specific
anchors or extraction logic only when real evidence justifies them, and keep an
untouched real-invoice evaluation split for product-quality claims.

## Optional later slice: durable KSeF productization

Durable remote orchestration is intentionally not the current priority. A future
explicit slice may add:

- durable submission identity and intent;
- restart-safe polling and ambiguous-response reconciliation;
- duplicate prevention and operator recovery;
- access-token/session lifecycle management;
- persisted remote status/KSeF number;
- UPO download, validation, and storage;
- explicit DEMO/production environment rollout.

Local correctness and remote acceptance must remain separate even if this work
is later promoted into the active plan.

## Validation gates

For implementation changes:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
```

Final handoff also requires wheel build/install resource checks, a local workflow
smoke test to the extent the execution environment permits, and independent PR
diff review before merge approval is requested.
