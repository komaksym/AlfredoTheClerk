# KSeF TEST Submission Proof Design

## Purpose

The local correctness boundary can produce FA(3) XML with
`CorrectnessStatus.READY_FOR_KSEF`, but Alfredo does not yet prove that KSeF can
remotely accept that artifact.

This slice adds one narrow vertical proof:

```text
synthetic domestic VAT shell
  -> existing correctness pipeline
  -> READY_FOR_KSEF
  -> KSeF TEST token authentication
  -> encrypted online session
  -> one FA(3) submission
  -> status polling
  -> ACCEPTED + KSeF number
```

Completing this slice proves protocol compatibility with KSeF TEST. It does not
complete the broader KSeF product integration. Persistent history, UPO storage,
durable recovery, access-token refresh, and production rollout remain later
slices.

## Branch and dependency

Implement this slice on a new `codex/ksef-test-submission-proof` branch.

The branch depends on the correctness and human-review work currently present
on `codex/human-review-workflow`. If implementation begins before that branch is
merged, create the new branch from it and rebase onto `main` after the dependency
merges.

## Product invariants

- The domestic VAT shell remains the canonical business object.
- Only a complete `CorrectnessResult` whose status is `READY_FOR_KSEF`, whose
  XML is non-empty, and whose local XSD result is successful may cross the KSeF
  boundary.
- Local readiness and remote acceptance remain separate states.
- KSeF HTTP, authentication, encryption, polling, and response models remain
  under a dedicated `src/ksef/` boundary.
- Extraction, agent repair, human review, FA(3) mapping, and XML rendering do
  not know KSeF HTTP details.
- The slice targets KSeF TEST only and contains no production endpoint.
- Expected remote and protocol failures return structured outcomes.
- Secrets never appear in result representations, exceptions, logs, or test
  output.
- An ambiguous submission is never treated as a confirmed rejection and is
  never blindly resubmitted.

## Supported environment

The only base URL in this slice is a source-code constant:

```text
https://api-test.ksef.mf.gov.pl/v2
```

The caller cannot supply or override a base URL. Tests inject an
`httpx.MockTransport` rather than another endpoint, so requests retain the
canonical TEST origin while no network call occurs.

Runtime configuration supplies only:

- `KSEF_TEST_TOKEN`: a pre-created KSeF TEST token;
- `KSEF_TEST_CONTEXT_NIP`: the synthetic seller context authorized by the
  token;
- `RUN_KSEF_LIVE=1`: the second opt-in gate for the live test.

For this proof, the configured context NIP must equal the synthetic seller NIP.
Broader delegated-context authorization belongs to durable integration.

## Architecture

Add a focused package with three responsibilities:

```text
submit_ready_invoice()
  ├─ KsefTransport
  │    HTTP endpoints + strict response parsing
  ├─ KsefCrypto
  │    key selection + RSA/AES encryption + hashes
  └─ polling/reconciliation policy
```

Suggested file ownership:

- `src/ksef/config.py`: TEST-only configuration and fixed origin;
- `src/ksef/models.py`: keys, status, stage, and structured result models;
- `src/ksef/crypto.py`: pure certificate selection and cryptographic helpers;
- `src/ksef/transport.py`: typed KSeF endpoint calls and response validation;
- `src/ksef/submission.py`: preconditions, authentication, session lifecycle,
  submission, reconciliation, polling, and cleanup.

`httpx` handles transport. `cryptography` handles X.509 parsing, RSA-OAEP,
AES-256-CBC, and PKCS#7 padding. Both become direct production dependencies
because code under `src/` imports them.

## Dynamic public-key discovery

Fetch all current KSeF certificates with:

```text
GET /security/public-key-certificates
```

Select certificates independently by `usage`:

- `KsefTokenEncryption` encrypts
  `{KSEF_TOKEN}|{challenge_timestamp_ms}` during authentication;
- `SymmetricKeyEncryption` encrypts the locally generated AES session key used
  for invoice encryption.

A selected certificate must be valid at the time of the operation. If several
valid certificates support the required usage, select the one with the latest
`validFrom`. Pass its `publicKeyId` to the endpoint that consumes the encrypted
value.

Do not pin a certificate or public key in source control. A small in-memory
cache is allowed, but error `21470` must invalidate it. On `21470`, refetch the
certificate list, reselect and re-encrypt with the new key, and retry that
pre-submission operation once.

The two key usages are not interchangeable even though both currently use
RSA-OAEP with SHA-256.

## Authentication

Authenticate with the configured TEST token:

