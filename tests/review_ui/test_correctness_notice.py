"""Tests for surfacing non-field local correctness failures in review UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession
from tests.agentic_repair.factories import make_repair_context


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = (
    REPO_ROOT
    / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
)


def test_review_page_surfaces_non_field_correctness_failure() -> None:
    """Mapping/XSD-style failures should be visible instead of looking unresolved silently."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    context = make_repair_context(
        shell=shell,
        extracted_summary=summarize_domestic_vat_shell(shell),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.FA3_MAPPING_FAILED,
        shell=shell,
        validation=ShellValidationResult(errors=[]),
        error="mapping failed",
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=shell,
        route=route_repair_context(context),
        context=context,
        reason=CorrectnessStatus.FA3_MAPPING_FAILED.value,
        correctness=correctness,
    )

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the prepared non-field correctness failure."""

        return workflow

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    client = TestClient(create_app(session=session))
    response = client.post(
        "/invoice",
        files={"invoice": ("invoice.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    assert "Local correctness is still blocked at fa3 mapping failed." in response.text
