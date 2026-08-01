# Human-review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal local FastAPI/Jinja application that accepts one supported single-page invoice PDF, runs the existing extraction and evidence-constrained agent repair first, falls back to the existing human-review workflow for residual problems, and finishes at `READY_FOR_KSEF` with downloadable FA(3) XML.

**Architecture:** Keep the existing extraction, repair, human-review, and correctness modules authoritative. Add a thin `src/review_ui` application layer for in-memory state, transport/value parsing, PDF-page presentation, and server-rendered HTML. The browser never mutates the canonical shell directly; it submits one attributed human-review command batch to the existing backend. Agent failures are adapted into review cases without weakening the candidate-only agent boundary.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, Jinja2, vanilla JavaScript/CSS, pdfplumber, existing LangChain/DeepSeek repair workflow, pytest/Ruff.

## Global Constraints

- [ ] Keep the canonical `DomesticVatInvoiceShell` as business truth.
- [ ] Reuse `run_shell_repair()`, `build_human_review_case()`, `submit_human_review()`, and `check_invoice_correctness()` rather than creating a second repair/correctness path.
- [ ] Agent values remain candidate-only; only humans may submit manual canonical values.
- [ ] `summary.*` remains immutable evidence.
- [ ] Support one native-text, single-page PDF and one active local review session only.
- [ ] Bind the runnable app to `127.0.0.1`; add no authentication, database, queue, React/Node stack, OCR, multi-page extraction, or KSeF submission UI.
- [ ] Every new Python module starts with a module docstring and every new function/test function has a docstring.
- [ ] Work on a feature branch and do not merge without user approval.

---

