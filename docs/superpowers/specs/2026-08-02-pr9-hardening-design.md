# PR #9 safety, provenance, browser, and CI hardening design

## Context

PR #9 currently combines the invoice-review UI redesign with repair-policy and XSD-runtime changes. An independent AI-assisted review identified valid issues in four areas: forced agent selection without a safe abstention path, incorrect provenance for deterministic repairs, browser smoke coverage that bypasses the JavaScript interaction contract, and definition-of-done gaps in CI and evidence retention. The user also requires the real KSeF TEST proof to run as a strict CI gate on every push and pull request.

This design addresses all validated findings in the existing PR without broad unrelated refactoring.

## Goals

1. Restore safe model abstention when evidence is ambiguous.
2. Record deterministic and model-assisted repairs with truthful provenance.
3. Remove duplicate deterministic fallback logic that cannot succeed on a second identical attempt.
4. Exercise the real browser interaction contract, not only HTTP routes and screenshots.
5. Make PDF download and fullscreen controls behave as labelled.
6. Add Python typechecking to the required CI sequence.
7. Preserve durable UI evidence and add a DAG-like system diagram.
8. Run a real KSeF TEST submission as a strict required CI job on every supported event.

## Non-goals

- Redesigning the extraction model or candidate-ranking system.
- Adding OCR, persistence, queues, remote storage, or multi-user review.
- Introducing a frontend framework.
- Replacing the existing repair kernel or correctness boundary.
- Splitting PR #9 into multiple pull requests.

## Repair safety

### Optional agent tool use

The LangChain model will still be bound to `apply_repair_plan`, but the binding will no longer force that tool through `tool_choice`. The system prompt will explicitly allow the model to abstain when the evidence cannot safely distinguish candidates.

The graph remains intentionally small:

```text
START -> llm_call -> tool_node -> END
                  \-> END on abstention
```

The model receives one call budget and the tool receives one call budget. A no-tool response is a valid abstention outcome, not a malformed run. At orchestration level it remains an unresolved automated attempt and is converted by `ReviewSession` into human review using the existing warning path.

### Ambiguity regression

A focused test will construct a routed seller-NIP field with two structurally valid, semantically indistinguishable candidates. A fake model will return no tool call. The assertions will prove:

- no candidate is promoted;
- the original shell remains unchanged;
- the workflow reports an unresolved agent outcome;
- the review session enters human review;
- no format-valid but semantically unsupported NIP reaches `READY_FOR_KSEF`.

This test complements, rather than replaces, the existing deterministic exact-label fixture.

## Truthful repair provenance

### Generic accepted-repair record

`RepairWorkflowResult` will stop treating every accepted automated repair as an `AgentRepairResult`. A small provenance-aware record will represent an accepted automated repair with:

- `repair_result: RepairResult`;
- `origin: DETERMINISTIC | AGENT`;
- optional agent execution metadata only when a model actually ran.

The exact names may follow existing project naming conventions, but the contract must make it impossible to record a deterministic repair as `tool_called=True`.

`AgentRepairResult` remains the output of the LangGraph runner. It is not reused to represent deterministic work.

### Presentation

The UI heading becomes `Automated changes`. Each displayed change includes its origin, such as `Deterministic rule` or `Agent`. Presenter types are renamed away from agent-only terminology where they may contain either source.

The mixed fixture must continue to show the seller NIP as a read-only automated change and expose only the buyer NIP for human correction.

### Dead fallback removal

The exact-label deterministic rule runs once before the agent. If it returns `None`, orchestration does not call the same function again with the same immutable session, context, and route after an exception, abstention, or missing result. Those outcomes go directly to the existing unresolved-agent path.

## Browser interaction coverage

### Playwright E2E

Playwright is added as a development dependency and used for one focused browser test against the actual FastAPI app. The test will:

1. open the upload page;
2. upload the human-review fixture;
3. wait for the review page;
4. focus and fill the manual buyer-NIP input;
5. assert JavaScript selected the hidden `manual` mode;
6. fill the reviewer field;
7. click `Confirm & continue`;
8. assert the result page reports `READY_FOR_KSEF`;
9. verify the generated XML remains downloadable.

