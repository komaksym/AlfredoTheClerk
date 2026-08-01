# Active Implementation Plan

The current slice is the local agent-first human-review UI.

- Design: `docs/superpowers/specs/2026-07-31-human-review-ui-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-31-human-review-ui.md`
- Pull request: `https://github.com/komaksym/AlfredoTheClerk/pull/7`
- Branch: `feat/human-review-ui`
- Base: `main`

## Milestones

1. [x] Add the narrow FastAPI/Jinja/vanilla-JS runtime and package assets.
2. [x] Reuse canonical shell types for browser-to-review value parsing.
3. [x] Contain technical agent failures for human fallback.
4. [x] Add single-page PDF rendering and evidence-overlay geometry.
5. [x] Add one-invoice in-memory workflow/session and presentation adapters.
6. [x] Add upload, review, PDF-resource, READY result, and XML routes.
7. [x] Build the approved side-by-side review UI and agent-change audit view.
8. [x] Add integration regressions across ready, agent, mixed, human, and failure
   paths.
9. [x] Update README, current spec, and durable roadmap for the minimal-product
   pivot.
10. [x] Run final compile/package resource validation, inspect the UI workflow,
    complete the three-pass docstring audit, and independently review the PR diff.
11. [x] Fix every valid final-review finding, rerun all gates on the final head,
    and update PR validation evidence before requesting merge approval.

## Scope boundary

This slice ends at locally validated `READY_FOR_KSEF` FA(3) XML. It intentionally
does not add durable review persistence, multi-user infrastructure, multi-page or
OCR extraction, or automatic KSeF submission/status/UPO management.

Durable KSeF productization remains optional later work. Real legacy-invoice
evaluation continues in parallel when data is available.
