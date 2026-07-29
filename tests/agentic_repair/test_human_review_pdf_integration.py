"""Persisted-PDF integration coverage for human review."""

from __future__ import annotations

import copy

import pdfplumber

from src.agentic_repair.human_review import (
    HumanReviewStatus,
    ManualCorrectionCommand,
    build_human_review_case,
    submit_human_review,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowStatus,
    run_shell_repair,
)
from src.input_processing.parse_pdf import parse_data
from src.invoice_gen.hard_case_corpus import load_hard_case_fixture
from src.invoice_gen.invoice_correctness import CorrectnessStatus
from src.invoice_gen.pdf_rendering import SELLER_BUYER_TEMPLATE_ID
from src.invoice_gen.template_registry import get_template


class _AgentMustNotRun:
    def bind_tools(self, tools: object) -> None:
        raise AssertionError(
            "blocking extraction must route directly to review"
        )


def test_persisted_pdf_resumes_through_human_review_to_valid_xml() -> None:
    fixture = load_hard_case_fixture("long_parties_v1")
    template = get_template(SELLER_BUYER_TEMPLATE_ID)
    original_anchors = copy.deepcopy(template.label_anchors)
    anchors = copy.deepcopy(template.label_anchors)
    anchors["invoice_number"] = []

    with pdfplumber.open(fixture.pdf_paths[SELLER_BUYER_TEMPLATE_ID]) as pdf:
        parsed = parse_data(pdf)

    workflow = run_shell_repair(
        parsed,
        model=_AgentMustNotRun(),
        anchors=anchors,
        generated_at=fixture.case.generated_at,
    )

    assert workflow.status is RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED
    assert [field.path for field in workflow.route.blocking_fields] == [
        "invoice_number"
    ]
    built = build_human_review_case(workflow)
    assert built.case is not None

    outcome = submit_human_review(
        built.case,
        reviewer_id="reviewer-pdf-integration",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value=fixture.case.shell.invoice_number,
                reason="confirmed against persisted benchmark truth",
            ),
        ),
        generated_at=fixture.case.generated_at,
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.correctness is not None
    assert outcome.correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert outcome.correctness.xml == fixture.case.target_xml
    assert outcome.correctness.xsd_validation is not None
    assert outcome.correctness.xsd_validation.is_valid is True
    assert template.label_anchors == original_anchors
