# Alfredo Review UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the approved 1536×960 Alfredo invoice-review mockup as closely as possible while keeping Alfredo’s real invoice data and existing review workflow intact.

**Architecture:** Keep the existing FastAPI/Jinja/vanilla-JavaScript architecture. Restructure only the shared app shell and review template, define the visual system in the existing stylesheet, preserve all server-side form names and evidence hooks, and use the existing GitHub Actions browser smoke as the executable visual fixture. GitHub Actions is the runtime and screenshot source because the local container cannot resolve github.com.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, vanilla JavaScript, CSS, pytest, headless Google Chrome, GitHub Actions.

## Global Constraints

- Primary visual acceptance viewport: exactly `1536×960`.
- Preserve real uploaded filename, invoice image, unresolved fields, candidates, values, errors, counts, and agent changes.
- Preserve `reviewer_id`, `mode::*`, `candidate::*`, and `manual::*` form names.
- Preserve evidence-overlay linking and existing correction behavior.
- Do not add React, a CSS framework, Playwright, Selenium, or external fonts.
- Do not change extraction, repair, correctness, XML, or KSeF behavior.
- Use repository-owned inline SVG/CSS for the Alfredo mascot and all icons.
- Commits require concise conventional subjects and detailed explanatory bodies.
- Handoff requires fresh CI, a downloaded 1536×960 browser artifact, and direct comparison with the approved reference.

---

## File Structure

- `src/review_ui/templates/base.html` — shared application shell, sidebar, wordmark, navigation, and page-content slot.
- `src/review_ui/templates/review.html` — dynamic review header, PDF viewer, agent-change card, unresolved-field cards, correction form, and action footer.
- `src/review_ui/static/review.css` — design tokens, desktop geometry, typography, cards, viewer, forms, responsive collapse, and non-review-page compatibility.
- `src/review_ui/static/review.js` — existing field/evidence activation plus working viewer zoom and field-card disclosure behavior.
- `tests/review_ui/test_app_routes.py` — stable semantic assertions for shell landmarks, dynamic values, preserved input names, and primary action copy.
- `.github/workflows/ci.yml` — 1536×960 browser capture and retained screenshot artifact.
- `docs/superpowers/specs/2026-08-01-review-ui-redesign-design.md` — approved visual and behavioral specification.
- `docs/superpowers/plans/2026-08-01-review-ui-redesign.md` — this executable implementation plan.

---

### Task 1: Add semantic acceptance tests for the redesigned shell

**Files:**
- Modify: `tests/review_ui/test_app_routes.py`

**Interfaces:**
- Consumes: current `GET /review` rendered HTML and `_valid_manual_review_result` fixture.
- Produces: stable required hooks and copy that later template changes must satisfy.

- [ ] **Step 1: Update the blocking-review route test before production markup**

Replace the old presentation-specific assertions with assertions for:

```python
assert 'class="app-sidebar"' in review.text
assert 'aria-label="Primary navigation"' in review.text
assert "Alfredo" in review.text
assert "Review" in review.text
assert "Invoices" in review.text
assert "Settings" in review.text
assert "Help" in review.text
assert 'class="document-header"' in review.text
assert "Needs review" in review.text
assert "invoice.pdf" in review.text
assert 'class="pdf-toolbar"' in review.text
assert 'class="agent-changes"' in review.text
assert "Unresolved fields" in review.text
assert "Invoice number" in review.text
assert "Confirm &amp; continue" in review.text
assert 'name="reviewer_id"' in review.text
assert 'name="mode::invoice_number"' in review.text
assert 'name="manual::invoice_number"' in review.text
```

Keep the existing PDF and PNG resource assertions.

- [ ] **Step 2: Push the test-only commit and verify RED in GitHub Actions**

Expected result: the route test fails because the current templates do not expose the new sidebar, document header, toolbar, or primary action label.

- [ ] **Step 3: Record the failing job and failure reason before production changes**

The failure must be an assertion failure for a missing redesigned semantic hook, not a syntax, import, fixture, or infrastructure error.

---

### Task 2: Implement the shared Alfredo application shell

**Files:**
- Modify: `src/review_ui/templates/base.html`
- Modify: `src/review_ui/static/review.css`

**Interfaces:**
- Consumes: Jinja block `{% block content %}` and static asset URL generation.
- Produces: `.app-frame`, `.app-sidebar`, `.brand-lockup`, `.primary-nav`, `.app-main`, and `.page-shell` landmarks used by every page.

- [ ] **Step 1: Replace the simple top header with the approved sidebar shell**

Use semantic markup with:

