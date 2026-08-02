# Alfredo Review UI Redesign

## Status

Approved for implementation on 2026-08-01.

## Objective

Redesign Alfredo's existing human-review screen to reproduce the approved
1536×960 reference mockup as closely as possible while preserving Alfredo's real
invoice data, correction workflow, evidence overlays, and validation behavior.

The redesign is visual and interaction-preserving. It must not hard-code the
mockup's sample invoice, candidate values, counts, dates, or company names.

## Reference target

The target composition is the approved warm, minimal invoice-review interface
with:

- a fixed left navigation rail;
- a document header containing the real filename, metadata, and review status;
- a large rounded PDF viewer with a compact toolbar;
- a narrower review column containing agent changes, unresolved fields, and the
  primary confirmation action;
- a warm ivory background, subtle borders and shadows, orange review accents,
  green success accents, and a purple primary action;
- an Alfredo wordmark and custom mascot rendered from repository-owned inline
  SVG/CSS assets rather than an external image dependency.

The primary visual acceptance viewport is exactly 1536×960.

## Scope

### In scope

- Restructure `base.html` and `review.html` to match the approved visual
  hierarchy.
- Restyle the review screen through `review.css`.
- Make narrowly scoped JavaScript adjustments where required for the new
  navigation, disclosure, field selection, and viewer controls.
- Preserve all existing Jinja-driven dynamic values and form names.
- Preserve the current evidence-overlay behavior between the review field and
  source document.
- Preserve multiple unresolved-field support even though the reference shows
  one expanded field.
- Preserve agent-change details, manual correction, candidate selection,
  reviewer attribution, validation errors, source-total mismatch handling, and
  successful submission.
- Keep upload and result pages usable and visually compatible with the new app
  shell without turning this slice into a full multi-page redesign.
- Update browser-smoke evidence so the primary screenshot is captured at
  1536×960.
- Add or update focused tests for stable semantic hooks and critical content.

### Out of scope

- Changes to extraction, repair orchestration, shell-field typing, correctness,
  XML generation, or KSeF behavior.
- Hard-coded sample invoice content from the mockup.
- New persistence, queue management, invoice history, settings functionality,
  or multi-user features.
- Introducing React, a CSS framework, a component library, Playwright, Selenium,
  or another frontend runtime.
- Replacing the current server-rendered FastAPI/Jinja architecture.
- Claiming literal pixel identity where the invoice image or dynamic data must
  differ from the reference.

## Information architecture

### App shell

The desktop shell uses three columns conceptually:

1. **Navigation rail** — 220 px fixed-width visual rail.
2. **Document workspace** — flexible main column containing the header and PDF
   viewer.
3. **Review workspace** — approximately 500–540 px at the 1536 px reference
   width.

The document and review workspaces remain within the main content area. The rail
is visually separated by a subtle border and warm background.

### Navigation rail

The rail includes:

- Alfredo mascot plus wordmark;
- active `Review` item;
- inert but visually present `Invoices` and `Settings` items;
- bottom-aligned `Help` item.

Only links that already have valid destinations should navigate. Placeholder
items must not pretend to provide unavailable product features; they may be
rendered as non-link navigation labels.

### Document header

The header displays:

- the actual uploaded filename;
- an orange `Needs review` status pill;
- available metadata derived from existing session data;
- a compact overflow/menu affordance for visual parity without inventing new
  behavior.

No mockup-specific invoice number or received date may be fabricated.

### PDF viewer

The document card contains:

- a toolbar with page count, zoom controls, download, and fullscreen-style
  affordances;
- the existing rendered invoice image;
- active evidence overlay styling matched to the orange reference treatment;
- neutral canvas padding and a white page surface;
- independent scrolling where required.

Toolbar controls that are implemented must work. Purely decorative controls
must be clearly non-interactive and inaccessible to keyboard focus.

### Review workspace

The review column contains:

1. Agent changes summary card.
2. Unresolved-fields container with count.
3. One or more field cards.
4. Sticky primary action and auto-save/reviewer note.

The first unresolved field is expanded by default. Additional fields use compact
collapsed cards and can be expanded without losing their submitted values.

### Field card

Each field card preserves the actual field label, path, current value,
diagnostics, candidates, source evidence, form errors, and editability.

The visual hierarchy is:

- field label and status badge;
- concise explanation;
- candidate choices;
- optional manual entry;
- secondary metadata and reviewer attribution.

