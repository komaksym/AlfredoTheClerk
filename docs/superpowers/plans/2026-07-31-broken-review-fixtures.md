# Broken Review Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two intentionally broken single-page native-text invoice PDFs for manual UI testing, with regression tests proving one routes to agent repair and one routes directly to human review.

**Architecture:** Keep production code unchanged. Build both PDFs from the current v1 synthetic invoice layout/values, changing only seller/buyer NIP presentation, then assert their behavior through `parse_data()`, `run_full_extraction()`, and `route_repair_context()`.

**Tech Stack:** Python 3.13, WeasyPrint-generated PDF fixtures, pdfplumber, existing extraction/routing pipeline, pytest/Ruff.

## Global Constraints

- Keep both PDFs single-page and native-text.
- Do not change parser, extraction, routing, or agent behavior to make the fixtures pass.
- Agent fixture must have exactly one repairable field: `seller.nip`, with two usable candidates and no blockers.
- Human fixture must have exactly one blocking field: `buyer.nip`, with no usable candidates.
- Preserve all other invoice data and totals from the existing `FV2026_11_390_seller_buyer_block_v1.pdf` synthetic case.
- Every new Python test function has a docstring.

---

### Task 1: Specify routing behavior with failing tests

**Files:**
- Create: `tests/review_ui/test_broken_fixture_routes.py`

**Interfaces:**
- Consumes: `parse_data(pdf)`, `run_full_extraction(parsed_document)`, `route_repair_context(context)`.
- Produces: exact behavioral contract for both fixture PDFs.

- [x] **Step 1: Write failing tests** for exact route status, affected path, candidate values, and blocking reason.
- [x] **Step 2: Run CI before fixtures exist** and confirm failure is caused by the missing fixture files.

### Task 2: Add the two broken PDFs

**Files:**
- Create: `data/synthetic_data/BROKEN_agent_ambiguous_seller_nip.pdf`
- Create: `data/synthetic_data/BROKEN_human_missing_buyer_nip.pdf`

**Interfaces:**
- Consumes: current v1 synthetic invoice field values and table layout.
- Produces: user-uploadable PDFs exercising the two review paths.

- [ ] **Step 1: Render agent fixture** with seller NIP `8637940261` plus unrelated seller-block reference NIP `5423511615`.
- [ ] **Step 2: Render human fixture** with a blank buyer NIP value; intended correction remains `5423511615`.
- [ ] **Step 3: Verify both PDFs are one page, have extractable text, and retain two bordered invoice tables.**
- [ ] **Step 4: Run focused routing tests and fix the fixtures only if current production behavior does not meet the approved contract.**
- [ ] **Step 5: Run Ruff, full pytest, and compileall on the final branch head.**
