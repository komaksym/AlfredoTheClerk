# Active Implementation Plan

The current slice is the KSeF TEST single-invoice integration using a
pre-created KSeF token. Design status: approved and specified (2026-07-29).
Implementation planning starts only after review of the written design spec.

- Design:
  `docs/superpowers/specs/2026-07-29-ksef-test-token-integration-design.md`
- Branch: `codex/ksef-test-token-slice`
- Base: `main`
- Authentication: KSeF token
- Environment: KSeF TEST only
- HTTP: `httpx`
- Cryptography: `cryptography`

## Slice summary

`READY_FOR_KSEF`

`-> authenticate with KSeF token`

`-> open one FA(3) online session`

`-> encrypt and send one synthetic invoice`

`-> poll remote processing`

`-> ACCEPTED + KSeF number`

## Milestones

1. [ ] Add the TEST-only KSeF transport, configuration, and token-auth boundary.
2. [ ] Add online-session encryption and single-invoice submission.
3. [ ] Add bounded polling and structured accepted/rejected/timeout outcomes.
4. [ ] Prove the orchestration with unit/mocked-HTTP tests and one opt-in live
   KSeF TEST smoke test.
5. [ ] Run repository gates, update `SPEC.md`, and include the high-level DAG in
   the implementation PR.

## Explicit non-goals

- XAdES
- DEMO or production
- batch sessions
- UPO retrieval
- refresh-token lifecycle
- persistence
- general retries/idempotency infrastructure
- UI

The detailed task-by-task implementation plan will be written after the design
spec is reviewed and approved in-repo.