Candidate confidence may be displayed only when it is already available in the
presentation model. The UI must not invent calibrated labels such as `Best
match` unless they are derived from existing data through a deterministic
presentation rule.

### Primary action

The primary action is a full-width purple button labelled `Confirm & continue`
for visual parity. It submits the same existing review form and preserves current
validation behavior.

## Visual system

### Palette

Use CSS custom properties for the approved palette:

- warm ivory app background;
- white cards;
- dark navy text;
- muted slate secondary text;
- pale lavender active navigation;
- orange unresolved/status accents;
- pale green success accents;
- purple gradient or solid primary action.

Exact values are implementation details and should be tuned through screenshot
comparison.

### Typography

Use the existing system-font approach with no externally downloaded font files.
Tune font size, weight, line height, and tracking to approximate the reference.
The wordmark may use a serif fallback stack while the application UI remains
sans-serif.

### Geometry

At 1536×960, target:

- 220 px navigation rail;
- 24–30 px outer content gutters;
- 20–24 px card radii;
- approximately 16–24 px internal spacing;
- a document/review split close to the reference;
- restrained shadows and one-pixel borders;
- no page-level vertical overflow in the primary smoke state unless the real
  field count requires it.

## Responsive behavior

The 1536×960 desktop state is the visual target.

Below approximately 1100 px:

- collapse the rail into a compact top or icon-only treatment;
- stack the document and review workspaces;
- keep the action accessible;
- preserve source/field linking.

Below approximately 700 px:

- use a single-column layout;
- simplify nonessential toolbar labels;
- allow document and field sections to scroll naturally;
- preserve all form controls and validation messages.

## Data and behavior preservation

The redesign must preserve:

- every existing form field name (`reviewer_id`, `mode::*`, `candidate::*`, and
  `manual::*`);
- existing session state and server-side form-error restoration;
- candidate and manual correction modes;
- evidence overlay activation and reciprocal scrolling;
- immutable source-total mismatch presentation;
- agent-change visibility;
- current route destinations and PDF/XML downloads;
- no-data and no-editable-field states.

No backend interface should be changed merely to simplify CSS or markup. A small
presentation-model addition is allowed only when it removes template logic and
is covered by a focused test.

## Accessibility

- Retain semantic headings, form labels, fieldsets, legends, and status roles.
- Maintain visible keyboard focus states.
- Do not make decorative navigation or toolbar items keyboard-focusable.
- Ensure text and controls meet practical contrast requirements.
- Preserve meaningful alt text for the rendered invoice page.
- Keep disclosure controls operable with native keyboard behavior.
- Do not encode status using color alone.

## Verification strategy

### Automated gates

Run the repository's complete existing gates:

```bash
uv run ruff check .
uv run pytest -q
uv run python -m compileall src tests
uv build --wheel
```

The browser-smoke workflow must continue to:

- start the real review application with the ambiguous-NIP fixture;
- reach the human-review state;
- render the review screen in headless Google Chrome;
- submit the real correction flow;
- render the successful result;
- upload non-empty screenshots.

### Visual verification

Capture the review screen at exactly 1536×960 and compare it side by side with
the approved reference. Iterate on:

- shell and column widths;
- vertical alignment;
- card dimensions;
- typography;
- spacing;
- radii;
- shadows and borders;
- colors;
- mascot and wordmark proportions;
- toolbar and action placement.

Handoff requires a fresh final screenshot from the implemented branch. Any
remaining visible differences must be attributable to Alfredo's actual invoice,
field count, candidate data, or other required dynamic content—not avoidable
layout or styling drift.

## Test expectations

Focused template/route tests should verify stable semantics rather than brittle
full-HTML snapshots. Appropriate checks include:

- the new app-shell landmarks and navigation labels are present;
- actual filenames and dynamic field values still render;
- form input names remain unchanged;
- the primary action label is present;
- agent changes and unresolved counts still render conditionally;
- the browser smoke continues through the same correction workflow.

## Delivery

Implementation will be delivered in a new pull request from
`feat/review-ui-redesign` into `main`.

Commits must use concise conventional subjects and detailed bodies explaining:

- what changed;
- why the change was made;
- behavior and architecture preserved;
- verification performed;
- limitations or remaining dynamic differences.

The PR description must include the final 1536×960 browser artifact and an AI
assistance disclosure.
