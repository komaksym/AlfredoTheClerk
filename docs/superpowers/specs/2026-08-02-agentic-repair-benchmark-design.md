# Agentic Repair Benchmark Design

## Status update

This document originally defined `agentic-repair-hard-v1` as an untouched
headline corpus and treated a no-action model response as the safe outcome for
an ambiguous case.

After the first live run, its cases and failures were inspected to design the
explicit safe-abstention feature documented in
`2026-08-03-agent-safe-abstention-design.md`. The corpus is therefore now a
**development regression corpus**, not untouched held-out data for post-change
headline claims. A future headline claim requires a separately authored and
previously unseen corpus.

The current agent contract also requires an explicit per-field `human_review`
decision. A silent no-tool response is an agent failure and receives no
safe-escalation credit.

## Goal

Provide a reproducible synthetic benchmark that measures how much known
invoice-repair work the evidence-constrained agent removes before human review,
while separately measuring whether ambiguous fields are explicitly and safely
escalated.

The benchmark must support defensible controlled regression comparisons without
using confidential customer invoices or pretending to measure end-to-end
accounts-payable time.

## Claim boundary

The current 30-case corpus may support wording such as:

> In a controlled synthetic regression, the agent correctly repaired X% of
> agent-eligible fields and explicitly escalated Y% of ambiguous fields.

It must not be described as untouched held-out post-change performance because
its failures influenced the safe-abstention design. It also must not support
claims about production invoice distributions, accountant speed, total
invoice-processing cost, or end-to-end accounts-payable cycle time. Those
require untouched operational data or a human timing study.

## Evaluation boundary

The benchmark isolates the agentic decision layer:

```text
persisted corrupted-field scenario
-> AgentRepairPayload
-> production LangGraph runner
-> one submit_repair_decisions tool call
-> one repair or human_review decision per field
-> recorded candidate selections and explicit review paths
-> deterministic ground-truth scoring
```

Extraction, PDF rendering, monetary reconciliation, FA(3) mapping, XML
serialization, XSD validation, and KSeF submission remain covered by their
existing tests and workflows. They are not mixed into the agent decision score.
The no-agent baseline requires one human correction per known defect; the
agent-assisted path removes only correctly resolved defects.

## Corpus separation

The benchmark uses two persisted corpora with explicit, non-interchangeable
roles.

### Hard regression corpus

`data/benchmark_cases/agentic_repair_hard_v1.json` contains 30 separately
authored cases:

- 12 single-field agent-repairable cases;
- six multi-field agent-repairable cases;
- six mixed cases containing agent-repairable and human-only defects;
- three human-only cases with no legal agent action;
- three ambiguous cases where explicit `human_review` is expected.

Candidate metadata is neutral: `rule` and `rejected_by` must be null. Expected
answers occur at candidate indexes zero, one, and two, and at high, middle, and
low confidence ranks. The publication loader rejects the wrong corpus ID, empty
data, or answer-leaking metadata.

The corpus remains valuable for development regression and before/after
comparison, but it is no longer eligible for untouched post-change headline
claims.

### Generated sanity corpus

`data/benchmark_cases/agentic_repair_v1.json` contains 200 deterministic cases.
It remains useful for schema validation, payload conversion, tool-contract
coverage, scoring tests, and byte-for-byte regeneration checks.

Because its visible evidence and ground truth originate from the same generation
rules, it is explicitly ineligible for performance claims.

## Runtime model path

The live benchmark uses the existing `build_repair_model()` configuration and
production `runner()` graph. A benchmark-only recording session implements the
same `apply_repair_plan` method used internally for the repair subset, validates
paths, indexes, duplicate commands, and empty plans, and records accepted
candidate promotions. It does not mutate a canonical invoice because
correctness of the mutation kernel is tested separately.

The combined model tool validates that every payload field has exactly one
decision before applying any repair. The benchmark records:

- repair selections as `(path, candidate_index)`;
- explicit `human_review_paths`;
- whether the tool completed;
- latency and errors.

