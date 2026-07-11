# CURRENT IMPLEMENTATION SPEC

This file is the ground truth for the current implementation sequence. Update it
when work is completed, reprioritized, or materially re-scoped.

`ROADMAP.md` defines durable product direction. `AGENTS.md` defines development
and repository rules.

## 0. Fix `build_repair_model()` — completed

`src/agentic_repair/config.py` must return the chat model object rather than a
one-element tuple.

Acceptance:

- the existing model-configuration tests pass
- the returned object can be passed directly into the repair workflow

## 1. Post-repair correctness pipeline — next

Complete one shared correctness pipeline for every repaired invoice:

`repaired shell`

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

Expected result states:

- `READY_FOR_KSEF`
- `INVALID_SHELL`
- `TOTALS_MISMATCH`
- `FA3_MAPPING_FAILED`
- `XML_SERIALIZATION_FAILED`
- `XSD_VALIDATION_FAILED`

Acceptance:

- a repaired invoice is accepted only after the complete pipeline succeeds
- repaired line items and extracted invoice totals are explicitly reconciled
- the final XML passes the checked-in local FA(3) XSD bundle
- failure states retain enough detail for review and debugging

## 2. Human-review workflow

Build a review workflow for unresolved or blocking fields:

`unresolved/blocking fields`

`-> show evidence and candidates`

`-> human selects or edits`

`-> rerun the same correctness pipeline`

`-> produce validated invoice`

Requirements:

- show the current value, validation error, extraction status, evidence region,
  and available candidates for each problem field
- allow a reviewer to select an existing candidate or enter a corrected value
- record every human change
- resume the same deterministic correctness pipeline used after agent repair
- do not create a separate, weaker validation path for human-reviewed invoices

Acceptance:

- manual-review outcomes can be resolved and resumed
- successful human repairs produce the same validated invoice artifact as
  successful agent repairs
- failed review attempts remain reviewable and auditable

## 3. KSeF integration

Add the remote KSeF path only for locally validated FA(3) XML:

`validated FA(3) XML`

`-> authenticate`

`-> submit`

`-> poll status`

`-> store KSeF number and UPO`

Requirements:

- keep KSeF access behind a dedicated client interface
- support authentication and session lifecycle
- submit invoices idempotently where possible
- poll and persist remote status
- distinguish local validation success from remote rejection or acceptance
- store the KSeF invoice number and UPO when available
- preserve request, response, and status history for debugging and audit

Acceptance:

- the system can distinguish locally valid, remotely rejected, and remotely
  accepted invoices
- accepted invoices retain their KSeF number and UPO
- retries do not silently create duplicate submissions

## 4. Real legacy invoices — parallel when data is available

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
