# Human-Review Workflow Design

## Purpose

The extraction and agent-repair workflow can identify invoices that require
manual review, but it cannot yet present a complete review case, accept a human
correction, preserve an audit trail, or resume correctness validation.

This slice adds that backend domain workflow. A reviewer can inspect the
current canonical value and its extraction evidence, select an existing
candidate or provide a typed correction, and submit the resulting candidate
shell through the same deterministic correctness boundary used after agent
repair.

The workflow does not make a human correction valid by itself. A corrected
shell becomes locally ready for KSeF only after full shell validation, monetary
reconciliation, FA(3) mapping, XML serialization, and local XSD validation all
succeed.

## Branch and dependency

Implement this slice on `codex/human-review-workflow`, created from
`codex/post-repair-correctness`.

The human-review workflow depends on the correctness service and the extraction
context preservation introduced by `codex/post-repair-correctness`. It must not
be based directly on `main` until that branch has been merged.

## Product invariants

- The domestic VAT shell remains the canonical business object.
- Extracted summary totals remain immutable evidence. Humans correct canonical
  shell fields; they do not overwrite `summary.*` evidence.
- Human corrections and agent repairs pass through the same
  `check_invoice_correctness()` function.
- A human may provide a correction not present in extraction candidates, but
  every accepted change must be attributable and auditable.
- Agent repair remains evidence-constrained. Adding the human path must not
  allow an agent command to inject an arbitrary value.
- The input workflow result and extraction context remain immutable.
- Unsupported or invalid review commands fail closed with structured issues.

## Architecture

Add a focused human-review domain service beside agentic repair. It consumes a
`RepairWorkflowResult` whose status is `MANUAL_REVIEW_REQUIRED`, builds a
reviewable case, applies a validated batch of human commands to a copied shell,
records the accepted changes, and calls the existing invoice correctness
service.

Human review and agent repair share only field-path access primitives and the
correctness boundary. They keep separate command models because their authority
differs:

- an agent may only promote an existing evidence candidate;
- a human may select a candidate or enter a typed canonical value.

Do not represent a human-entered value as a synthetic extraction candidate.
That would falsely claim the value came from source evidence.

## Components

### Shared shell-field access

Extract the pure path-support, read, and write behavior currently embedded in
`RepairSession` into a small internal module under `src/agentic_repair`.

The shared functions:

- determine whether a path names a supported mutable shell field;
- read the current value at a supported path;
- write a value at a supported path on a caller-owned shell copy;
- enforce line-item index bounds;
- reject every `summary.*` path.

`RepairSession` delegates to these functions without changing the existing
agent command contract or evidence-candidate checks.

The path helpers do not validate business values. Business validation remains
inside the existing shell and correctness validators.

### Review case

Create a human-review module with an immutable `HumanReviewCase`. It retains:

- the original `RepairContext`;
- the current candidate shell;
- the original repair route and reason;
- the latest correctness result, when one exists;
- reviewable field descriptions;
- prior human-review attempts.

A reviewable field exposes:

- field path;
- current canonical value;
- extraction diagnostic status;
- shell validation errors for that path;
- blocking reason, when routing marked the field as blocking;
- raw extracted text;
- evidence bounding box;
- available evidence candidates with stable indices, values, confidence,
  source metadata, and rejection information.

Review fields are built from the union of route problem paths and field-level
errors from the latest correctness result. Correctness failures that are not
editable shell fields, such as totals mismatches or XSD errors, remain visible
as case-level diagnostics.

For a correctness failure after agent repair, the current review shell must be
the shell stored in `CorrectnessResult.shell`, not the original extracted
shell. The original extraction context remains available separately.

### Human commands

Support two explicit immutable command types:

1. Candidate selection: path, candidate index, and reason.
2. Manual correction: path, typed canonical value, and reason.

The submission also requires a non-empty `reviewer_id`. Transport-layer string
parsing, form validation, authentication, and identity lookup are outside this
slice; the caller supplies canonical Python values and the reviewer identifier.

Candidate selection requires existing evidence, a valid candidate index, and a
candidate with a non-`None` value. Manual correction does not add or mutate
extraction evidence.

Both command types require a supported shell path and a non-empty reason.
Duplicate paths inside one batch are rejected.

### Atomic command application

Validate the complete command batch before changing any shell copy. If any
command is malformed, unsupported, duplicated, or references an invalid
candidate, reject the entire batch and apply none of its changes.

For example, a valid `invoice_number` correction submitted with a forbidden
`summary.invoice_gross_total` edit must not partially change the invoice
number.

After batch validation succeeds, deep-copy the current review shell and apply
every command to that copy. The original workflow result, extraction context,
and previous review shell remain unchanged.

Atomicity covers command application. It does not erase a fully applied review
attempt whose candidate shell later fails correctness. That failed candidate
shell is retained as reviewable history but is never accepted as locally ready.

### Audit records

Each successfully applied command produces an immutable decision containing:

- reviewer identifier;
- field path;
- old value;
- new value;
- input kind (`candidate_selection` or `manual_correction`);
- candidate index for candidate selections;
- reviewer reason.

Each submission produces an attempt record containing the submitted commands,
accepted decisions, structured command issues, and resulting correctness
status when correctness ran.

A rejected command batch records its issues and no accepted decisions. A valid
batch records every decision even when the resulting shell fails correctness.

### Review outcome and retries

The service returns a structured outcome with one of two states:

- `READY_FOR_KSEF`: the corrected candidate passed the complete local
  correctness boundary;
