# Agent Safe-Abstention Design

## Goal

Allow the invoice-repair agent to make a safe, explicit decision for every
field in its payload:

- repair a field when exactly one candidate is semantically supported; or
- leave that field for human review when the evidence remains ambiguous.

One agent execution may therefore repair clear fields and escalate dangerous
fields from the same document. The implementation must preserve the current
single-model-call and single-tool-call budgets, existing deterministic fast
paths, and the existing human-review workflow.

## Problem

The current agent has only one model-facing action: `apply_repair_plan`.
The prompt tells the model not to call the tool when evidence is ambiguous, but
production interprets a no-tool response as:

```text
AGENT_FAILED
reason = "agent_no_tool_call"
```

The benchmark previously treated the absence of a selected candidate on an
ambiguous case as a safe escalation. Production and evaluation therefore do
not share the same abstention contract.

The first three-repeat live benchmark also showed that the model selected a
candidate in all nine ambiguous opportunities, producing a 0% safe-escalation
rate.

A whole-payload abstention tool would fix the explicitness problem but would
waste valid repairs whenever one field is clear and another field is
ambiguous. This design instead uses one combined per-field decision tool.

## Terminology

### Candidate exists

A candidate exists when extraction produced a possible value for a field.
Candidate count alone does not establish correctness.

A single candidate can still be unsafe. For example, the only extracted bank
account may be explicitly described as a customer refund account rather than
the seller's payment account.

### Uniquely supported candidate

A candidate is uniquely supported when its evidence establishes that it belongs
to the requested field and no competing candidate has equally plausible
evidence for that role or meaning.

`Uniquely supported` does not mean `only one candidate exists`.

Examples:

- two NIP candidates exist, but only one line identifies the invoice issuer;
- three dates exist, but only one line identifies the document issue date;
- two IBANs exist, but only one is identified as the account for invoice
  payment.

### Ambiguous field

A field is ambiguous when the available evidence does not uniquely support one
candidate for the requested field.

Examples include:

- two candidates that are equally plausible for the same role;
- invoice-number-like values without evidence identifying the final invoice
  number;
- valid bank accounts without evidence identifying the seller's payment
  account;
- dates whose evidence does not distinguish issue date, sale date, or payment
  deadline.

A field is not ambiguous merely because multiple candidates exist or because
the semantically supported candidate has lower extraction confidence.

### Partial repair

This design supports document-level and agent-payload-level partial repair.

For example, a document may contain:

- a clear `seller.nip` candidate;
- an ambiguous `invoice_number` candidate set; and
- a blocking summary field that was never agent-repairable.

The agent may repair `seller.nip`, escalate `invoice_number`, and leave the
blocking summary field to the existing human-review workflow. The document
remains in manual review, but the accepted seller-NIP repair is preserved.

## Existing deterministic boundary

The change does not duplicate or replace deterministic extraction.

Existing logic continues to own:

- seller and buyer sub-block detection;
- field-label anchors;
- NIP and IBAN structural/checksum validation;
- deterministic unique winners;
- the exact-labelled NIP fallback;
- no-repair and blocking-field routing.

The agent only receives fields that survive extraction, validation, routing,
and deterministic fallback.

No new seller, buyer, date, payment-account, or refund-account keyword registry
is added to agent orchestration. If future end-to-end fixtures show that useful
structured extraction provenance is lost before the agent boundary, candidate
role metadata may be designed separately.

## Chosen architecture

Replace the model-facing repair-only tool with one combined decision tool:

```text
submit_repair_decisions
```

The tool accepts exactly one decision for every field in the agent payload.
Each decision is either:

- `repair`; or
- `human_review`.

The model still makes one LLM call and at most one tool call.

```text
MAX_LLM_CALLS = 1
MAX_TOOL_CALLS = 1
```

The deterministic repair kernel remains unchanged. The combined tool validates
and partitions model decisions, then passes only the repair subset to the
existing `RepairSession.apply_repair_plan` method.

## Model-facing schema

```python
class AgentFieldDecisionInput(BaseModel):
    path: str
    action: Literal["repair", "human_review"]
    candidate_index: int | None
    reason: str


def submit_repair_decisions(
    decisions: list[AgentFieldDecisionInput],
) -> AgentDecisionResult:
    ...
```

Example mixed decision:

```json
{
  "decisions": [
    {
      "path": "seller.nip",
      "action": "repair",
      "candidate_index": 1,
      "reason": "The evidence identifies this party as the invoice issuer."
    },
    {
      "path": "invoice_number",
      "action": "human_review",
      "candidate_index": null,
      "reason": "Neither candidate is uniquely identified as the invoice number."
    }
  ]
}
```

