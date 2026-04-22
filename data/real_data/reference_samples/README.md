# Real Invoice Reference Samples

This folder contains repo-local reference material for real invoice
layouts that should constrain template and extractor work.

Primary reference:

- [faktura-vat-wzor.png](/Users/koval/dev/AlfredoTheClerk/data/real_data/reference_samples/faktura-vat-wzor.png)

Secondary convenience artifact:

- [fakturaxl_reference_invoice_from_attachment.svg](/Users/koval/dev/AlfredoTheClerk/data/real_data/reference_samples/fakturaxl_reference_invoice_from_attachment.svg)

Agent instruction:

- Treat this sample as a real data reference, not as synthetic filler.
- Use the PNG as the authoritative visual source of truth; do not let
  the hand-made SVG override the real image.
- When the synthetic renderer or extractor disagrees with this sample,
  call out the mismatch explicitly instead of assuming the synthetic
  template is correct.
- For the current sample, the bank account appears in the summary area
  as `Konto bankowe`, not in the seller block as `Numer rachunku`.