## Task 1: Wire the local-web runtime and package assets

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/review_ui/__init__.py`
- Create: `src/review_ui/__main__.py`
- Create: `src/review_ui/templates/.gitkeep` only if needed before real templates land
- Create: `src/review_ui/static/.gitkeep` only if needed before real assets land

- [ ] Add failing packaging/import checks that expect FastAPI, Jinja, multipart upload support, Uvicorn, runtime `pdfplumber`, and installed template/static package data.
- [ ] Add the narrow runtime dependencies: `fastapi`, `jinja2`, `python-multipart`, `uvicorn`, and promote `pdfplumber>=0.11.9` from dev-only to runtime.
- [ ] Configure setuptools package data for `src.review_ui` templates/static assets.
- [ ] Add a minimal module entrypoint that will later call the app factory on `127.0.0.1`; do not put workflow logic in `__main__.py`.
- [ ] Run the narrow packaging/import checks and commit the dependency/package boundary.

## Task 2: Add typed form-to-shell conversion without duplicating shell semantics

**Files:**
- Modify: `src/agentic_repair/shell_fields.py`
- Create: `src/review_ui/form_values.py`
- Modify/Create tests: `tests/agentic_repair/test_shell_fields.py`
- Create: `tests/review_ui/test_form_values.py`

- [ ] Write failing tests for exposing the target canonical value type for supported shell paths, including indexed line-item paths.
- [ ] Add the smallest public shell-field type lookup needed by the UI, reusing the existing canonical path/type maps.
- [ ] Write failing UI parsing tests for `str`, `date`, `Decimal`, `int`, optional/empty values, malformed values, and unsupported/summary paths.
- [ ] Implement a pure form parser that converts browser strings into the runtime type expected by `submit_human_review()` and returns structured parse errors instead of mutating review state.
- [ ] Run the focused shell-field/form parser tests and commit.

## Task 3: Build the in-memory UI workflow/session adapter

**Files:**
- Create: `src/review_ui/session.py`
- Create: `src/review_ui/presenter.py`
- Create: `tests/review_ui/test_session.py`
- Create: `tests/review_ui/test_presenter.py`

- [ ] Write failing tests for the four workflow outcomes: already ready, fully agent-repaired, manual-review required, and structured `AGENT_FAILED` fallback.
- [ ] Write a failing test for an exception raised while constructing/calling the model and require human fallback rather than a broken request.
- [ ] Implement one-process `ReviewSession` state holding the uploaded PDF bytes/name, workflow result, optional human-review case, optional agent warning, reviewer identity, and final correctness/XML result.
- [ ] Keep model construction lazy: extraction/routing must be allowed to determine that no agent call is needed before requiring a model. Inject the model/model factory in tests.
- [ ] Adapt structured or exceptional agent failure into a human-review case based on the unchanged extraction context/route, preserving evidence/candidates and exposing a warning.
- [ ] Compute the read-only agent-change diff by comparing original extracted values with accepted candidate-shell values and matching the chosen value back to evidence candidates where possible.
- [ ] Build presentation objects for field labels, validation/blocking messages, immutable summary issues, candidate metadata, and agent-change rows. Do not put HTML concerns into repair-domain modules.
- [ ] Run focused session/presenter tests and commit.

## Task 4: Render the single PDF page and evidence overlays

**Files:**
- Create: `src/review_ui/pdf_view.py`
- Create: `tests/review_ui/test_pdf_view.py`

- [ ] Write failing tests that reject non-PDF/invalid PDF input, multi-page PDFs, and pages with no native text.
- [ ] Write a failing test that renders a supported single-page PDF and returns page image bytes plus source page dimensions.
- [ ] Implement single-page validation and server-side page rendering using the existing pdfplumber layer.
- [ ] Convert source `(x0, top, x1, bottom)` evidence coordinates into percentage-based overlay geometry relative to the source page dimensions; do not introduce a second coordinate convention.
- [ ] Represent missing bbox as an explicit no-evidence state rather than a fabricated box.
- [ ] Run focused PDF-view tests and commit.

## Task 5: Add FastAPI routes for upload, review, original PDF, page image, and XML

**Files:**
- Create: `src/review_ui/app.py`
- Create: `tests/review_ui/test_app_routes.py`

- [ ] Write failing route tests for `GET /`, supported PDF upload, multi-page/invalid upload errors, original-PDF/page-image access, success XML download, and review-page routing.
- [ ] Create an app factory with injectable `ReviewSession`/model dependencies for deterministic tests.
- [ ] Implement `GET /` upload page and `POST /invoice` processing. Expected business failures render understandable HTTP/UI states, not tracebacks.
- [ ] Implement `GET /review/original.pdf` and `GET /review/page.png` from current in-memory state only.
- [ ] Implement `GET /result/invoice.xml` only when the active correctness result is `READY_FOR_KSEF` with generated XML.
- [ ] Implement `POST /review`: read reviewer ID and field modes/values, build candidate/manual commands with generated reasons, reject parse errors without calling correctness, call existing atomic `submit_human_review()`, and retain failed attempts/state for retry.
- [ ] Do not submit anything to KSeF from these routes.
- [ ] Run focused route tests and commit.

## Task 6: Build the server-rendered review and result UI

**Files:**
- Create: `src/review_ui/templates/base.html`
- Create: `src/review_ui/templates/upload.html`
- Create: `src/review_ui/templates/review.html`
- Create: `src/review_ui/templates/result.html`
- Create: `src/review_ui/static/review.css`
- Create: `src/review_ui/static/review.js`
- Modify: `tests/review_ui/test_app_routes.py`

- [ ] Add failing rendered-HTML assertions for the approved side-by-side layout, agent-warning banner, read-only agent diff, unresolved field cards, immutable summary issue, candidate/manual controls, reviewer field, and `Review & Validate` action.
- [ ] Implement the Jinja templates with the PDF/evidence pane on the left and agent changes + unresolved fields on the right.
- [ ] Render evidence boxes as percentage-positioned HTML overlays keyed to field paths.
- [ ] Add small vanilla JS only for field-card/overlay selection, scroll/highlight behavior, and candidate-vs-manual input enabling.
- [ ] Preserve entered reviewer/manual values and surface field errors after failed review attempts.
- [ ] On ready paths, render success details and agent changes when present plus a `Download FA(3) XML` action; skip the human form.
- [ ] Add a small `Open original PDF` action from the review page.
- [ ] Run focused route/render tests and commit.

## Task 7: Prove the complete workflow with integration regressions

**Files:**
- Create: `tests/review_ui/test_workflow_integration.py`
- Reuse existing deterministic synthetic PDF fixtures under `data/` and existing repair test helpers where appropriate.

- [ ] Add a no-repair-needed test that ends at `READY_FOR_KSEF` and downloadable XML.
- [ ] Add a fully agent-repaired test that skips human editing and shows the agent diff.
- [ ] Add a mixed repair test where candidate-backed fields are agent-handled first and only residual blocking fields are presented to the human.
- [ ] Add a blocking-only test proving the model is not called when no legal candidate exists.
- [ ] Add agent technical-failure fallback coverage.
- [ ] Add invalid human correction coverage proving the same case remains reviewable and no partial canonical mutation is accepted.
- [ ] Add successful human correction coverage proving the existing correctness gate reaches `READY_FOR_KSEF` and XML/XSD success.
- [ ] Add missing-bbox coverage and unsupported multi-page coverage.
- [ ] Run the full review-UI test package and relevant existing repair/correctness tests; commit.

## Task 8: Update product/task documentation and local run instructions

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `ROADMAP.md`
- Modify: `PLANS.md`

- [ ] Document the local launch command, required agent environment keys, supported PDF scope, and `READY_FOR_KSEF`/XML end state in README.
- [ ] Update `SPEC.md` to record the KSeF TEST proof as completed, make this local human-review UI the active/completed slice as appropriate, and move durable KSeF recovery/UPO work to optional later work.
- [ ] Update `ROADMAP.md` because the user explicitly changed durable product sequencing: minimal product success ends at reviewable validated FA(3), while durable remote KSeF tracking/UPO becomes a later optional extension. Preserve the existing KSeF TEST proof as a demonstrated capability.
- [ ] Update `PLANS.md` to point to this design, plan, branch, milestones, and implementation status.
- [ ] Keep durable strategy in ROADMAP and current execution/status in SPEC/PLANS.
- [ ] Run documentation-sensitive tests/checks if any and commit.

## Task 9: Repository gates, browser smoke test, PR, and review loop

**Files:**
- All files changed by Tasks 1-8
- PR description

- [ ] Run `uv run ruff check src tests`.
- [ ] Run `uv run pytest`.
- [ ] Run `uv run python -m compileall src tests`.
- [ ] Build the wheel and verify installed package templates/static/XSD resources are usable.
- [ ] Launch the app locally on `127.0.0.1` and manually smoke-test `PDF → agent attempt → human fallback → Review & Validate → READY_FOR_KSEF`, plus a no-repair success path.
- [ ] Inspect every changed Python module/function/test for the required docstrings three times before handoff.
- [ ] Inspect the final diff for scope creep, duplicated correctness logic, unsupported agent value invention, secret exposure, and accidental KSeF submission.
- [ ] Open a non-draft PR with a concise system-level DAG and validation evidence; state that the PR text/review was prepared with AI assistance.
- [ ] Re-review the PR from the final diff. Fix every valid overengineering/correctness finding and rerun the narrowest relevant checks, then the repository gates, until the review is clean.

## Plan self-review

- [x] No `TBD`, `TODO`, or unresolved design choices remain.
- [x] The plan covers all approved acceptance cases: no repair, agent repair, mixed repair, blocking-only review, agent failure, invalid/successful human review, evidence/no-evidence, single-page restriction, XML output, and no KSeF side effect.
- [x] Browser strings are converted to canonical shell runtime types before entering the existing human-review boundary.
- [x] PDF overlay geometry reuses existing bbox coordinates and single-page scope.
- [x] UI/application state is isolated from repair-domain logic and remains in memory only.
- [x] Documentation updates reflect the explicit durable-product pivot rather than silently contradicting ROADMAP/SPEC.
