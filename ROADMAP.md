# ROADMAP

This file defines the durable product direction for AlfredoTheClerk. It is not a
current-task tracker.

- See `SPEC.md` for the current implementation sequence and acceptance criteria.
- See `AGENTS.md` for development and repository instructions.

## Product vision

AlfredoTheClerk turns invoice drafts and outputs from legacy systems into
reviewable, validated, KSeF-ready FA(3) invoices.

The product is not primarily a generic PDF converter and is not intended to
migrate arbitrary historical invoice archives. Its core value is diagnosing and
repairing incomplete, ambiguous, or invalid current invoice drafts while keeping
every change evidence-backed and deterministically verified.

## Product flow

`legacy-system invoice draft or output`

`-> deterministic parsing and extraction`

`-> canonical domestic VAT shell + evidence + diagnostics`

`-> deterministic validation and repair routing`

`-> evidence-constrained agentic repair when safe`

`-> human review when automation cannot resolve the case safely`

`-> one shared deterministic correctness pipeline`

`-> FA(3) XML`

`-> KSeF submission and status tracking`

## Durable product principles

### Canonical business truth

- The domestic VAT shell is the canonical business object.
- FA(3) XML is a downstream compliance artifact, not the source of truth.
- Source totals remain evidence and must be reconciled with totals computed from
  canonical line items.

### Bounded agentic repair

- The agent may diagnose failures and select evidence-backed candidates.
- The agent must not invent unsupported values, bypass the shell, or emit XML as
  its primary repair output.
- Agent and human repairs must pass the same deterministic correctness pipeline.

### Deterministic acceptance

An invoice is not ready merely because individual shell fields are structurally
valid. Acceptance requires the complete correctness path to succeed:

- full shell validation
- deterministic monetary summary computation
- reconciliation with extracted source totals
- FA(3) mapping
- XML serialization
- local XSD validation

Remote KSeF acceptance is tracked separately from local correctness.

### Reviewability and auditability

- Every automated or human correction must be attributable and reviewable.
- Evidence, candidates, validation failures, repair decisions, human changes,
  generated artifacts, and remote KSeF outcomes must remain traceable.
- Unsafe or unsupported cases must stop for review rather than silently degrade.

## Data strategy

Synthetic and real invoices have different roles and both remain part of the
product:

- Synthetic fixtures are the controlled regression laboratory. They isolate
  known failure modes, preserve deterministic expectations, and make repairs
  reproducible.
- Real legacy-system invoices are the external product-validation layer. They
  expose unknown layouts, source-specific behavior, and assumptions that the
  synthetic corpus cannot prove.

When a real failure is fixed, preserve the real regression case when legally and
operationally possible and add a minimal synthetic reproduction when useful.
Production-readiness claims require results from an untouched real-invoice
evaluation set.

## Product rollout

The product should mature in this order:

1. Complete the end-to-end correctness boundary around repaired invoices.
2. Add a human-review path that resumes through the same correctness boundary.
3. Integrate validated FA(3) invoices with KSeF submission, polling, and UPO
   storage.
4. Expand support source by source using real legacy-system output and measured
   failures.

This is strategic sequencing, not a task-status list. `SPEC.md` records which
step is active, completed, or blocked.

Real invoice collection and evaluation run in parallel whenever data becomes
available; they do not block development of the correctness, review, or KSeF
paths.

## Initial scope

The initial product scope remains:

- ordinary Polish domestic VAT invoices
- native, text-based PDF output from legacy or vertical software
- deterministic extraction with evidence and diagnostics
- evidence-constrained repair and manual escalation
- FA(3) generation and KSeF submission

## Out of scope for now

- scanned PDFs and OCR-first extraction
- photographs of invoices
- non-domestic invoices
- correction invoices
- advance invoices
- claims of arbitrary-PDF reliability without source-specific real evaluation

These boundaries may change only through an explicit product-direction update to
this file.

## Product success

The product succeeds when a supported legacy-system invoice can move from source
document to KSeF with:

- no unsupported invented values
- explicit evidence and diagnostics for uncertain fields
- a reviewable repair diff
- deterministic monetary and compliance validation
- a safe human-review fallback
- stored KSeF status, number, and UPO
- measured performance on named real source systems
