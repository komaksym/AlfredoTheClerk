# Agentic Repair Benchmark Design

## Goal

Add a reproducible synthetic benchmark that measures how much known
invoice-repair work the evidence-constrained agent removes before human review.
The benchmark must support defensible controlled-evaluation claims without using
confidential customer invoices or pretending to measure end-to-end
accounts-payable time.

## Claim boundary

The benchmark may support claims such as:

> Reduced required human field corrections by X% across N held-out controlled
> synthetic invoice cases, with Y% candidate-selection accuracy and Z% safe
> escalation.

It must not support claims about production invoice distributions, accountant
speed, total invoice-processing cost, or end-to-end accounts-payable cycle time.
Those require untouched real operational data or a human timing study.

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
The no-agent baseline requires one human correction per known defect; the
agent-assisted path removes only correctly resolved defects.

## Corpus separation

The benchmark uses two persisted corpora with explicit, non-interchangeable
roles.

### Held-out hard corpus

`data/benchmark_cases/agentic_repair_hard_v1.json` contains 30 separately
authored cases and is the only corpus eligible for headline metrics:

- 12 single-field agent-repairable cases;
- six multi-field agent-repairable cases;
- six mixed cases containing agent-repairable and human-only defects;
- three human-only cases with no legal agent action;
- three ambiguous cases where no tool call is the expected safe outcome.

Candidate metadata is neutral: `rule` and `rejected_by` must be null. Expected
answers occur at candidate indexes zero, one, and two, and at high, middle, and
low confidence ranks. The publication loader rejects the wrong corpus ID,
empty data, or answer-leaking metadata.

### Generated sanity corpus

`data/benchmark_cases/agentic_repair_v1.json` contains 200 deterministic cases.
It remains useful for schema validation, payload conversion, tool-contract
coverage, scoring tests, and byte-for-byte regeneration checks.

Because its visible evidence and ground truth originate from the same generation
rules, it is explicitly ineligible for headline performance claims.

## Runtime model path

The live benchmark uses the existing `build_repair_model()` configuration and
existing `runner()` graph. A benchmark-only recording session implements the
same `apply_repair_plan` method, validates paths, indexes, duplicate commands,
and empty plans, and records accepted candidate promotions. It does not mutate a
canonical invoice because correctness of the mutation kernel is tested
separately.

Human-only cases skip the model boundary. A model failure, malformed tool call,
invalid path, invalid candidate index, or duplicate path is isolated to the
current attempt and preserved in diagnostic output.

## Complete evaluation matrix

For `N` selected cases and `R` configured repeats, scoring requires exactly
`N × R` uniquely identified attempts. Unknown cases, out-of-range run indexes,
duplicate identities, and missing case-run combinations fail scoring before any
aggregate metric is published.

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

Incorrect, missing, or errored model actions never count as work saved. Raw
per-attempt results remain in the JSON report.

## Publication eligibility

The CLI writes JSON and Markdown diagnostics before checking publication
eligibility. It then returns a nonzero status when:

- there are no model-evaluated attempts;
- every model-evaluated attempt failed; or
- the model-attempt error rate exceeds `--max-error-rate`.

The default threshold is 5%. Human-only cases are excluded from the error-rate
denominator because they intentionally do not call the model.

This boundary prevents a credential outage, provider failure, malformed-output
regression, or incomplete execution from producing a green benchmark workflow.

## Outputs

The CLI writes:

- machine-readable JSON containing corpus digest, model, every attempt, errors,
  aggregate metrics, methodology, and limitations;
- concise Markdown containing methodology, result tables, and limitations.

The recommended headline evaluation uses three repeats over all 30 held-out hard
cases. The manual GitHub Actions workflow passes the 5% threshold explicitly and
uploads both reports.

## CI and secrets

Ordinary CI validates both corpus roles, answer-leak rejection, complete matrix
validation, scoring, reports, production-graph execution with scripted models,
and the systemic-failure exit code without calling an external model.

A separate manual-only workflow runs the live held-out benchmark when
`DEEPSEEK_API_KEY` is configured. Push and pull-request CI never calls DeepSeek.

## Out of scope

- OCR or image-first invoice support;
- downloading third-party invoice datasets;
- production-generalization claims;
- human timing experiments;
- AP cost or cycle-time extrapolation;
- prompt tuning against the held-out hard corpus;
- changing extraction, repair routing, correctness, UI, or KSeF behavior.
