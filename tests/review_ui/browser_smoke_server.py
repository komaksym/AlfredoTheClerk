"""Serve a deterministic agent-failure-to-human-review browser smoke flow."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import uvicorn

from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import route_repair_context
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)
from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_PDF = (
    _REPO_ROOT
    / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
)


def _agent_failure_result() -> RepairWorkflowResult:
    """Build a valid invoice with one no-evidence field left for a human."""

    valid_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    broken_shell = copy.deepcopy(valid_shell)
    broken_shell.buyer.nip = None
    error = ShellValidationError(
        path="buyer.nip",
        code="required",
        message="buyer.nip is required",
    )
    context = RepairContext(
        shell=broken_shell,
        extracted_summary=summarize_domestic_vat_shell(valid_shell),
        evidence={},
        validation=ShellValidationResult(errors=[error]),
        diagnostics=ExtractionDiagnostics(fields={}),
    )
    return RepairWorkflowResult(
        status=RepairWorkflowStatus.AGENT_FAILED,
        shell=broken_shell,
        route=route_repair_context(context),
        context=context,
        reason="agent_exception",
    )


def main() -> None:
    """Start the loopback smoke server with one preprocessed invoice."""

    result = _agent_failure_result()

    def workflow_runner(
        parsed_document: object,
        model: Any,
        *,
        generated_at: object = None,
    ) -> RepairWorkflowResult:
        """Return the deterministic agent-failure result for browser CI."""

        del parsed_document, model, generated_at
        return result

    session = ReviewSession(model=object(), workflow_runner=workflow_runner)
    session.process_upload("browser-smoke.pdf", _SAMPLE_PDF.read_bytes())
    uvicorn.run(
        create_app(session=session),
        host="127.0.0.1",
        port=8001,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
