# Mixed agent-and-human fixture design

## Goal

Add one intentionally broken, single-page native-text PDF under `data/synthetic_data` that exercises the complete mixed repair path: Alfredo automatically resolves one safe field, preserves that change, then asks a human to supply a different field that has no legal candidate.

## Fixture

### `BROKEN_mixed_agent_and_human_nips.pdf`

Reuse the current v1 synthetic invoice values, layout, line items, and totals.

Introduce exactly two defects:

1. `seller.nip` is ambiguous because the seller block contains both checksum-valid values `8637940261` and `5423511615`. The true seller NIP remains on the literal `NIP:` line; the distractor appears only as unrelated reference text.
2. `buyer.nip` is missing because the buyer `NIP:` row has no value and exposes no usable candidate.

Expected first-pass workflow:

```text
seller.nip -> unique exact NIP-labelled candidate
           -> automated repair to 8637940261

buyer.nip  -> no candidates
           -> MANUAL_REVIEW_REQUIRED
```

The review screen must show:

- one read-only entry under `Agent changes` for `seller.nip: 8637940261`;
- one unresolved field for `buyer.nip`;
- no unresolved seller-NIP field;
- no other changed or unresolved fields.

The intended human correction is buyer NIP `5423511615`.

## Data flow

```text
upload mixed PDF
-> parse and extract evidence
-> route seller.nip to constrained automated repair
-> apply and validate seller.nip
-> retain buyer.nip as blocking
-> render review UI with preserved agent diff
-> reviewer enters buyer.nip = 5423511615
-> apply attributed human correction batch
-> rerun invoice correctness pipeline
-> READY_FOR_KSEF + downloadable FA(3) XML
```

The automated stage may only promote evidence already present in the PDF. It must not invent a value, alter source totals, or consume the human-only buyer field.

## Scope

Production extraction, routing, repair, correctness, and UI behavior should remain unchanged. The work adds the persisted PDF fixture, regression coverage, and a concise README entry. A production change is allowed only if the new test exposes a real violation of the already documented mixed-repair contract.

## Validation

Tests must use the real parser and real upload/session path and prove all of the following:

1. The persisted PDF is one page and contains extractable text.
2. Before repair, only `seller.nip` is repairable and only `buyer.nip` is blocking.
3. After the automated stage, the workflow remains in manual review with seller NIP `8637940261` already applied.
4. The review presenter exposes exactly one agent change and exactly one unresolved human field.
5. Submitting buyer NIP `5423511615` reaches `READY_FOR_KSEF`.
6. Generated XML passes the local FA(3) XSD validator and contains both expected NIPs.
7. Ruff, focused tests, full pytest, compileall, wheel build, installed-package smoke, and browser smoke pass.

## Non-goals

- No OCR or scanned-PDF support.
- No extra UI controls or visual redesign.
- No new agent capability or free-form value invention.
- No change to the existing two broken fixtures.
