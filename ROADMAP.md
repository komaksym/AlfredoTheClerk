# ROADMAP

## 0. Current State

Today the repo has a deterministic synthetic domestic-VAT pipeline plus
one native-PDF render/extract loop:

`seed -> shell -> shell validation -> summary -> PDF render -> PDF parse/extract -> comparison`

and

`seed -> shell -> shell validation -> summary -> FA(3) mapping -> XML -> local XSD validation`

What already exists:

- schema-independent domestic VAT shell
- deterministic synthetic seed generation
- seed -> shell mapping
- shell validation
- shell summary / totals
- native PDF rendering for the current template
- deterministic PDF parsing / extraction for the current template
- field-level evidence and extraction diagnostics
- shell + summary -> `ksef_schema.schemat.Faktura` mapping
- FA(3) XML rendering
- CLI generation path
- offline FA(3) XSD validation in the default test suite

What does not exist yet:

- benchmark case artifacts
- persisted comparison policies or manifests
- KSeF API client

The roadmap should be read from that reality. This repo is not yet a benchmark
system. It already has an extraction baseline, but it is not yet a
reviewable benchmark system.

## 1. Near-Term Goal

Build a trustworthy benchmark contract for ordinary domestic VAT invoices in a
closed-loop, self-rendered native-PDF setting.

The order of work is:

1. Freeze canonical benchmark artifacts on disk.
2. Freeze the current renderer/extractor assumptions into reviewable benchmark
   artifacts and manifests.
3. Expand from the current deterministic baseline into hard cases and template
   diversity.
4. Add agentic repair only after deterministic extraction has a clear baseline.

## 2. Hard Constraints

- Scope stays limited to ordinary domestic VAT invoices.
- The shell is the canonical business-truth object.
- FA(3) XML is a downstream compliance artifact, not the source of truth.
- XML validity is necessary but not sufficient.
- Benchmarks must score only fields that are actually rendered and visible in
  the template.
- Benchmark cases must be reviewable on disk and loadable without regenerating
  them from seeds.
- `generated_at` must be fixed inside benchmark cases so target XML is stable.
- Row identity for line items is position-based until an explicit replacement
  policy is introduced.
- Scoped milestones must use validation that matches the extraction
  surface being scored, not a broader validator that turns expected
  omissions into noise.
- `payment_form` is scored only when it is both:
  - present in canonical truth
  - visible in the template

## 3. Benchmark Contract to Freeze First

Before expanding PDF benchmark coverage, freeze the benchmark contract.

Each benchmark case should own:

- canonical shell truth
- derived summary
- deterministic target FA(3) XML
- fixed `generated_at`
- local XSD validation result
- persisted comparison policy
- per-template visibility manifests
- metadata describing schema / fixture version

Suggested on-disk layout:

- `case.json`
- `shell.json`
- `summary.json`
- `target.xml`
- `xsd_validation.json`
- `comparison_policy.json`
- `manifests/no_pdf.json`

Important: M1 must fully specify JSON serialization for every non-JSON-native
type used in fixtures.

Required serialization rules:

- money fields: JSON strings, fixed-point, exactly the repo's `round_money`
  result
- `quantity`: JSON string, plain decimal, no scientific notation, preserve the
  exact value, max 6 fraction digits
- `unit_price_net`: JSON string, plain decimal, no scientific notation,
  preserve the exact value, max 8 fraction digits
- `vat_rate`: JSON string using the canonical business value, e.g. `"23"` or
  `"5"`
- `date`: ISO string, `YYYY-MM-DD`
- enums: serialize as `.value`
- nested dataclasses: nested JSON objects
- optional fields: omit when `None`

If any of those rules change, increment the benchmark-case schema version.

Comparison policy should be frozen in M1 too:

- exact match: dates, currency, VAT rates, line count
- normalized match: invoice number, NIP, phone, money, whitespace-heavy text
- not scored: fields without a deterministic canonicalizer yet

The evidence and diagnostics schemas should also be defined in M1, even though
they will not be populated until extraction milestones.

## 4. Milestone Outline

### M1. BenchmarkCase v0

Goal:

- turn the existing synthetic shell->XML pipeline into persisted benchmark
  cases

Deliver:

- `BenchmarkCase` concept
- create / load / validate case directories
- deterministic XML generation with fixed `generated_at`
- local XSD result stored with the case
- persisted comparison policy
- `manifests/no_pdf.json` with all fields marked `not_rendered`
- shell and summary comparators
- frozen serialization rules
- frozen evidence schema
- frozen diagnostics schema

Acceptance:

- a benchmark case can be created from the current pipeline
- load -> save is lossless
- target XML is deterministic for a fixed case
- case-owned XML passes local XSD validation
- mismatch reporting follows the persisted comparison policy

### M2. Renderer Spike and First Native-PDF Template

Goal:

- choose a renderer based on parser-visible extraction stability, not visual
  aesthetics