```html
<div class="app-frame">
  <aside class="app-sidebar">
    <a class="brand-lockup" href="/" aria-label="Alfredo home">...</a>
    <nav class="primary-nav" aria-label="Primary navigation">...</nav>
    <div class="sidebar-footer">...</div>
  </aside>
  <main class="app-main">
    <div class="page-shell">{% block content %}{% endblock %}</div>
  </main>
</div>
```

Render the mascot and navigation icons as inline SVG using `currentColor`. Render `Invoices` and `Settings` as non-link labels because their product routes do not exist. Keep `Review` linked to `/review` and `Help` non-interactive.

- [ ] **Step 2: Add the shell design tokens and desktop geometry**

Define CSS variables for:

```css
--app-bg: #fbfaf8;
--surface: #ffffff;
--text: #131b34;
--muted: #74788a;
--border: #e8e7e4;
--lavender: #f1edff;
--purple: #5531c5;
--orange: #f59e3d;
--orange-soft: #fff5ec;
--green-soft: #ecfbf2;
--sidebar-width: 220px;
--review-width: 540px;
```

Set the 1536×960 desktop shell to a 220 px sidebar and a flexible main area without page-level overflow in the single-field smoke state.

- [ ] **Step 3: Preserve upload and result-page usability**

Keep `.upload-card`, `.result-card`, button, alert, and result utility styles compatible with the new shell. Do not redesign their workflows.

- [ ] **Step 4: Commit the shell slice with a detailed body**

The body must explain the new shell, inline SVG ownership, inert navigation policy, preserved page blocks, and responsive fallback.

---

### Task 3: Rebuild the review workspace to match the approved mockup

**Files:**
- Modify: `src/review_ui/templates/review.html`
- Modify: `src/review_ui/static/review.css`

**Interfaces:**
- Consumes: `session`, `presentation`, `correctness_notice`, and `has_editable_fields` template data.
- Produces: `.document-header`, `.review-workspace`, `.document-card`, `.pdf-toolbar`, `.review-column`, `.agent-changes`, `.unresolved-card`, `.field-card`, and `.review-actions` markup while retaining all existing form names and `data-*` hooks.

- [ ] **Step 1: Implement the document header**

Render the real filename and a `Needs review` pill. Do not fabricate received dates or invoice numbers. Use the available warning/correctness text only in accessible compact notices below the header when present.

- [ ] **Step 2: Implement the PDF viewer card and toolbar**

Use:

```html
<section class="document-card" aria-label="Original invoice">
  <div class="pdf-toolbar">...</div>
  <div class="pdf-scroll">
    <div class="pdf-stage" data-pdf-stage>...</div>
  </div>
</section>
```

Include page `1 / 1`, minus and plus zoom buttons with `data-zoom-out` and `data-zoom-in`, a `100%` readout with `data-zoom-value`, a direct original-PDF download link, and a decorative fullscreen-shaped icon that is not focusable unless working behavior is supplied.

Keep every existing `data-evidence-path` overlay and style the active overlay orange.

- [ ] **Step 3: Implement the right review column**

Render agent changes as a compact native `<details>` card. Render `Unresolved fields` with the real count. Keep source-total mismatches and global errors visible but visually subordinate.

- [ ] **Step 4: Implement field cards without changing transport contracts**

For each field:

- preserve `data-field-path` and focusability;
- render real label, diagnostic state, current value, errors, blocking reason, raw source text, and no-evidence state;
- keep `mode::*`, `candidate::*`, and `manual::*` names exactly unchanged;
- present candidate rows inside the orange unresolved card;
- keep manual entry available;
- keep read-only evidence cases explicitly read-only.

The first card is visually expanded; subsequent cards remain naturally compact only through native markup and CSS, without hiding required controls from form submission.

- [ ] **Step 5: Implement the sticky primary action**

Use the exact label:

```html
<button class="button button-primary" type="submit">
  Confirm &amp; continue
</button>
```

Keep reviewer attribution required, but move it into a compact footer row near the auto-save/security note rather than making it the visual focus.

- [ ] **Step 6: Complete 1536×960 styling**

Tune:

- 24 px main gutters;
- 18–22 px radii;
- 16–24 px internal spacing;
- approximately 63/37 document/review split inside the main area;
- subtle warm shadows;
- orange unresolved outlines;
- pale green agent-change summary;
- full-width purple gradient action;
- independent document and review scrolling.

- [ ] **Step 7: Commit the review workspace with a detailed body**

Explain the visual hierarchy, preserved data contracts, working controls, dynamic-data differences, and responsive behavior.

