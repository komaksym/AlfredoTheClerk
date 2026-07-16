# Post-Repair Correctness Pipeline Design

## Purpose

A repaired shell is not safe merely because its individual fields validate.
The system needs one deterministic boundary that proves the shell's monetary
meaning and FA(3) output before any agent or human repair can be treated as
KSeF-ready.

This design implements the first active item in `SPEC.md`. It does not add the
human-review interface or remote KSeF integration.

## Architecture

Add a shared correctness service in the invoice domain rather than embedding
the checks in agent orchestration. Agent repair calls the service now; the later
human-review workflow will call the same service without depending on agent
code.

The service runs these stages in order and stops at the first failure:

1. Fully validate the repaired domestic VAT shell.
2. Recompute line, VAT-bucket, and invoice totals from canonical line items.
3. Reconcile computed VAT-bucket and invoice totals with extracted PDF totals.
4. Map the shell and computed summary to `Faktura`.
5. Serialize `Faktura` to FA(3) XML.
6. Validate the XML against the checked-in local FA(3) XSD bundle.

No stage mutates the shell, extracted summary, or evidence.

## Components

### Invoice correctness service

Create `src/invoice_gen/invoice_correctness.py` with:

- `CorrectnessStatus`, containing exactly:
  - `READY_FOR_KSEF`
  - `INVALID_SHELL`
  - `TOTALS_MISMATCH`
  - `FA3_MAPPING_FAILED`
  - `XML_SERIALIZATION_FAILED`
  - `XSD_VALIDATION_FAILED`
- `TotalsMismatch`, a structured record containing the summary path, computed
  value, extracted value, and reason.
- `CorrectnessResult`, the immutable stage result. It retains the status,
  shell validation, computed summary when available, reconciliation mismatches,
  mapped `Faktura` when available, XML when available, XSD result when
  available, and a stable error description for exceptional failures.
- `check_invoice_correctness(shell, extracted_summary, generated_at=None)`, the
  reusable entry point.

Expected business failures are returned, not raised. Programmer errors outside
the known validation, summary, mapping, serialization, and XSD boundaries are
not silently converted into business outcomes.

### Totals reconciliation

Reconciliation compares:

- `summary.invoice_net_total`
- `summary.invoice_vat_total`
- `summary.invoice_gross_total`
- each extracted VAT bucket's `net_total`, `vat_total`, and `gross_total`

The computed summary is authoritative because it is derived from canonical
line items using repository rounding rules. Extracted totals remain immutable
source evidence.

Every extracted total required by the current extraction contract must exist
and equal its computed counterpart. A missing extracted value, missing or extra
VAT bucket, or unequal value produces `TOTALS_MISMATCH`. Missing totals never
fall back to computed values and never produce `READY_FOR_KSEF`.

Line computations are recomputed but not compared to extracted line-total
columns because the current PDF extraction contract does not expose those
columns. Their effect is still checked through VAT-bucket and invoice totals.

### Reusable local XSD validation

Create `src/invoice_gen/fa3_xsd_validation.py` and move the local schema-bundle
validation behavior out of the hard-case corpus. It exposes
`validate_xml_against_local_schema_bundle(xml)` and the immutable
`XsdValidationResult`.

Existing benchmark and hard-case imports remain compatible by importing and
re-exporting the shared result and validator where necessary. The validator
continues to use the checked-in schema files and local `xmllint`; it performs no
network access.

## Result flow

The failure precedence is deterministic:

```text
invalid shell
  -> INVALID_SHELL
valid shell + unreconciled totals
  -> TOTALS_MISMATCH
reconciled totals + mapping exception
  -> FA3_MAPPING_FAILED
mapped Faktura + serialization exception
  -> XML_SERIALIZATION_FAILED
serialized XML + failed XSD result
  -> XSD_VALIDATION_FAILED
all stages succeed
  -> READY_FOR_KSEF
```

A ready result contains the validated shell, computed summary, mapped
`Faktura`, serialized XML, and successful XSD result so later KSeF integration
does not need to reconstruct or bypass the correctness boundary.

## Repair orchestration integration

`RepairWorkflowResult` gains an optional correctness result. After a successful
candidate repair, orchestration calls `check_invoice_correctness` with the
repaired shell and the original extraction context's extracted summary.

- `READY_FOR_KSEF` preserves the existing `REPAIRED` workflow status and
  returns the repaired shell plus its correctness artifact.
- Any correctness failure returns `MANUAL_REVIEW_REQUIRED`, preserves the
  original shell as the workflow's safe fallback, retains the attempted repair
  and correctness details, and uses the correctness status value as the stable
  reason.
- Agent failures before a repair result keep their existing behavior and have
  no correctness result.

This preserves the existing workflow API while changing the meaning of
`REPAIRED` from "field validation passed" to "the complete local correctness
boundary passed."

## Testing

Tests are written before production changes and cover:

- the complete ready path with real validation, summary, mapping, XML, and
  local XSD validation
- invalid shell
- missing extracted invoice total
- unequal extracted invoice total
- missing, extra, and unequal VAT buckets
- FA(3) mapping failure
- XML serialization failure
- XSD validation failure with retained validator detail
- orchestration returning `REPAIRED` only for `READY_FOR_KSEF`
- orchestration routing every correctness failure to manual review while
  retaining the attempted repair details
- existing hard-case and benchmark XSD behavior after validator extraction

The repository's Ruff, full pytest, and compileall gates must pass.

## Scope boundaries

- No model-editable summary or total fields.
- No human-review interface.
- No KSeF client or remote validation.
- No scanned-document or OCR support.
- No generic pipeline framework; the shared function is the abstraction needed
  by the two known callers: agent repair now and human repair later.