## Tool validation contract

The combined tool validates the complete decision batch before applying any
repair.

The batch must satisfy all of the following:

1. It contains exactly one decision for every field in the agent payload.
2. It contains no unknown path.
3. It contains no duplicate path.
4. Every reason is non-empty.
5. A `repair` decision has a non-null candidate index within that field's
   candidate list.
6. A `human_review` decision has `candidate_index = null`.
7. A selected repair candidate has a non-null value.

Missing, duplicate, unknown, or malformed decisions cause the tool execution to
fail. No repair is applied from an invalid batch.

This complete-coverage contract prevents silent omission from being interpreted
as abstention.

## Deterministic execution

After validation, the tool partitions decisions into:

```text
repair decisions
human-review decisions
```

If at least one repair decision exists, the tool constructs one
`RepairPlanCommand` containing only those repairs and calls the existing
`RepairSession.apply_repair_plan` method once.

If every field is escalated, the tool does not call the repair session.

The repair subset remains atomic under the existing kernel contract. If kernel
validation fails, the complete agent execution fails and no model decision is
accepted.

## Result types

Add an immutable field-level escalation record:

```python
@dataclass(frozen=True, kw_only=True)
class AgentHumanReviewDecision:
    path: str
    reason: str
```

Add an immutable combined tool result:

```python
@dataclass(frozen=True, kw_only=True)
class AgentDecisionResult:
    repair_result: RepairResult | None
    human_review_decisions: tuple[AgentHumanReviewDecision, ...]
```

Extend the graph result:

```python
@dataclass(frozen=True, kw_only=True)
class AgentRepairResult:
    repair_result: RepairResult | None
    human_review_decisions: tuple[AgentHumanReviewDecision, ...]
    tool_called: bool
    final_messages: tuple[AnyMessage, ...]
```

Valid outcomes are:

| Repair result | Human-review decisions | Meaning |
| --- | --- | --- |
| Present | Empty | Every payload field was repaired |
| Present | Present | Some fields were repaired and some escalated |
| Absent | Present | Every payload field was escalated |
| Absent | Empty | Invalid/incomplete agent execution |

The model cannot submit two separate tools in one execution.

## System prompt

Replace the current implication that every payload field is already safely
repairable.

The prompt must say:

> The payload contains fields for which deterministic extraction and routing
> could not establish a safe final value. For each field, determine whether
> exactly one candidate is uniquely supported by evidence for the requested
> field. Repair that field when one candidate is uniquely supported; otherwise
> leave that field for human review.

The prompt must require this process:

1. Inspect every field independently.
2. Compare all candidates using `raw_text`, `same_line_text`, the requested
   field path, and labels or role language in the evidence.
3. Emit exactly one decision for every payload field.
4. Use `repair` only when exactly one candidate is uniquely supported.
5. Use `human_review` when evidence remains ambiguous or contradicts the
   requested field.
6. Never omit a field.
7. Never resolve semantic ambiguity by selecting the highest-confidence
   candidate.

Add explicit confidence guidance:

> Candidate confidence describes extraction reliability. It does not establish
> field ownership, party role, date meaning, account purpose, or overall
> semantic correctness. Confidence cannot break a semantic tie.

Candidate confidence remains in the payload for this MVP. Removing or renaming
it is a later ablation, not part of this implementation.

## Production orchestration

### All fields repaired

When the result contains repairs and no human-review decisions, preserve the
existing flow:

1. accept the agent repair provenance;
2. run the shared correctness gate on the repaired shell;
3. return `REPAIRED` only when correctness is ready for KSeF;
4. otherwise return `MANUAL_REVIEW_REQUIRED` through the existing correctness
   path.

### Mixed repair and escalation

When the result contains both repairs and human-review decisions:

1. preserve the accepted repair result with `AutomatedRepairOrigin.AGENT`;
2. run the shared correctness gate on the partially repaired shell;
3. return `MANUAL_REVIEW_REQUIRED` regardless of whether the remaining shell
   would otherwise pass validation;
4. use stable reason code `agent_partial_abstention`;
5. retain the field-level escalation reasons on `agent_result`.

The existing human-review builder already starts from `correctness.shell` when
correctness exists. The partially repaired candidate shell therefore remains
the review starting point. Existing presentation logic continues to show
accepted automated changes and hides automatically resolved fields from the
human-editable list.

### Every field escalated

When there is no repair result and at least one human-review decision:

```text
status = MANUAL_REVIEW_REQUIRED
reason = "agent_abstained"
automated_repair = None
```

The original extracted shell becomes the review starting point.

### Existing blocking fields

Blocking fields that were never agent-repairable remain in the route and remain
visible to human review. They do not prevent the agent from repairing clear
fields in its own payload.

