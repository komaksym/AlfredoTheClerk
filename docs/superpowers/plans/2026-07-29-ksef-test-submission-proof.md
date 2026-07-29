# KSeF TEST Submission Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove one locally valid synthetic FA(3) invoice can be accepted by KSeF TEST using token authentication, encrypted online submission, bounded polling, and ambiguity-safe reconciliation.

**Architecture:** Add a dedicated `src/ksef/` boundary split into TEST-only config, models, crypto, transport, and orchestration. Reuse the existing correctness result as the only local submission gate; use `httpx` and `cryptography`; never expose a production origin or blindly retry invoice submission.

**Tech Stack:** Python 3.13, httpx, cryptography, pytest, Ruff, uv.

## Global Constraints

- Implement on `codex/ksef-test-submission-proof`, based on `codex/human-review-workflow`.
- KSeF origin is fixed to `https://api-test.ksef.mf.gov.pl/v2`.
- Only complete `READY_FOR_KSEF` results with non-empty XML and successful local XSD validation may submit.
- Secrets never appear in results, exceptions, logs, or test output.
- Invoice submission POST is never automatically retried.
- Ambiguous submission is reconciled via the session invoice list and otherwise returns `PENDING/SUBMISSION_UNKNOWN`.
- Live submission is opt-in only via marker plus `RUN_KSEF_LIVE=1` and required TEST credentials.
- UPO, persistence, refresh lifecycle, DEMO/production, XAdES, batch, and process-restart recovery are out of scope.

## Milestones

1. [ ] Add dependencies, TEST-only config, result/status models, and crypto primitives with focused unit coverage.
2. [ ] Add strict typed transport calls, public-key discovery, authentication, and `21470` key-refresh behavior.
3. [ ] Add online session submission, polling, ambiguous-send reconciliation, and cleanup semantics with fake-HTTP end-to-end coverage.
4. [ ] Add opt-in live TEST proof, update `SPEC.md`, run focused/full validation, and publish PR with the required DAG.