Spike:

- render the seller / buyer two-column block
- inspect extracted text and bounding boxes with `pdfplumber`
- reject any renderer that makes the two parties ambiguous to parse

Renderer choice is between:

- `WeasyPrint`, if extraction remains clean enough
- `reportlab`, if explicit coordinates are needed for clean parsing

Deliver:

- one renderer decision backed by the spike
- one pinned template
- pinned renderer version
- pinned fonts
- fixed locale / timezone assumptions for rendering
- first template manifest:
  `manifests/<template_id>.json`

Acceptance:

- seller and buyer blocks extract as separable regions
- header fields extract as separate tokens
- re-rendering the same case yields identical extracted text and bounding boxes
- only parser-visible stability is required, not byte-identical PDFs

### M3. Deterministic Extraction Baseline

Goal:

- ship the first deterministic extractor that reconstructs the current
  rendered invoice surface, not just header fields

Scored fields in M3:

- seller name, NIP, address lines
- buyer name, NIP, address lines
- invoice number
- issue date
- sale date
- `payment_form`, only when present in truth and visible in the template
- rendered line items
- rendered invoice totals

Critical correction:

- M3 must validate only the extraction surface that is actually rendered
  and scored by the current template
- do not treat non-rendered or not-yet-scored fields as extraction
  failures

Deliver:

- PDF extraction interface
- one `pdfplumber` backend
- draft shell result for the current rendered invoice surface
- field-level evidence objects
- extraction diagnostics
- normalization for NIP, whitespace, invoice number, dates, and money
- scoped comparison against the benchmark contract

Acceptance:

- rendered fields round-trip from template PDF back to canonical values
- evidence exists for every scored field
- diagnostics distinguish missing, ambiguous, and normalized values

### M4. Hard-Case Corpus and Robustness

Goal:

- harden deterministic extraction against harder layouts and ambiguous
  cases now that line-item extraction exists

Deliver:

- hard-case corpus covering:
  - wrapped descriptions
  - seller / buyer confusion
  - multiple nearby dates
  - totals near row values
  - punctuation-heavy identifiers
  - long names and addresses

Acceptance:

- scored header and line-item fields round-trip back to canonical truth
- reconstructed XML passes local XSD validation
- hard cases become stable regression fixtures
- row identity policy is still explicit and enforced

### M5. Template Diversity and Presentation Perturbations

Goal:

- prove extraction robustness across multiple native templates of the same
  canonical shell

Deliver:

- more templates
- per-template manifests
- semantic-preserving perturbations:
  - font changes
  - spacing shifts
  - label wording variants
  - block reordering
  - row wrapping

Acceptance:

- the same shell rendered through supported templates collapses back to the
  same scored meaning
- M4 hard-case regressions remain stable

### M6. Agentic Repair on Top of Deterministic Extraction

Goal:

- add a repair layer only after deterministic extraction is measurable

The repair loop may:

- choose among competing candidates
- fix normalization mistakes
- resolve ambiguity using extracted evidence

The repair loop may not:

- invent unsupported values
- bypass the shell stage
- emit XML directly as the primary output

Inputs:

- draft shell
- scoped or full validation errors
- evidence
- extraction diagnostics

Acceptance:

- cases that fail deterministic extraction but have enough support can be
  repaired to scored shell equivalence
- repaired shells still pass downstream validation, summary, mapping, and XSD

## 5. Non-Blocking KSeF Track

This track should not start with arbitrary synthetic fixtures immediately after
M1. That produces noisy failures because the current synthetic generator emits
optional seller identifiers that are not KSeF-hardened.

Minimum hygiene before the first KSeF smoke test:

- either use curated sandbox-acceptable identities
- or omit optional seller registry identifiers from smoke-test fixtures until
  they are validated
- clearly separate local XSD success from remote business-rule acceptance

Only after that hygiene exists should the first non-production smoke test run.

Deliver later:

- KSeF client behind an interface
- auth flow
- session handling
- invoice submission
- status polling
- UPO retrieval where supported
- remote-validation artifacts stored separately from local XSD artifacts

Acceptance:

- the system can tell apart:
  - locally valid XML
  - remotely rejected XML
  - remotely accepted XML

## 6. Validation Gates

For implementation work:

- run the narrowest relevant tests first
- run `uv run ruff check src tests`
- run `uv run pytest`
- run `uv run python -m compileall src tests`

Milestone gates:

- M1: deterministic benchmark-case creation, load/save stability, local XSD
- M2: renderer spike passes parser-visible stability checks
- M3: scoped rendered-surface equivalence plus evidence and diagnostics
- M4+: full scored-shell equivalence plus reconstructed XSD-valid XML
- KSeF track: remote non-production acceptance is stronger than local XSD, but
  it is a separate gate

## 7. Out of Scope for Now

- scanned PDFs
- OCR-first extraction
- photo input
- non-domestic invoices
- correction invoices
- advance invoices