### No tool call

When the agent returns without calling the combined tool:

```text
status = AGENT_FAILED
reason = "agent_no_tool_call"
```

No-tool behavior is never considered a successful abstention.

### Tool or graph exception

Existing exception handling remains:

```text
status = AGENT_FAILED
reason = "agent_exception"
```

## Human-review projection

The existing review route remains the source of reviewable fields.

- repaired fields remain recorded in `automated_repair`;
- escalated agent fields remain unresolved route fields and therefore remain
  available for human review;
- existing blocking fields remain available for human review;
- presentation logic may hide repaired paths when correctness proves they are
  resolved.

Displaying the agent's escalation reason directly in the UI is not required for
this MVP. The reason must remain available in `workflow.agent_result` for audit
and future presentation work.

## Benchmark representation

Replace attempt-level implicit abstention with explicit per-field escalation.

Extend `BenchmarkAttempt` with:

```python
human_review_paths: tuple[str, ...]
```

The benchmark runner records:

- candidate selections from the repair subset;
- human-review paths from the escalation subset;
- whether the combined tool was called;
- latency and errors as before.

Attempt invariants:

1. selection paths are unique;
2. human-review paths are unique;
3. the two path sets are disjoint;
4. every recorded path belongs to the benchmark case;
5. for a successful model-evaluated attempt, the union of selected and
   human-review paths covers every field in the case;
6. human-only cases continue to bypass the model and have both sets empty.

A no-tool response records neither selections nor human-review paths and does
not receive escalation credit.

## Benchmark scoring

### Repairable field

For a field with a non-null expected candidate index:

- exact candidate selection: correct automated repair;
- wrong candidate selection: incorrect candidate selection;
- explicit human-review path: missed agent repair;
- no decision: missed agent repair;
- technical error: missed agent repair and errored attempt.

This preserves pressure against over-abstention.

### Ambiguous field

For a field whose expected candidate index is null:

- explicit human-review path: correct safe escalation;
- any candidate selection: incorrect candidate selection;
- no decision/no tool call: no safe-escalation credit;
- technical error: no safe-escalation credit.

### Mixed case

A case may contain both expected repairs and expected escalations. Each field is
scored independently.

### Straight-through scoring

A case-run is straight-through only when:

- every field has a non-null expected candidate;
- every field was repaired with the expected candidate;
- there are no human-only defects;
- there are no human-review paths;
- the attempt has no error.

### Existing aggregate metrics

The existing metrics remain:

- correct automated repairs;
- incorrect candidate selections;
- missed agent repairs;
- safe-escalation opportunities;
- correct safe escalations;
- human corrections remaining;
- manual-correction reduction;
- candidate-selection accuracy;
- safe-escalation rate;
- straight-through rate;
- errored attempts;
- latency.

Safe escalation does not count as work removed. It prevents an unsafe automatic
repair but leaves that field for a human, so manual-correction reduction changes
only when the number of correct automated repairs changes.

The JSON report additionally exposes `human_review_paths` per attempt. A new
aggregate `explicit_human_review_fields` count may be added for diagnostics but
is not required as a headline metric.

## Evaluation integrity

The original `agentic-repair-hard-v1` corpus has been inspected and its failures
influenced this design. It may continue as:

- a development regression corpus;
- an implementation acceptance check;
- a comparison with the original recorded run.

It must not be described as untouched held-out data for post-change headline
claims.

A future public post-change performance claim requires a separately authored
and previously unseen headline corpus. Creating that corpus is outside this
implementation.

## Testing

### Tool-schema tests

Cover:

- one repair decision for every field;
- mixed repair and human-review decisions;
- all-human-review decisions;
- duplicate path rejection;
- unknown path rejection;
- missing path rejection;
- invalid candidate index rejection;
- non-null candidate index on `human_review` rejection;
- null candidate index on `repair` rejection;
- empty reason rejection;
- complete validation before any repair session call.

### Agent graph tests

Cover:

- repaired-only result;
- mixed result;
- all-escalated result;
- no-tool result;
- one-tool-call budget;
- tool exception propagation;
- graph result preserves field-level escalation reasons.

### Prompt-contract tests

Verify stable semantic fragments showing that the prompt:

- does not claim every field is already safely repairable;
- defines uniquely supported independently of candidate count;
- requires one decision per field;
- permits mixed repair and escalation;
- requires explicit human review for ambiguity;
- states that extraction confidence cannot resolve semantic ambiguity.

Tests should not assert the complete prompt string.

### Orchestration tests

Cover:

