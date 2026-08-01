# Agentic Repair Benchmark Design

## Goal

Add a reproducible, persisted synthetic benchmark that measures how much known
invoice-repair work the evidence-constrained agent removes before human review.
The benchmark must support defensible resume claims without using confidential
customer invoices or pretending to measure end-to-end accounts-payable time.

## Claim boundary

The benchmark may support claims such as:

> Reduced required human field corrections by X% across N controlled synthetic
> invoice defects, with Y% candidate-selection accuracy and Z% safe escalation.

It must not support claims about production invoice distributions, accountant
speed, total invoice-processing cost, or end-to-end accounts-payable cycle time.
Those require real operational data or a human timing study.

## Evaluation boundary

The benchmark isolates the agentic decision layer:

```text
persisted corrupted-field scenario
-> existing AgentRepairPayload
-> existing LangGraph repair runner and apply_repair_plan tool contract
-> recorded candidate selections or no-action decision
-> deterministic ground-truth scoring
```

Extraction, PDF rendering, monetary reconciliation, FA(3) mapping, XML
serialization, XSD validation, and KSeF submission remain covered by their
existing tests and workflows. They are not mixed into the agent decision score.
This makes the comparison precise: the no-agent baseline requires one human
correction per known defect; the agent-assisted path removes only correctly
resolved defects.

## Persisted corpus

The checked-in corpus lives at:

```text
data/benchmark_cases/agentic_repair_v1.json
```

It contains 200 fully materialized cases. Loading the corpus never regenerates
business values from seeds. A deterministic corpus builder exists only to make
intentional regeneration reviewable and to assert that the checked-in artifact
matches the declared benchmark version.

Distribution:

- 80 single-field agent-repairable cases;
- 40 multi-field agent-repairable cases;
- 40 mixed cases containing agent-repairable and human-only defects;
- 20 human-only cases with no legal agent action;
- 20 ambiguous cases where candidates exist but none is sufficiently supported,
  so no tool call is the expected safe outcome.

Each case persists:

- stable case ID and category;
- agent-visible fields;
- current invalid value;
- complete candidate values and evidence metadata;
- expected candidate index, or `null` when the safe outcome is escalation;
- count of additional defects that have no agent-visible candidates.

Candidate order varies across cases. Correct answers are not tied to candidate
index, confidence ordering, or one fixed field type.

## Runtime model path

The live benchmark uses the existing `build_repair_model()` configuration and
existing `runner()` graph. A benchmark-only recording session implements the
same `apply_repair_plan` boundary, validates paths, indexes, duplicate commands,
and empty plans, and records accepted candidate promotions. It does not mutate a
canonical invoice because correctness of the mutation kernel is already tested
separately.

A model failure, malformed tool call, invalid path, invalid candidate index, or
duplicate path is isolated to the current attempt and recorded as an error. The
benchmark continues with the remaining cases.

## Metrics

For every run, deterministic scoring reports:

- `total_cases`;
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
  = straight_through_cases / total_cases
```

Incorrect or missing model actions never count as work saved. For repeated runs,
raw per-attempt results are preserved and aggregate metrics are computed across
all case-runs.

## Outputs

The CLI writes:

- machine-readable JSON containing benchmark metadata, corpus digest, every
  attempt, and aggregate metrics;
- a concise Markdown report containing methodology, metric definitions, result
  tables, and limitations suitable for linking from the README.

The CLI supports case limits for smoke runs and configurable repeated runs. The
recommended final evaluation uses three runs over all 200 cases.

## CI and secrets

Ordinary CI validates corpus loading, corpus invariants, scoring, report
rendering, payload conversion, and the recording-session safety checks without
calling an external model.

A separate manual-only GitHub Actions workflow may run the live benchmark when
`DEEPSEEK_API_KEY` is configured as a repository secret. It uploads JSON and
Markdown reports as artifacts. Push and pull-request events never call DeepSeek.

## Documentation

README documentation must:

- describe the benchmark as synthetic and controlled;
- show the exact command for a full repeated run;
- explain the agent-disabled baseline;
- separate benchmark results from industry context;
- avoid publishing placeholder performance numbers;
- retain current product limitations around native-text, single-page, supported
  invoice layouts.

## Out of scope

- OCR or image-first invoice support;
- downloading third-party invoice datasets;
- production-generalization claims;
- human timing experiments;
- AP cost or cycle-time extrapolation;
- prompt tuning against the final checked-in corpus;
- changing extraction, repair routing, correctness, UI, or KSeF behavior.
