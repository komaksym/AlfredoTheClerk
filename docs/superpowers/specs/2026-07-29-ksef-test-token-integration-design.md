# KSeF TEST Token Integration Design

## Summary

Implement the smallest remote KSeF slice that proves Alfredo can take one
synthetic invoice that already passed the local correctness pipeline and have it
accepted by the KSeF 2.0 TEST environment.

The approved system flow is:

`READY_FOR_KSEF`

`-> authenticate with a pre-created KSeF token`

`-> open one FA(3) online session`

`-> encrypt and send one FA(3) invoice`

`-> poll remote status`

`-> ACCEPTED + KSeF number`

This slice is TEST-only and has no legal effect. It must not expose a production
execution path.

## Goal

Given a `CorrectnessResult` whose status is `READY_FOR_KSEF` and which contains
locally validated FA(3) XML, authenticate to KSeF TEST with a pre-created KSeF
token, submit exactly one invoice through an online session, and return a
structured remote outcome containing the KSeF number when the invoice is
accepted.

The slice is complete only when one synthetic FA(3) invoice is accepted by the
real KSeF TEST API end to end.

## Non-goals

Do not implement any of the following in this slice:

- XAdES authentication
- DEMO or production environments
- batch sessions or multiple invoices per session
- UPO retrieval or storage
- refresh-token lifecycle management
- durable submission persistence or audit storage
- general retry or idempotency infrastructure
- UI or frontend work
- a reusable general-purpose KSeF SDK

Those are separate slices. In particular, local `READY_FOR_KSEF` and remote
`ACCEPTED` remain distinct states.

## Architecture

Add a dedicated KSeF integration boundary under `src/ksef/`. Extraction, repair,
human review, shell validation, FA(3) mapping, and XML generation must not know
about KSeF HTTP endpoints or cryptographic transport details.

At system level:

```text
existing correctness pipeline
        |
        v
CorrectnessResult(status=READY_FOR_KSEF, xml=...)
        |
        v
KSeF submission service
        |
        +--> KSeF token authentication
        +--> online session lifecycle
        +--> KSeF-required cryptography
        +--> HTTP transport
        |
        v
structured remote result
```

Use `httpx` for HTTP and `cryptography` for RSA-OAEP and AES-256-CBC. These are
new production dependencies and are justified because the repository currently
has no suitable HTTP transport or cryptography library for this protocol.

Keep the remote boundary small. The orchestration entry point should consume a
locally validated result and delegate protocol details to focused helpers rather
than duplicating correctness logic.

## Environment and safety boundary

This design supports KSeF TEST only.

Requirements:

- the KSeF API base URL is fixed to the TEST environment inside this slice
- no generic `environment="production"` switch exists
- the pre-created KSeF token is supplied at runtime and is never committed
- the authentication context is an explicitly supplied TEST NIP/context
- raw KSeF tokens, temporary auth tokens, access tokens, and refresh tokens must
  never appear in logs, exception messages, snapshots, or test fixtures
- locally invalid invoices must never trigger a network call

A future production slice must add its own explicit design and review rather
than turning this TEST client into production through configuration alone.

## Authentication flow

Use KSeF token authentication, not XAdES.

The flow is:

1. `POST /auth/challenge` and read the returned challenge and timestamp.
2. Build the UTF-8 byte string `{ksefToken}|{timestampMs}`, where `timestampMs`
   is the challenge timestamp expressed as Unix milliseconds.
3. Encrypt that byte string with the KSeF public key using RSA-OAEP with
   SHA-256/MGF1-SHA-256, then Base64-encode the ciphertext.
4. `POST /auth/ksef-token` with the challenge, NIP context, and encrypted token.
5. Receive `authenticationToken` and `referenceNumber`.
6. Poll `GET /auth/{referenceNumber}` using the temporary authentication token
   until authentication reaches a terminal state or a bounded timeout expires.
7. On success, call `POST /auth/token/redeem` once and obtain `accessToken` and
   `refreshToken`.

Only the `accessToken` is needed by the rest of this slice. The returned
`refreshToken` may be represented in the immediate auth result if the KSeF
response requires it to be parsed, but refresh behavior is out of scope.

Authentication failures are structured remote failures. They must not escape as
ambiguous generic exceptions unless the failure is truly unexpected transport
or programming behavior.

## Online session and invoice encryption

After authentication succeeds:

1. Generate one random 256-bit AES key and one random 128-bit IV for the online
   session.
2. Encrypt the FA(3) XML with AES-256-CBC and PKCS#7 padding.
3. Encrypt the AES key with the KSeF public key using RSA-OAEP with
   SHA-256/MGF1-SHA-256.