Human-only cases skip the model boundary. A model failure, malformed tool call,
invalid path, invalid candidate index, duplicate path, overlapping repair/review
actions, or incomplete successful decision batch is preserved as an invalid or
errored attempt.

## Complete evaluation matrix

For `N` selected cases and `R` configured repeats, scoring requires exactly
`N × R` uniquely identified attempts. Unknown cases, out-of-range run indexes,
duplicate identities, and missing case-run combinations fail scoring before any
aggregate metric is published.

For a successful tool-called attempt, repair paths and human-review paths must be
disjoint and their union must exactly cover every field in the case. A no-tool
response is allowed to reach scoring as a diagnostic outcome, but it receives no
safe-escalation credit.

Case limits are allowed for smoke runs, but the selected prefix still requires a
complete matrix for every configured repeat.

## Metrics

Deterministic scoring reports:

- `total_cases`;
- `total_attempts`;
- `total_defects`;
- `agent_eligible_fields`;
- `correct_automated_repairs`;
- `incorrect_candidate_selections`;
- `missed_agent_repairs`;
- `safe_escalation_opportunities`;
- `correct_safe_escalations`;
- `human_corrections_remaining`;
- `straight_through_cases`;
- `errored_attempts`;
- median and p95 model latency.

Derived metrics:

```text
manual_correction_reduction
  = correct_automated_repairs / total_defects

candidate_selection_accuracy
  = correct_automated_repairs / agent_eligible_fields

safe_escalation_rate
  = correct_safe_escalations / safe_escalation_opportunities

straight_through_rate
  = straight_through_cases / total_case_runs
```

Scoring rules are field-level:

- a repairable field receives repair credit only for the exact expected
  candidate;
- explicit human review on a repairable field is a missed repair;
- an ambiguous field receives safe-escalation credit only when its path is
  explicitly present in `human_review_paths`;
- selecting a candidate for an ambiguous field is an incorrect selection;
- a silent omission, no-tool response, or technical error receives no
  safe-escalation credit.

Safe escalation does not count as work removed. It prevents an unsafe automatic
repair but leaves the correction for a human. Raw per-attempt results remain in
the JSON report.

## Publication eligibility

The CLI writes JSON and Markdown diagnostics before checking execution
reliability. It then returns a nonzero status when:

- there are no model-evaluated attempts;
- every model-evaluated attempt failed; or
- the model-attempt error rate exceeds `--max-error-rate`.

The default threshold is 5%. Human-only cases are excluded from the error-rate
denominator because they intentionally do not call the model.

This boundary prevents a credential outage, provider failure, malformed-output
regression, or incomplete execution from producing a green benchmark workflow.
It does not by itself make the current corpus untouched or headline-eligible.

## Outputs

The CLI writes:

- machine-readable JSON containing corpus digest, model, every repair selection,
  every explicit human-review path, errors, aggregate metrics, methodology, and
  limitations;
- concise Markdown containing methodology, result tables, and limitations.

The recommended development regression uses three repeats over all 30 hard
cases. The manual GitHub Actions workflow passes the 5% execution-error threshold
explicitly and uploads both reports.

## CI and secrets

Ordinary CI validates both corpus roles, answer-leak rejection, complete matrix
validation, explicit per-field coverage, scoring, reports, production-graph
execution with scripted models, and the systemic-failure exit code without
calling an external model.

A separate manual-only workflow runs the live hard regression when
`DEEPSEEK_API_KEY` is configured. Push and pull-request CI never calls DeepSeek.

## Out of scope

- OCR or image-first invoice support;
- downloading third-party invoice datasets;
- production-generalization claims;
- human timing experiments;
- AP cost or cycle-time extrapolation;
- treating `agentic-repair-hard-v1` as untouched after its failures were
  inspected;
- changing extraction anchors or adding a duplicate semantic keyword layer;
- model retries or a second verifier model.