- `MANUAL_REVIEW_REQUIRED`: command validation or local correctness failed and
  another human attempt is required.

A ready outcome exposes the unchanged `CorrectnessResult`, including its
computed summary, mapped `Faktura`, XML, and successful XSD result.

A failed outcome exposes an updated `HumanReviewCase`. If commands were
rejected, its current shell is unchanged. If a valid batch failed correctness,
its current shell is the fully applied candidate shell. In both cases, the
attempt and diagnostics remain available for the next review submission.

`READY_FOR_KSEF` means locally validated and ready to submit. It does not mean
that KSeF remotely accepted the invoice.

## Data flow

```text
RepairWorkflowResult(MANUAL_REVIEW_REQUIRED)
  -> build HumanReviewCase
  -> reviewer submits reviewer_id + command batch
  -> validate every command
      -> any command issue: retain shell, record rejected attempt, require review
  -> deep-copy current shell
  -> apply every command and record decisions
  -> check_invoice_correctness(candidate, original extracted summary)
      -> failure: retain attempted shell and audit, require review
      -> READY_FOR_KSEF: return correctness artifacts
```

The correctness sequence after a valid human correction remains:

```text
full shell validation
  -> deterministic summary computation
  -> extracted-total reconciliation
  -> FA(3) mapping
  -> XML serialization
  -> local XSD validation
  -> READY_FOR_KSEF
```

## Error handling

Expected review failures return structured issues rather than generic
exceptions. Stable issue reasons cover at least:

- result is not eligible for manual review;
- empty reviewer identifier;
- empty command batch;
- empty reason;
- duplicate path;
- unsupported or immutable path;
- missing evidence;
- missing candidates;
- candidate index out of range;
- candidate value missing.

Known correctness failures keep their existing `CorrectnessStatus` and details.
Unexpected programmer errors are not silently converted into business
outcomes.

## Testing

### Focused unit tests

Unit tests use small constructed contexts and controlled correctness results to
cover:

- review-case field completeness;
- route and correctness-error path union;
- evidence bounding boxes and candidate metadata;
- candidate selection;
- typed manual correction;
- reviewer attribution and reasons;
- duplicate, unsupported, immutable, and invalid-candidate rejection;
- all-or-nothing command application;
- input-shell and extraction-context immutability;
- failed-attempt audit preservation and retry behavior;
- unchanged agent evidence constraints after shared path-helper extraction.

### Human-review-to-correctness integration tests

Integration tests construct a real domestic VAT shell, extracted summary, and
manual-review context, then call the real human-review service and real
`check_invoice_correctness()` implementation.

They do not mock FA(3) mapping, XML serialization, or local XSD validation. A
successful correction must produce a `READY_FOR_KSEF` result containing XML and
a successful XSD result. A totals mismatch must remain
`MANUAL_REVIEW_REQUIRED` with the mismatch details and attempted audit record.

These tests intentionally skip PDF parsing so they isolate the integration
between the human-review service and the complete local correctness boundary.

### PDF workflow integration test

Add an end-to-end test using the persisted
`long_parties_v1/seller_buyer_block_v1.pdf` hard-case PDF and its reviewed
truth:

1. Parse the real PDF with `pdfplumber` and `parse_data()`.
2. Run the real extraction and deterministic repair routing.
3. Copy the registered template anchors and set only the copied
   `invoice_number` anchor list to empty. Real extraction then produces missing
   invoice-number evidence and the real router returns manual review for that
   blocking field.
4. Build the review case from the real workflow result.
5. Submit the truth-backed human correction.
6. Run the real correctness pipeline.
7. Assert `READY_FOR_KSEF`, non-empty XML, and successful local XSD validation.

The test must not monkeypatch `run_full_extraction()`,
`check_invoice_correctness()`, FA(3) mapping, XML serialization, or the XSD
validator. No language model or remote KSeF request is involved because the
controlled unresolved field takes the deterministic manual-review route.

The production template registry is not mutated. The controlled anchor copy is
only the test input that exercises the same missing-evidence path produced by a
source whose invoice-number label is unsupported. The persisted PDF and truth
remain reviewable on disk, and no PDF is generated during the test.

## Documentation and completion

When the slice is complete:

- mark the human-review workflow complete in `SPEC.md` only if every acceptance
  criterion for this slice is satisfied;
- update `PLANS.md` with the active branch, milestones, and final status;
- preserve `ROADMAP.md` because product direction is unchanged;
- run the narrowest tests first, then Ruff, the full test suite, compileall, and
  the repository build/package check relevant to packaged XSD resources.

## Scope boundaries

- No user interface or HTTP/API transport.
- No persistence layer or schema migration.
- No authentication or authorization implementation.
- No parsing of free-form UI strings into domain values.
- No remote KSeF authentication, submission, polling, or UPO storage.
- No changes to agent authority or evidence constraints.
- No editing of extracted `summary.*` totals.
- No scanned-PDF or OCR support.

## Acceptance criteria

- Every manual-review outcome can be represented as a complete review case.
- A reviewer can select an evidence candidate or provide a typed correction.
- Invalid batches never partially mutate a shell.
- Every applied human change is attributable and retained across failed
  attempts.
- Failed attempts remain reviewable and can be retried without re-extracting
  the source PDF.
- Successful human corrections return the same correctness artifact shape as
  successful agent repairs.
- `READY_FOR_KSEF` is impossible until the corrected shell passes every local
  correctness stage.
- Unit, human-review-to-correctness integration, and PDF workflow integration
  tests pass.
- Agent repair remains limited to existing non-`None` evidence candidates.