```text
POST /auth/challenge
  -> challenge + timestamp

"{KSEF_TEST_TOKEN}|{timestamp_ms}"
  -> RSA-OAEP SHA-256 with KsefTokenEncryption certificate
  -> Base64 encryptedToken

POST /auth/ksef-token
  -> challenge + NIP context + encryptedToken + publicKeyId
  -> authenticationToken + referenceNumber

GET /auth/{referenceNumber}
  -> poll until authentication succeeds or terminates

POST /auth/token/redeem
  -> accessToken + refreshToken
```

The temporary `authenticationToken` is redeemable once. Do not attach generic
POST retry behavior to `/auth/token/redeem`; a repeated redemption with the same
token returns HTTP 400. If its response is lost, return a structured
authentication failure and require a new authentication flow.

The access token is held in memory only for this run. Refresh-token lifecycle is
outside this slice.

## Invoice encryption and online session

Generate once for the online session:

```text
AES key: 256 random bits
IV:      128 random bits
```

Encrypt the exact UTF-8 FA(3) XML bytes with AES-256-CBC and PKCS#7 padding.
Encrypt the AES key with the selected `SymmetricKeyEncryption` RSA certificate
using OAEP SHA-256.

Compute and send:

- original XML byte size;
- Base64 SHA-256 of original XML bytes;
- encrypted XML byte size;
- Base64 SHA-256 of encrypted XML bytes;
- Base64 encrypted XML.

Open one FA(3) online session:

```text
POST /sessions/online
```

The request includes the encrypted AES key, IV, selected `publicKeyId`, and FA(3)
form code. Submit exactly one invoice:

```text
POST /sessions/online/{session_reference}/invoices
```

The response must provide an invoice reference before direct invoice polling
begins.

## Result model

Use a result model that distinguishes confirmed remote truth from local
technical failure:

```text
KsefSubmissionStatus
  ACCEPTED  KSeF returned terminal success and a non-empty KSeF number
  REJECTED  KSeF returned a terminal invoice rejection
  PENDING   the remote result is non-terminal or cannot yet be known safely
  FAILED    the flow failed before remote invoice evaluation was possible
```

Track the failing or uncertain boundary separately:

```text
KsefFailureStage
  PRECONDITION
  KEY_DISCOVERY
  AUTH
  SESSION_OPEN
  SUBMIT
  POLL
  SESSION_CLOSE
```

The structured result carries, when available:

- session reference;
- invoice reference;
- original invoice hash and invoice number used for reconciliation;
- KSeF number;
- remote status code and description;
- failure stage and stable local error code;
- redacted diagnostics.

An accepted result requires all of:

```text
status == ACCEPTED
session_reference
invoice_reference
ksef_number
```

A poll deadline produces `PENDING`, not `FAILED`, because the invoice may still
be processing remotely. A precondition or authentication failure produces
`FAILED`. A terminal KSeF validation decision produces `REJECTED`.

## Retry and ambiguous-submission policy

Retries are allowed only when the operation is known to be safe:

- retry certificate-dependent authentication or session opening once after
  `21470`, after refetching and re-encrypting;
- repeat status `GET` requests within a bounded polling deadline;
- respect `Retry-After` without extending that deadline.

Do not automatically retry the invoice-submission POST. A timeout or broken
connection can occur after KSeF accepted the request but before Alfredo received
the invoice reference.

For an ambiguous submission:

1. Preserve the session reference, unique invoice number, and original invoice
   hash.
2. Query `GET /sessions/{session_reference}/invoices`.
3. Match the remote invoice by both original invoice hash and unique invoice
   number.
4. If exactly one match exists, recover its invoice reference and resume
   polling.
5. If no unique match can be proven before the deadline, return
   `PENDING` with stable code `SUBMISSION_UNKNOWN`.
6. Never resubmit automatically in this slice.

Durable persistence and later reconciliation across process restarts belong to
the next integration slice.

## Session cleanup

Attempt to close the online session after the invoice reaches a terminal status
or the bounded polling/reconciliation flow ends.

Session-close failure is cleanup metadata. It must not replace a known
`ACCEPTED` or `REJECTED` invoice result. If the result is already `PENDING`,
preserve the pending state and all available references.

UPO retrieval is not part of this proof. UPO is the Ministry of Finance-signed
XML receipt proving acceptance; downloading, validating, and storing it belongs
to the durable integration slice.

## Fail-closed behavior

Return structured failures for:

- input status other than `READY_FOR_KSEF`;
- absent XML or unsuccessful local XSD validation;
- missing KSeF TEST token or context NIP;
- seller NIP different from the configured TEST context;
- no currently valid certificate for either required usage;
- malformed or purpose-mismatched certificate data;
- authentication rejection or deadline;
- malformed KSeF response;
- session-open failure;
- confirmed remote invoice rejection;
- polling deadline;
- ambiguous invoice-submission outcome.

