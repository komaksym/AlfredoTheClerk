# Broken review fixtures design

## Goal

Add two intentionally broken, single-page native-text PDFs under `data/synthetic_data` so the local review UI can be exercised manually through both repair paths.

## Fixtures

### `BROKEN_agent_ambiguous_seller_nip.pdf`

Reuse the current v1 synthetic invoice values and layout. Keep the normal seller NIP `8637940261`, then add a second checksum-valid NIP `5423511615` inside the seller block as unrelated reference text.

Expected production extraction/routing:

```text
seller.nip -> ambiguous evidence with two usable candidates
           -> AGENT_REPAIR_AVAILABLE
           -> no blocking fields
```

The actual seller NIP remains on the `NIP:` line, while the distractor is labelled as unrelated reference text so the repair agent has evidence to choose the correct candidate without inventing a value.

### `BROKEN_human_missing_buyer_nip.pdf`

Reuse the same current v1 synthetic invoice values and layout, but render the buyer `NIP:` row with an empty value.

Expected production extraction/routing:

```text
buyer.nip -> unresolved evidence with no value candidates
          -> MANUAL_REVIEW_REQUIRED
          -> agent has no legal repair action
```

The intended manual value is the original fixture buyer NIP `5423511615`.

## Validation

Add regression tests using the real parser, production extraction pipeline, and deterministic repair router. The tests must prove the exact affected path and route for each PDF, not merely assert that the files exist or look broken.

Do not change parser/repair behavior to accommodate the fixtures. The fixtures must exercise current behavior as-is.
