# Mixed Agent-and-Human PDF Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one persisted PDF whose seller NIP is repaired automatically while its missing buyer NIP remains for a human, then prove the combined workflow reaches `READY_FOR_KSEF`.

**Architecture:** Keep production behavior unchanged. Add a native-text fixture derived from the existing seed-42 invoice, with the seller distractor line from the agent fixture and the blank buyer NIP from the human fixture. Exercise it through the real parser, route, repair orchestration, presenter, FastAPI upload, human submission, XML generation, and local XSD validation.

**Tech Stack:** Python 3.13, pytest, pdfplumber, FastAPI TestClient, WeasyPrint-generated native PDF, existing invoice repair and review modules.

## Global Constraints

- Persist the fixture as `data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf`.
- `seller.nip` must resolve to `8637940261` from the unique literal `NIP:` line.
- `buyer.nip` must have no usable candidate and require manual value `5423511615`.
- The review UI must expose one read-only seller agent change and one editable buyer field.
- No production extraction, routing, repair, correctness, or UI change unless the regression exposes a real contract violation.
- No OCR, scanned PDF, multi-page support, new dependency, or free-form agent invention.

---

### Task 1: Add the failing mixed-fixture regression

**Files:**
- Create: `tests/review_ui/test_mixed_fixture_flow.py`
- Expected fixture: `data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf`

**Interfaces:**
- Consumes: `run_full_extraction(ParsedDocument) -> RepairContext`, `route_repair_context(RepairContext) -> RepairRoute`, `ReviewSession.process_upload(filename, pdf_bytes)`, `build_review_presentation(case, workflow, page)`, and the existing `/invoice`, `/review`, `/result/invoice.xml` routes.
- Produces: regression coverage that locks the fixture's extraction shape and full agent-then-human behavior.

- [ ] **Step 1: Write the fixture-shape test**

```python
from pathlib import Path
from typing import Any

import pdfplumber
from fastapi.testclient import TestClient

from src.agentic_repair.repair_orchestration import RepairWorkflowStatus
from src.agentic_repair.repair_routing import RepairRouteStatus, route_repair_context
from src.input_processing.extraction_comparison import run_full_extraction
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from src.review_ui.app import create_app
from src.review_ui.presenter import build_review_presentation
from src.review_ui.session import ReviewSession


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf"
SELLER_NIP = "8637940261"
BUYER_NIP = "5423511615"


class _AgentMustNotRun:
    def bind_tools(self, tools: list[Any], **kwargs: Any) -> None:
        raise AssertionError("unique exact NIP-labelled evidence must bypass the model")


def test_mixed_fixture_routes_one_field_to_agent_and_one_to_human() -> None:
    with pdfplumber.open(FIXTURE) as pdf:
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text() or ""
        assert "Referencja kontrahenta: 5423511615" in text
        context = run_full_extraction(parse_data(pdf))

    route = route_repair_context(context)
    assert route.status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE
    assert [field.path for field in route.repairable_fields] == ["seller.nip"]
    assert [field.path for field in route.blocking_fields] == ["buyer.nip"]
    assert route.blocking_fields[0].reason == "no_candidates"
```

- [ ] **Step 2: Write the full upload/review/result test**

```python
def test_mixed_fixture_preserves_agent_change_until_human_finishes() -> None:
    session = ReviewSession(model=_AgentMustNotRun())
    client = TestClient(create_app(session=session))

    upload = client.post(
        "/invoice",
        files={"invoice": (FIXTURE.name, FIXTURE.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    assert upload.headers["location"] == "/review"
    assert session.workflow is not None
    assert session.workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert session.case is not None
    assert session.page is not None

    presentation = build_review_presentation(
        session.case,
        session.workflow,
        session.page,
    )
    assert [(change.path, change.new_value) for change in presentation.agent_changes] == [
        ("seller.nip", SELLER_NIP)
    ]
    assert [field.path for field in presentation.fields] == ["buyer.nip"]

    review = client.get("/review")
    assert "Agent changes" in review.text
    assert 'name="mode::buyer.nip"' in review.text
    assert 'name="mode::seller.nip"' not in review.text

    submit = client.post(
        "/review",
        data={
            "reviewer_id": "mixed-fixture-test",
            "mode::buyer.nip": "manual",
            "manual::buyer.nip": BUYER_NIP,
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303
    assert submit.headers["location"] == "/result"
    assert session.is_ready is True
    assert session.correctness is not None
    assert session.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert session.correctness.xsd_validation is not None
    assert session.correctness.xsd_validation.is_valid is True

    xml = client.get("/result/invoice.xml")
    assert xml.status_code == 200
    assert SELLER_NIP in xml.text
    assert BUYER_NIP in xml.text
```