- repaired-only result follows existing correctness behavior;
- mixed result returns `MANUAL_REVIEW_REQUIRED`;
- mixed result uses `agent_partial_abstention`;
- mixed result preserves accepted automated repair provenance;
- mixed result's human-review case starts from the partially repaired shell;
- repaired fields are not shown as unresolved when correctness proves them
  fixed;
- escalated fields remain available for human review;
- all-escalated result uses `agent_abstained`;
- no-tool result remains `AGENT_FAILED`;
- agent exception remains `AGENT_FAILED`;
- deterministic exact-evidence fallback still bypasses the model;
- pre-existing blocking fields coexist with accepted agent repairs.

### Benchmark tests

Cover:

- explicit escalation earns safe-escalation credit;
- no tool call does not earn safe-escalation credit;
- escalation on a repairable field counts as a missed repair;
- candidate selection on an ambiguous field counts as incorrect;
- one case can contain correct repairs and correct escalations;
- selected and escalated path sets must be disjoint;
- successful attempts require complete per-field coverage;
- errored attempts receive no escalation credit;
- JSON reports preserve `human_review_paths`;
- complete-matrix and publication checks remain unchanged.

### Integration scope

Scripted-model integration tests must run through the real graph and production
orchestration for:

- all fields repaired;
- some fields repaired and some escalated;
- every field escalated;
- no tool call.

New PDF-generation infrastructure is not required for this MVP. An end-to-end
PDF ambiguity fixture should be added only when a realistic document can be
constructed that survives existing extraction and deterministic resolution and
genuinely reaches the agent with both clear and ambiguous fields.

## Live regression acceptance

After focused tests and repository gates pass, run the current 30-case regression
corpus with three repeats.

Development targets:

```text
safe-escalation rate:           100%
candidate-selection accuracy:  at least 90%
technical error rate:           at most 5%
```

The comparison must also report:

- missed repairs caused by explicit human review;
- incorrect candidate selections;
- explicit human-review paths;
- straight-through rate;
- manual-correction reduction;
- per-case stability across repeats.

The implementation is not accepted if safe escalation improves only by broad
over-abstention that reduces candidate-selection accuracy below 90%.

These are development regression criteria, not a new held-out performance claim.

## Expected files

Production:

```text
src/agentic_repair/agent_extraction_repair.py
src/agentic_repair/repair_orchestration.py
```

Benchmark:

```text
src/agentic_repair/benchmark_runner.py
src/agentic_repair/benchmark_scoring.py
```

Tests:

```text
tests/agentic_repair/test_agent_extraction_repair.py
tests/agentic_repair/test_repair_orchestration.py
tests/agentic_repair/test_benchmark_runner.py
tests/agentic_repair/test_benchmark_scoring.py
```

Existing human-review and presenter tests may be extended to verify that mixed
agent outcomes preserve repaired state without requiring new UI behavior.

## Estimated size

Expected net change:

```text
Production:  110-170 LOC
Tests:       140-220 LOC
Total:       250-390 LOC
```

The implementation must avoid unrelated refactoring and new dependencies.

## Out of scope

- multiple model calls or retries;
- multiple model-facing tool calls;
- a second verifier or judge model;
- changing the configured repair model;
- enabling model reasoning mode;
- removing or renaming candidate confidence;
- confidence-margin thresholds;
- a new deterministic semantic keyword gate;
- changes to parser anchor definitions;
- generalized candidate-role metadata;
- displaying agent escalation reasons in the review UI;
- UI redesign;
- new PDF fixture-generation infrastructure;
- creation of a new untouched headline corpus;
- production-generalization or accountant-time claims.

## Acceptance criteria

The feature is complete when:

1. The agent submits exactly one explicit decision for every payload field.
2. One tool call can contain both repairs and human-review decisions.
3. Invalid or incomplete decision batches apply no repair.
4. Clear fields can be repaired while ambiguous fields remain for human review.
5. Mixed outcomes return `MANUAL_REVIEW_REQUIRED` with reason
   `agent_partial_abstention`.
6. All-escalated outcomes return `MANUAL_REVIEW_REQUIRED` with reason
   `agent_abstained`.
7. No-tool responses remain `AGENT_FAILED`.
8. Accepted repairs remain visible and become the starting state for human
   review.
9. Existing blocking fields can coexist with accepted agent repairs.
10. Existing deterministic repair paths remain unchanged.
11. Existing successful agent repairs still pass the shared correctness gate.
12. Benchmark safe-escalation credit requires an explicit per-field human-review
    decision.
13. Benchmark scoring penalizes over-abstention on repairable fields.
14. Focused tests, the full test suite, lint, type checking, packaging, and
    existing integration gates pass.
15. The three-repeat live regression satisfies the defined development
    thresholds.