The existing screenshot checks remain useful for visual regression and forced-dark-mode coverage, but they are no longer described as the complete browser E2E proof.

### Toolbar behavior

The PDF download action becomes a real download. The PDF response used by that control returns `Content-Disposition: attachment`, and Playwright verifies a PDF download event and non-empty file.

Fullscreen becomes a real button. JavaScript calls `requestFullscreen()` on the PDF document card and exits fullscreen when already active. The test stubs or observes the browser fullscreen API so the interaction is deterministic in headless CI.

## CI and evidence

### Main CI order

The main job runs in this order:

```text
install -> lint -> typecheck -> unit/integration tests -> browser E2E
        -> screenshot evidence -> compile -> wheel build -> installed-wheel smoke
```

Pyright is added to the development dependencies and configured in basic mode. CI runs it explicitly against `src` and `tests`. Existing inline Pyright suppressions may remain only where justified by third-party typing limitations.

### Durable screenshots

Canonical review and result screenshots are stored under `docs/evidence/pr9/` and referenced from the PR body. CI still captures fresh screenshots and uploads them as artifacts, then compares the required visual properties. Committed evidence provides a durable review record; CI artifacts provide per-run proof.

### System DAG

The PR body includes this Mermaid flow:

```mermaid
flowchart LR
    PDF[PDF upload] --> EX[Extraction and diagnostics]
    EX --> DR{Exact deterministic evidence?}
    DR -->|yes| AR[Deterministic repair]
    DR -->|no| AG{Agent can safely select?}
    AG -->|yes| RR[Agent repair tool]
    AG -->|abstain or fail| HR[Human review]
    AR --> CG[Correctness and FA(3) XSD gate]
    RR --> CG
    HR --> CG
    CG -->|ready| OUT[READY_FOR_KSEF and XML]
    CG -->|residual issue| HR
```

The PR title and summary are updated to describe both the UI redesign and repair-safety hardening.

## Strict always-on KSeF TEST gate

The `ksef-live` job becomes a normal CI job for push, pull request, and manual workflow events.

- The event-level opt-in condition is removed.
- `RUN_KSEF_LIVE` is set by the job or removed from the test contract.
- Missing `KSEF_TEST_TOKEN` or `KSEF_TEST_CONTEXT_NIP` is a hard failure, never a skip.
- KSeF TEST transport failures, rejections, or timeouts fail the job.
- The invoice number remains unique to avoid duplicate-submission collisions.
- The job depends on the successful main job so externally visible submissions are not attempted for commits that already fail local validation.
- Fork pull requests without repository secrets fail by design, matching the selected strict-gate policy.

The live test itself is simplified so `pytest -m ksef_live` always attempts the real proof when invoked. Credential validation emits a clear actionable error.

## Error handling

- Agent abstention is represented explicitly and routed to human review.
- Tool execution errors do not trigger a repeated deterministic pass.
- Browser E2E failures identify the interaction step that broke.
- Missing live-test secrets produce named CI errors.
- External KSeF TEST instability is intentionally treated as a failed required gate under the approved strict policy.

## Verification

Implementation is complete only when all of the following pass on the final PR head:

- deterministic exact-label regression;
- semantically indistinguishable candidate abstention regression;
- provenance tests for deterministic and agent origins;
- mixed automated-plus-human fixture flow;
- Playwright upload, correction, submit, download, and fullscreen checks;
- Ruff;
- Pyright;
- full pytest suite;
- screenshot visual checks;
- Python compilation;
- wheel build;
- isolated installed-wheel resource/XSD smoke;
- real KSeF TEST submission from the always-on `ksef-live` CI job.

## Scope control

Changes should be limited to the repair runner/orchestration result contract, presenter/template terminology, toolbar route and JavaScript behavior, focused tests, CI configuration, dependencies, evidence files, and PR metadata. No unrelated cleanup is included.