- [ ] **Step 3: Run the new tests and verify they fail because the fixture is absent**

Run: `uv run pytest tests/review_ui/test_mixed_fixture_flow.py -q`

Expected: FAIL with `FileNotFoundError` for `BROKEN_mixed_agent_and_human_nips.pdf`.

- [ ] **Step 4: Commit the red test**

```bash
git add tests/review_ui/test_mixed_fixture_flow.py
git commit -m "test: define mixed agent and human fixture flow"
```

### Task 2: Create and verify the persisted PDF fixture

**Files:**
- Create: `data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf`

**Interfaces:**
- Consumes: the seed-42 shell and existing `seller_buyer_block_v1.html` visual structure.
- Produces: a one-page native-text PDF with seller `NIP: 8637940261`, blank buyer `NIP:`, and seller-side `Referencja kontrahenta: 5423511615`.

- [ ] **Step 1: Render the fixture in the sandbox**

Use the existing seed-42 shell, set `shell.buyer.nip = None`, substitute the standard v1 HTML tokens, and insert this paragraph immediately after the seller/buyer row:

```html
<p>Referencja kontrahenta: 5423511615</p>
```

Render with the repository's pinned template fonts and WeasyPrint. Do not modify the production template or renderer.

- [ ] **Step 2: Render the PDF to PNG and inspect it**

Run:

```bash
python /home/oai/skills/pdfs/scripts/render_pdf.py \
  data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf \
  --out_dir /tmp/mixed-fixture-render --dpi 200
```

Expected: one unclipped A4 page; the buyer `NIP:` row is blank; the seller NIP and reference line are readable; tables and totals remain intact.

- [ ] **Step 3: Run the focused regression**

Run: `uv run pytest tests/review_ui/test_mixed_fixture_flow.py -q`

Expected: `2 passed`.

- [ ] **Step 4: Commit the fixture**

```bash
git add data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf
git commit -m "test: add mixed agent and human PDF fixture"
```

### Task 3: Document and run repository-wide verification

**Files:**
- Modify: `README.md:62-72`

**Interfaces:**
- Consumes: the persisted fixture and passing workflow regression.
- Produces: discoverable local smoke instructions and final verification evidence.

- [ ] **Step 1: Add the README fixture entry**

Change `Two deliberately broken smoke fixtures` to `Three deliberately broken smoke fixtures` and add:

```markdown
- `BROKEN_mixed_agent_and_human_nips.pdf` automatically repairs seller NIP
  `8637940261`, then asks the reviewer to enter buyer NIP `5423511615`.
```

- [ ] **Step 2: Run narrow checks**

```bash
uv run ruff check tests/review_ui/test_mixed_fixture_flow.py README.md
uv run pytest tests/review_ui/test_mixed_fixture_flow.py -q
uv run pytest tests/review_ui/test_broken_fixture_routes.py tests/agentic_repair/test_ambiguous_fixture_agent_flow.py -q
```

Expected: all pass.

- [ ] **Step 3: Run full verification**

```bash
uv run ruff check .
uv run pytest -q
uv run pytest tests/ksef/test_docstrings.py -q
uv run python -m compileall src tests
rm -rf dist build alfredotheclerk.egg-info
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py dist/alfredotheclerk-*.whl
```

Expected: every command exits 0; the existing KSeF live test remains intentionally skipped.

- [ ] **Step 4: Run the real app flow in the sandbox**

Start `uv run python -m src.review_ui`, upload the mixed PDF, verify `/review` shows one seller agent change and only buyer NIP as unresolved, submit `5423511615`, and verify `/result` reports `READY_FOR_KSEF` with downloadable XML containing both NIPs.

- [ ] **Step 5: Commit documentation and verification-ready state**

```bash
git add README.md
git commit -m "docs: describe mixed repair fixture"
```