Unexpected programmer errors remain exceptions. Expected KSeF, transport, and
protocol failures must not be collapsed into generic exceptions.

Authentication request/response bodies, bearer headers, KSeF tokens,
authentication tokens, access tokens, and refresh tokens are never included in
diagnostics. Transport exceptions are converted to allowlisted metadata rather
than storing raw request objects.

## Testing

### Crypto and model unit tests

Use generated RSA private keys so tests can decrypt produced ciphertext and
assert the exact plaintext. Cover:

- certificate usage, validity, and latest-`validFrom` selection;
- no eligible certificate;
- RSA-OAEP SHA-256 token and AES-key encryption;
- AES-256-CBC encryption and PKCS#7 padding;
- original and encrypted hashes and byte sizes;
- accepted-result invariants;
- status and failure-stage classification;
- secret-safe representations.

### Fake-HTTP orchestration tests

Use `httpx.MockTransport` with the fixed TEST origin. Exercise the complete
orchestrator with scripted responses:

- key discovery and successful token authentication;
- authentication `100 -> 200` followed by one redemption;
- invoice `100 -> 150 -> 200` with a KSeF number;
- terminal remote rejection;
- polling deadline returning `PENDING`;
- malformed JSON and missing required fields;
- `21470`, certificate refresh, re-encryption, and one retry;
- no second redemption attempt;
- submission response loss followed by successful session reconciliation;
- unresolved ambiguous submission returning `SUBMISSION_UNKNOWN`;
- session-close failure preserving the primary invoice result;
- no token or bearer value in exceptions and captured logs.

These tests use the real cryptographic and orchestration implementations. Only
the network transport is fake.

### Live KSeF TEST proof

Register a `ksef_live` pytest marker. The test also skips unless
`RUN_KSEF_LIVE=1`, `KSEF_TEST_TOKEN`, and `KSEF_TEST_CONTEXT_NIP` are present.
A marker labels the test; the environment guard prevents accidental execution.

The live test:

1. Builds a synthetic domestic VAT shell whose seller NIP equals the configured
   TEST context.
2. Generates a unique invoice number for that run.
3. Uses an issue date that is not in the future.
4. Runs the existing real correctness pipeline.
5. Asserts `READY_FOR_KSEF`, non-empty XML, and successful local XSD validation.
6. Calls the real KSeF TEST submission service.
7. Asserts `ACCEPTED` and non-empty session reference, invoice reference, and
   KSeF number.

Do not mock correctness, cryptography, HTTP, or KSeF in this test. Do not place
real taxpayer or customer data in the synthetic invoice. Ordinary CI and
`uv run pytest` must not make a live submission.

## Explicitly out of scope

- DEMO and production environments;
- arbitrary base URLs;
- XAdES authentication;
- batch sessions;
- multiple invoices per session;
- UPO download, verification, or storage;
- access-token refresh lifecycle;
- persistent submission and status history;
- process-restart recovery;
- automatic invoice resubmission or a general idempotency system;
- UI or operator workflow;
- a general-purpose KSeF SDK.

## Definition of done

The slice is complete when:

```text
one unique synthetic invoice
  -> real local correctness pipeline
  -> READY_FOR_KSEF
  -> real KSeF TEST authentication
  -> encrypted online submission
  -> terminal remote status
  -> ACCEPTED + KSeF number
```

Additionally:

- focused crypto and model tests pass;
- fake-HTTP orchestration tests pass;
- the explicitly enabled live KSeF TEST proof passes;
- the ordinary test suite cannot submit remotely;
- Ruff, pytest, compileall, and package build pass;
- the PR includes a high-level DAG of the completed system flow;
- `SPEC.md` marks only the TEST submission proof complete;
- durable KSeF integration remains active until persistence, recovery, UPO, and
  history requirements are implemented.

## Official contract references

- [KSeF OpenAPI](https://api-test.ksef.mf.gov.pl/docs/v2/index.html)
- [Authentication](https://github.com/CIRFMF/ksef-api/blob/main/uwierzytelnianie.md)
- [Public encryption keys and rotation](https://github.com/CIRFMF/ksef-api/blob/main/bezpieczenstwo/klucze-publiczne-do-szyfrowania.md)
- [Online sessions](https://github.com/CIRFMF/ksef-api/blob/main/sesja-interaktywna.md)
- [Invoice verification](https://github.com/CIRFMF/ksef-api/blob/main/faktury/weryfikacja-faktury.md)
- [Session status and UPO](https://github.com/CIRFMF/ksef-api/blob/main/faktury/sesje/sesja-sprawdzenie-stanu-i-pobranie-upo.md)