---

### Task 4: Add only the interactions required by the accepted UI

**Files:**
- Modify: `src/review_ui/static/review.js`

**Interfaces:**
- Consumes: existing `data-field-path`, `data-evidence-path`, mode/candidate/manual controls, plus new `data-pdf-stage`, `data-zoom-in`, `data-zoom-out`, and `data-zoom-value` hooks.
- Produces: reciprocal evidence activation, form-mode enablement, and bounded PDF zoom.

- [ ] **Step 1: Preserve existing field/evidence and correction-mode behavior**

Do not change server transport values or disable a selected value unexpectedly.

- [ ] **Step 2: Implement bounded viewer zoom**

Maintain an in-memory scale starting at `1`. On zoom-in/out, clamp between `0.75` and `1.5` in `0.1` steps, set `transform: scale(...)` with `transform-origin: top center`, and update the readout to the nearest integer percent.

- [ ] **Step 3: Respect reduced motion and keyboard behavior**

The zoom buttons remain native buttons. Existing field and overlay controls remain keyboard focusable. Do not add custom keyboard traps.

- [ ] **Step 4: Commit the interaction slice with a detailed body**

Explain that the change adds only local viewer controls and preserves form/evidence behavior.

---

### Task 5: Update browser-smoke capture to the accepted viewport

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: existing real ambiguous-NIP browser smoke server and `/review` and `/result` routes.
- Produces: `human-fallback.png` and `ready-for-ksef.png` at `1536×960` in the `human-review-browser-smoke` artifact.

- [ ] **Step 1: Change both Chrome commands**

Use:

```bash
--window-size=1536,960
```

Do not replace direct Chrome with Playwright or Selenium.

- [ ] **Step 2: Keep artifact validation intact**

Retain both `test -s` assertions and `if-no-files-found: error`.

- [ ] **Step 3: Commit the viewport change with a detailed body**

Explain that it aligns automated visual evidence with the approved reference dimensions without changing the smoke workflow.

---

### Task 6: Verify GREEN and iterate visually

**Files:**
- Modify as required by observed visual drift: `base.html`, `review.html`, `review.css`, `review.js`.

**Interfaces:**
- Consumes: GitHub Actions run and downloaded `human-review-browser-smoke` artifact.
- Produces: final implementation screenshot and a fidelity ledger.

- [ ] **Step 1: Verify the focused route test and full CI are green**

Required successful steps:

- Ruff;
- full pytest suite;
- single docstring audit;
- browser smoke;
- artifact upload;
- compileall;
- wheel build;
- installed-resource smoke.

- [ ] **Step 2: Download and inspect the review screenshot**

Open both:

- approved reference: `/mnt/data/4c28d562-a7a3-449c-a23d-c44bc5f7ff4a.png`;
- implementation: downloaded `human-fallback.png`.

- [ ] **Step 3: Compare at least these fidelity points**

1. Sidebar width, logo scale, and navigation vertical rhythm.
2. Header filename position, status pill, and top whitespace.
3. PDF card geometry, toolbar density, page scale, and canvas padding.
4. Right-column width, agent-card height, unresolved-card hierarchy, and footer action position.
5. Typography scale, orange/green/purple palette, borders, shadows, and radii.
6. Dynamic-content wrapping and no accidental clipping at 1536×960.

- [ ] **Step 4: Iterate with small visual-fix commits**

Each fix commit must describe the concrete mismatch observed, the CSS/markup adjustment, and the verification evidence it targets.

- [ ] **Step 5: Run a final fresh CI after the last visual edit**

Do not rely on a prior run.

---

### Task 7: Open and document the pull request

**Files:**
- No additional production files unless final verification identifies a defect.

**Interfaces:**
- Consumes: final branch head, green workflow, and final screenshot artifact.
- Produces: reviewable PR from `feat/review-ui-redesign` into `main`.

- [ ] **Step 1: Open the PR with a detailed description**

Include:

- visual redesign summary;
- preserved backend and form contracts;
- exact 1536×960 verification method;
- full CI result;
- browser artifact name and ID;
- fidelity ledger and intentional dynamic differences;
- AI assistance disclosure.

- [ ] **Step 2: Verify PR metadata and changed-file scope**

The PR must target `main`, remain unmerged, and contain only the spec, plan, templates, CSS, JavaScript, focused tests, and CI viewport changes required by this redesign.

- [ ] **Step 3: Hand off without claiming impossible literal identity**

State that the product chrome was directly verified against the accepted design and list only differences caused by Alfredo’s real invoice data or required dynamic state.
