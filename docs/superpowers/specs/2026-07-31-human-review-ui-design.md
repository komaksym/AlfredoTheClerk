# Human-review UI design

## Goal

Turn the existing extraction → agent repair → correctness pipeline into a minimal local application that a human can use when automation cannot finish an invoice safely.

The slice ends at a locally validated `READY_FOR_KSEF` invoice and generated FA(3) XML. Durable KSeF orchestration, persistence, UPO handling, and production rollout remain outside this slice.

```text
single-page PDF
→ deterministic extraction
→ deterministic repair routing
→ evidence-constrained agent repair
→ shared correctness pipeline
        │
        ├─ READY_FOR_KSEF
        │      → success screen + XML
        │
        └─ unresolved
               → human-review UI
               → corrections
               → shared correctness pipeline
               → READY_FOR_KSEF
```

The canonical shell remains the business truth. Agent and human changes must pass through the existing deterministic correctness boundary.

## Application boundary

Build a single-user local web application using:

- FastAPI
- Jinja templates
- small vanilla JavaScript
- the existing Python extraction, repair, correctness, and FA(3) modules

The app binds to `127.0.0.1` only. There is one active invoice at a time.

Do not add React, Node, a SPA architecture, a separate frontend service, or a frontend build pipeline.

## Supported input

The UI accepts one ordinary Polish domestic VAT invoice as a native/text-based, single-page PDF.

The existing parser already assumes exactly one page, so multi-page parsing remains out of scope. Scanned PDFs, OCR, photos, correction invoices, advance invoices, non-domestic invoices, and generic arbitrary-PDF support are also out of scope.

Unsupported input must produce a clear UI error instead of a raw traceback.

## Agent-first repair rule

Human review is a fallback after all legal agent repair opportunities have been exhausted.

For each problematic field:

```text
usable evidence-backed candidate exists
→ agent may repair

no usable candidate exists
→ agent has no legal action
→ human fallback
```

The agent:

- receives only repairable fields;
- may choose only existing evidence-backed candidates;
- may not invent values;
- may not modify immutable extracted summary evidence;
- may not bypass the canonical shell or deterministic correctness pipeline.

### Mixed invoices

When an invoice contains both repairable and blocking fields, the agent handles every evidence-backed field first. Only residual unresolved problems go to the human.

Example:

```text
seller.nip        → candidate exists
buyer.address     → candidate exists
payment.iban      → no candidate

agent repairs seller.nip + buyer.address
→ correctness
→ payment.iban remains unresolved
→ human review
```

The human is not asked to redo successful agent repairs.

### Purely blocking invoices

Do not invoke the agent when every unresolved field has no permissible action, such as:

- missing evidence;
- zero candidates;
- candidates exist but every value is `None`;
- immutable `summary.*` evidence.

These cases go directly to human review because the model has nothing legal to choose.

### Agent technical failure

If the agent times out, errors, returns malformed output, or otherwise produces no usable repair, preserve the current invoice state and open human review. Show a small notice that automated repair failed.

A broken model must not make the invoice unusable.

## Human-review layout

Use a side-by-side interface:

```text
┌──────────────────────────┬───────────────────────────┐
│                          │ Agent changes             │
│                          ├───────────────────────────┤
│                          │                           │
│       Original PDF       │ Unresolved fields         │
│                          │                           │
│       + evidence         │ [field card]              │
│         highlights       │ [field card]              │
│                          │ [field card]              │
│                          │                           │
│                          │ Review & Validate         │
└──────────────────────────┴───────────────────────────┘
```

Do not add a dashboard, invoice queue, history page, settings area, or multi-invoice navigation.

## PDF evidence interaction

The left pane shows the original PDF.

Selecting or focusing an unresolved field should:

- bring its evidence region into view when possible;
- highlight the evidence bounding box;
- visually associate the highlight with the selected field card.

Use the existing extraction geometry. Do not invent a second evidence-coordinate representation.

When no geometry exists, show `No source evidence found` and do not display a fake highlight.

## Agent changes

Show successful automated repairs in a read-only `Agent changes` section above unresolved fields.

For each change, show:

- field label and canonical path;
- original value;
- repaired value;
- selected candidate index when available;
- confidence when available.

Example:

```text
Agent changes — 2

Seller NIP
1234567890 → 9876543210
Candidate #1 · confidence 0.94

Sale date
2026-07-03 → 2026-07-08
Candidate #0 · confidence 0.89
```

The section may collapse when long. It is an audit view, not a second approval gate.

If an agent-repaired field later becomes unresolved after correctness validation, it returns to the unresolved field list.

## Unresolved field cards

Show all remaining unresolved fields in one scrollable list.

Each card should display, where available:

- human-readable label;
- canonical shell path;
- current value;
- reason the field remains unresolved;
- validation errors;
- blocking reason;
- extracted/raw text;
- evidence candidates;
- candidate confidence;
- manual correction input.

## Human repair permissions

The human may either:

1. select an extracted candidate; or
2. enter an explicit manual canonical value.

This boundary is intentional:

```text
agent → candidate-only
human → candidate OR manual correction
```

Fields with no candidates remain editable through manual correction.

## Derived totals and `summary.*`

