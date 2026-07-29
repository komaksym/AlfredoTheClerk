# CURRENT IMPLEMENTATION SPEC

This file is the ground truth for the current implementation sequence. Update it
when work is completed, reprioritized, or materially re-scoped.

`ROADMAP.md` defines durable product direction. `AGENTS.md` defines development
and repository rules.

## Completed in this PR

### Fix `build_repair_model()`

`src/agentic_repair/config.py` now returns the chat model object rather than a
one-element tuple.

Acceptance:

- the existing model-configuration tests pass
- the returned object can be passed directly into the repair workflow

### Post-repair correctness pipeline

`src/invoice_gen/invoice_correctness.py` now provides one shared correctness
pipeline for every unchanged or repaired invoice, and repair orchestration
requires its successful result before returning an accepted shell:

`unchanged or repaired shell`

`-> full shell validation`

`-> recompute monetary summary`

`-> reconcile against extracted PDF totals`

`-> map to FA(3)`

`-> serialize XML`

`-> XSD validation`

Requirements:

- do not mark a repair as ready merely because field-level shell validation
  passes
- recompute line, VAT-bucket, and invoice totals deterministically from the
  repaired shell
- compare computed totals with totals extracted from the source PDF
- keep extracted totals as evidence; do not allow the model to invent or edit
  totals directly
- stop and return a structured failure or review outcome when reconciliation,
  mapping, serialization, or XSD validation fails
- expose one reusable correctness function for both agent and human repairs
- run the shared correctness function even when deterministic routing finds no
  repair work
- retain the original repair context, including extraction evidence and
  diagnostics, on every workflow outcome
- load the FA(3) schemas from installed package resources rather than the source
  repository layout

Expected result states:

- `READY_FOR_KSEF`
- `INVALID_SHELL`
- `TOTALS_MISMATCH`
- `FA3_MAPPING_FAILED`
- `XML_SERIALIZATION_FAILED`
- `XSD_VALIDATION_FAILED`

Acceptance:

- unchanged and repaired invoices are accepted only after the same complete
  pipeline succeeds
- repaired line items and extracted invoice totals are explicitly reconciled
- the final XML passes the packaged local FA(3) XSD bundle
- failure states retain enough detail for review and debugging
- manual-review outcomes retain their original extraction context without
  re-extracting the source invoice
- an isolated installed-wheel smoke test proves the production validator can
  load every packaged XSD

### Human-review workflow

`src/agentic_repair/human_review.py` now builds complete review cases for
unresolved or blocking fields, applies attributed human corrections atomically,
retains failed attempts for retry, and resumes the shared correctness pipeline:

`unresolved/blocking fields`

`-> show evidence and candidates`

`-> human selects or edits`

`-> rerun the same correctness pipeline`

`-> produce validated invoice`

Requirements:

- show the current value, validation error, extraction status, evidence region,
  and available candidates for each problem field
- allow a reviewer to select an existing candidate or enter a corrected value
- reject manual and candidate-selected values whose runtime type does not match
  the target canonical shell path before applying any command
- snapshot extraction evidence, diagnostics, validation, extracted totals,
  routing, and correctness when the review case is built so upstream mutation
  cannot change later review decisions or reconciliation evidence
- accept only canonical ASCII line-item indices at repair and review boundaries
  so path aliases cannot target one shell field more than once per batch
- record every human change
- resume the same deterministic correctness pipeline used after agent repair
- do not create a separate, weaker validation path for human-reviewed invoices

Acceptance:

- manual-review outcomes can be resolved and resumed
- successful human repairs produce the same validated invoice artifact as
  successful agent repairs
- failed review attempts remain reviewable and auditable
- incompatible value types produce an audited `INVALID_VALUE_TYPE` issue,
  apply no decisions, and do not call correctness
- mutating the source workflow context after case construction cannot change
  review candidates, diagnostics, validation, or extracted totals

## 1. KSeF TEST submission proof — live proof pending

The TEST-only implementation now covers:

`READY_FOR_KSEF -> token auth -> encrypted online session -> one FA(3)`

