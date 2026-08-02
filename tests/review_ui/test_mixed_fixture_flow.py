"""End-to-end regression for one mixed agent-and-human PDF fixture."""

from __future__ import annotations

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
FIXTURE = (
    REPO_ROOT
    / "data/synthetic_data/BROKEN_mixed_agent_and_human_nips.pdf"
)
SELLER_NIP = "8637940261"
BUYER_NIP = "5423511615"


class _AgentMustNotRun:
    """Reject model use when exact labelled evidence resolves the agent field."""

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> None:
        """Fail if the deterministic seller-NIP path reaches the model."""

        raise AssertionError(
            "unique exact NIP-labelled evidence must bypass the model"
        )


def test_mixed_fixture_routes_one_field_to_agent_and_one_to_human() -> None:
    """The persisted PDF should expose exactly one field to each repair path."""

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


def test_mixed_fixture_preserves_agent_change_until_human_finishes() -> None:
    """The seller repair should remain visible while a human supplies buyer NIP."""

    session = ReviewSession(model=_AgentMustNotRun())
    client = TestClient(create_app(session=session))

    upload = client.post(
        "/invoice",
        files={
            "invoice": (
                FIXTURE.name,
                FIXTURE.read_bytes(),
                "application/pdf",
            )
        },
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
    assert [
        (change.path, change.new_value)
        for change in presentation.agent_changes
    ] == [("seller.nip", SELLER_NIP)]
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