Extracted summary values are immutable evidence and are never directly editable.

A mismatch appears as an explanatory issue, for example:

```text
Gross total mismatch

PDF evidence:         2,460.00 PLN
Calculated invoice:  2,430.00 PLN

The extracted source total is evidence and cannot be edited.
Correct the invoice data responsible for this difference.
```

Where the mismatch can be tied to editable canonical line-item fields, surface those fields for correction. Do not add an `edit total` control.

## Submission semantics

The browser accumulates proposed human changes without mutating the canonical invoice on each event.

One primary action, `Review & Validate`, submits the full review batch:

```text
form values
→ build review commands
→ validate the whole batch
→ apply atomically
→ rerun shared correctness pipeline
```

This preserves the existing backend's atomic human-review semantics.

## Failed human review

When corrections are still invalid:

- remain on the same review page;
- preserve attempted values;
- show updated validation errors;
- refresh the unresolved field state;
- preserve audit information for the attempt;
- allow another correction attempt.

Do not require re-uploading or re-running extraction.

## Reviewer attribution

Keep reviewer attribution but make it minimal for a local single-user app.

Prompt for one reviewer name or identifier when human review is first needed and retain it for the active process/session.

Do not add user accounts, authentication, roles, or authorization.

## Reasons and audit data

Generate default reasons automatically:

```text
candidate selection → "selected evidence candidate"
manual correction   → "manual correction"
```

An optional reviewer note may be supported, but typing a reason for every field is not required.

Every human decision still records reviewer attribution and the resulting change.

## Successful outcomes

### Already valid

```text
✓ Invoice valid
No repairs required
READY_FOR_KSEF
```

### Agent repaired everything

```text
✓ Agent repair successful
2 fields corrected
READY_FOR_KSEF

Agent changes
...
```

No human form is shown.

### Human review succeeded

```text
✓ Review complete
✓ Shell valid
✓ Totals reconciled
✓ FA(3) generated
✓ XSD valid

READY_FOR_KSEF
```

All successful paths use the same deterministic correctness result.

## Output

On success, expose the generated FA(3) XML for download.

Do not submit to KSeF from this UI slice.

```text
READY_FOR_KSEF
→ Download FA(3) XML
```

The existing TEST submission implementation remains intact and separate.

## State and persistence

State is intentionally in memory only:

```text
process starts
→ user uploads invoice
→ active workflow/review case lives in memory
→ new upload replaces it
→ process restart loses it
```

Do not add:

- a database;
- durable queues;
- review history storage;
- restart recovery;
- background workers.

These are later productization concerns.

## Error handling

The UI must convert expected workflow failures into understandable states rather than tracebacks.

At minimum:

- unsupported or multi-page PDF → upload error;
- extraction failure → processing error with no partial canonical mutation;
- agent technical failure → human-review fallback with warning;
- invalid human command batch → keep form state and show field errors;
- correctness failure after review → remain in review with updated blockers;
- XML/XSD failure → show the deterministic correctness status rather than claiming readiness.

Unexpected server errors may still be logged, but browser-visible error messages must not expose secrets.

## Out of scope

Explicitly exclude:

- durable KSeF integration;
- automatic KSeF submission from the UI;
- UPO retrieval or storage;
- DEMO/production environment rollout;
- persistent review cases;
- restart recovery;
- multi-user support;
- authentication;
- roles/permissions;
- dashboards;
- invoice queues;
- multi-page PDFs;
- scanned PDFs;
- OCR;
- photos;
- correction invoices;
- advance invoices;
- non-domestic invoices;
- generic arbitrary-PDF support;
- React or another frontend framework;
- deployment infrastructure.

## Acceptance criteria

The slice is complete when:

1. A user can launch the application locally and upload a supported PDF.
2. The existing extraction pipeline processes the PDF.
3. Every evidence-backed agent repair opportunity is attempted before human review.
4. The agent cannot introduce values outside available candidates.
5. Successful agent changes appear as a read-only diff.
6. Remaining unresolved fields appear in the side-by-side review interface.
7. Selecting a field highlights its PDF evidence when geometry exists.
8. The reviewer can select a candidate or enter a manual correction.
9. Human changes are applied atomically.
10. Human repair reruns the existing correctness pipeline.
11. Failed corrections stay editable without re-uploading the PDF.
12. Successful completion reaches `READY_FOR_KSEF`.
13. Generated FA(3) XML is available to the user.
14. No KSeF submission occurs as a side effect of using the UI.
15. Existing extraction, repair, correctness, human-review, and KSeF tests remain green.
16. Regression coverage includes:
   - no repair needed;
   - fully agent-repaired;
   - mixed agent + human repair;
   - blocking-only human review;
   - agent technical failure → human fallback;
   - invalid human correction;
   - successful human correction;
   - missing PDF evidence;
   - unsupported multi-page upload.

## Validation

Run the repository's normal checks before handoff:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
```

Also perform a manual browser smoke test of:

```text
PDF
→ agent
→ human fallback
→ READY_FOR_KSEF
```

## Scope boundary

This slice makes the existing repair backend usable as a minimal local product without expanding into persistence or durable KSeF orchestration.

Durable KSeF integration remains a later optional extension rather than a prerequisite for the human-review UI.