`-> poll or reconcile -> ACCEPTED / REJECTED / PENDING / FAILED`

Implemented contracts:

- only complete locally XSD-valid `READY_FOR_KSEF` results may submit
- KSeF HTTP, authentication, cryptography, polling, and cleanup stay under
  `src/ksef/`
- only the fixed KSeF TEST origin exists; no production URL is configurable
- public encryption certificates are discovered dynamically by usage; `21470`
  refreshes the affected key once before submission
- temporary authentication tokens are redeemed at most once; only the access
  token needed by this slice is consumed
- FA(3) XML uses AES-256-CBC with the session key encrypted by the matching KSeF
  RSA certificate
- invoice submission is never blindly retried after an ambiguous response;
  reconciliation matches both invoice hash and invoice number
- ambiguous remote truth stays `PENDING`, including reconciliation failures;
  accepted/rejected truth survives best-effort session-close failure
- secrets are excluded from result representations, diagnostics, and transport
  exception messages
- shared fake-HTTP coverage exercises success, rejection, key rotation,
  one-shot redemption, polling deadlines, malformed responses, reconciliation,
  and cleanup failure
- the `ksef_live` test is explicitly opt-in and ordinary CI cannot submit
  remotely

Remaining acceptance gate:

- run one real synthetic invoice through KSeF TEST and record
  `ACCEPTED + KSeF number`
- Ruff, pytest, compileall, and package build pass for the final revision

Detailed protocol and design rationale:
`docs/superpowers/specs/2026-07-29-ksef-test-submission-proof-design.md`.

## 2. Durable KSeF integration — after the TEST proof

Turn the proven TEST protocol boundary into a recoverable product workflow:

`validated FA(3) XML`

`-> durable submission intent`

`-> submit or reconcile`

`-> persist every status transition`

`-> store KSeF number and UPO`

Requirements:

- persist submission identity, session and invoice references, request metadata,
  remote statuses, and redacted failure history
- resume polling and ambiguous-submission reconciliation after process restarts
- prevent duplicate submissions through durable identity and explicit operator
  recovery
- refresh access tokens safely
- download, validate, and store the invoice or session UPO
- preserve local correctness separately from remote rejection or acceptance
- introduce DEMO or production only through an explicit rollout decision and
  environment enum with internally mapped official origins

Acceptance:

- remotely pending work survives process restart
- accepted invoices retain their KSeF number and verified UPO
- retries and recovery cannot silently create duplicate submissions
- submission and status history remains auditable without exposing secrets

## 3. Real legacy invoices — parallel when data is available

Add real legacy-system invoices whenever they become available:

`real legacy invoice`

`-> annotate ground truth`

`-> measure failures`

`-> add source-specific extraction support`

`-> preserve failures as regression cases`

Requirements:

- keep the synthetic corpus; real invoices supplement it rather than replace it
- begin with invoices from one identifiable accounting or vertical software
  system instead of claiming arbitrary-PDF support
- create manually reviewed canonical shell truth for each evaluation invoice
- keep an untouched evaluation split separate from development cases
- classify failures by parsing, candidate generation, normalization, routing,
  repair, reconciliation, mapping, or validation stage
- convert recurring real failures into stable regression fixtures when legally
  and operationally possible
- add source-specific anchors or extraction logic only when real evidence shows
  they are needed

Acceptance:

- extraction and repair quality are measured on real system output
- each fixed real-world failure remains covered by regression tests
- supported source systems are named explicitly rather than implied through a
  generic reliability claim

## Validation gates

For each implementation change:

- run the narrowest relevant tests first
- run `uv run ruff check src tests`
- run `uv run pytest`
- run `uv run python -m compileall src tests`

For product readiness:

- repaired shell passes full validation
- computed and extracted totals reconcile or receive an explicit review outcome
- FA(3) mapping and XML serialization succeed
- XML passes local XSD validation
- human-reviewed cases use the same correctness gate
- KSeF acceptance is tracked separately from local correctness
- real legacy-system evaluation results are recorded separately from synthetic
  benchmark results
