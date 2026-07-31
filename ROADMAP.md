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

## Core product flow

```text
legacy-system invoice draft or output
-> deterministic parsing and extraction
-> canonical domestic VAT shell + evidence + diagnostics
-> deterministic validation and repair routing
-> evidence-constrained agent repair when legal
-> human review for residual problems
-> one shared deterministic correctness pipeline
-> locally XSD-valid FA(3) XML
```

A validated `READY_FOR_KSEF` invoice is the minimal product completion boundary.
Remote KSeF submission is a separate downstream capability rather than a
prerequisite for the review product.

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
- If no usable evidence-backed candidate exists, the agent has no legal repair
  action and the field falls back to human review.
- Agent and human repairs must pass the same deterministic correctness pipeline.

### Deterministic acceptance

An invoice is not ready merely because individual shell fields are structurally
valid. `READY_FOR_KSEF` requires:

- full shell validation;
- deterministic monetary summary computation;
- reconciliation with extracted source totals;
- FA(3) mapping;
- XML serialization;
- local XSD validation.

Remote KSeF acceptance, rejection, and pending status remain separate from local
correctness.

### Reviewability and auditability

- Every automated or human correction must be attributable and reviewable.
- Evidence, candidates, validation failures, repair decisions, human changes,
  and generated artifacts must remain traceable within the workflow that owns
  them.
- Unsupported cases must stop for review rather than silently degrade.

The minimal local product does not require durable history storage; persistence
may be added later when multi-session or remote-submission workflows justify it.

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

1. Complete the shared deterministic correctness boundary.
2. Make agent-first repair and human fallback usable through a minimal local
   review interface.
3. Expand supported sources using real legacy-system invoices and measured
   failures.
4. Optionally productize the already-proven KSeF protocol boundary with durable
   submission identity, restart recovery, status history, KSeF number/UPO
   storage, and explicit DEMO/production rollout.

The repository already contains a TEST-only KSeF submission proof. That proof is
kept as a demonstrated downstream integration boundary, while durable remote
orchestration is intentionally not required by the minimal review product.

Real invoice collection and evaluation run in parallel whenever data becomes
available.

## Initial scope

The minimal product scope is:

- ordinary Polish domestic VAT invoices;
- native, text-based PDF output from supported legacy or vertical software;
- deterministic extraction with evidence and diagnostics;
- evidence-constrained agent repair;
- safe human-review fallback;
- deterministic FA(3) generation and local XSD validation;
- explicit FA(3) XML output for downstream use.

KSeF TEST submission exists separately and may be invoked explicitly outside the
local review UI.

## Out of scope for now

- scanned PDFs and OCR-first extraction;
- photographs of invoices;
- multi-page invoice extraction in the local review slice;
- non-domestic invoices;
- correction invoices;
- advance invoices;
- claims of arbitrary-PDF reliability without source-specific real evaluation;
- persistent multi-user review infrastructure;
- durable KSeF recovery/UPO tracking unless explicitly promoted into a later
  product slice.

These boundaries may change only through an explicit product-direction update to
this file.

## Product success

The minimal product succeeds when a supported legacy-system invoice can move
from source document to locally validated FA(3) with:

- no unsupported invented values;
- explicit evidence and diagnostics for uncertain fields;
- agent repair before human fallback wherever usable candidates exist;
- a reviewable automated-repair diff;
- deterministic monetary and compliance validation;
- a usable human-review path for residual problems;
- downloadable `READY_FOR_KSEF` FA(3) XML;
- measured performance on named real source systems as those evaluation sets
  become available.

Durable KSeF status, KSeF-number, and UPO persistence are optional later
productization goals, not minimal-product success criteria.