4. Open one online session for the FA(3) form using the access token and the
   encrypted session-key material required by the current KSeF TEST contract.
5. Submit exactly one encrypted invoice to that session, including the required
   plaintext/ciphertext sizes and hashes from the current API contract.
6. Poll the invoice/session status with bounded polling until the invoice is
   accepted, rejected, or times out.

This slice may close the online session when required for clean protocol
completion, but session UPO retrieval remains out of scope.

## Domain boundary and result states

The local correctness result is the input gate, not the remote result model.

The submission entry point must reject anything whose local status is not
`READY_FOR_KSEF` before authentication or any other network activity.

Remote outcomes must distinguish at least:

- `ACCEPTED`
- `REJECTED`
- `PENDING_TIMEOUT`
- authentication/session/submission protocol failure

An accepted result contains at minimum:

- the remote invoice reference returned during submission
- the KSeF number returned after acceptance
- the final remote status

Session/reference metadata may also be returned when it is useful for debugging,
but it must not expand into persistence or audit-history infrastructure in this
slice.

## Error handling

Expected failures should be structured and explicit.

Fail closed for:

- input not in `READY_FOR_KSEF`
- missing KSeF TEST token
- missing authentication NIP/context
- authentication rejection
- session-open failure
- invoice submission rejection
- malformed required KSeF response fields
- bounded polling timeout
- remote invoice rejection

HTTP non-success responses should retain safe diagnostic information such as
HTTP status and KSeF error codes/details when available, while redacting all
credentials and bearer tokens.

Do not automatically resubmit an invoice after an ambiguous network failure.
Without durable idempotency state, silent retry could create duplicate remote
submissions. Recovery behavior is a later slice.

## Testing

Use three layers.

### Unit tests

Cover deterministic pieces without network access:

- token + timestamp plaintext construction
- RSA-OAEP wrapper behavior using test keys
- AES-256-CBC encryption/padding and required metadata
- request/response parsing
- rejection of non-`READY_FOR_KSEF` inputs before transport
- redaction of secrets from errors

### HTTP orchestration tests

Use mocked HTTP responses to cover the complete orchestration path:

- successful token authentication, polling, and redeem
- successful session open and one-invoice submission
- accepted and rejected invoice outcomes
- auth and invoice polling timeouts
- malformed/error responses
- no accidental second submission after an ambiguous send failure

These tests must not require external credentials.

### Live KSeF TEST smoke test

Add one explicit opt-in live test that:

- requires runtime TEST credentials/context
- uses one synthetic FA(3) invoice from the existing locally validated path
- calls the real KSeF TEST API
- succeeds only when the invoice reaches remote acceptance and a KSeF number is
  returned
- is skipped by default in normal local/CI test runs when credentials are absent

The live test must have no way to target production.

## Dependencies and validation

Add production dependencies:

- `httpx`
- `cryptography`

Do not add another KSeF client dependency in this slice.

After each milestone, run the narrowest relevant tests first. Before completion,
run:

```bash
uv run ruff check src tests
uv run pytest
uv run python -m compileall src tests
uv build
```

No static typechecker is currently configured in the repository. Do not add one
as incidental scope; document that the typecheck gate is not applicable until a
typechecker is intentionally introduced.

## PR and documentation requirements

The implementation PR must:

- explain the TEST-only boundary and KSeF-token authentication choice
- include a small high-level DAG showing:
  `READY_FOR_KSEF -> token auth -> online session -> encrypt/send -> poll -> ACCEPTED`
- report the focused and full validation results
- avoid screenshots because this slice has no frontend
- update `SPEC.md` when the slice is complete

Commits should use a short conventional summary and a descriptive body so the
change can be understood at both headline and detailed levels.

After every multi-file implementation step, report one line per changed file
summarizing what changed.

## Acceptance criteria

This slice is done when all of the following are true:

- only `READY_FOR_KSEF` invoices can enter remote submission
- KSeF token authentication works against the real KSeF TEST environment
- one online FA(3) session can be opened
- one synthetic FA(3) invoice can be encrypted and submitted
- asynchronous processing is polled with bounded timeouts
- remote rejection remains distinct from local correctness failure
- an accepted invoice returns its KSeF number
- secrets are not exposed in logs/errors/tests
- focused tests, Ruff, pytest, compileall, and build pass
- the opt-in live TEST smoke test demonstrates `READY_FOR_KSEF -> ACCEPTED + KSeF number`

## High-level system DAG

```text
READY_FOR_KSEF
      |
      v
Authenticate with KSeF token
      |
      v
Open FA(3) online session
      |
      v
Encrypt and send one invoice
      |
      v
Poll remote processing
      |
      v
ACCEPTED + KSeF number
```
