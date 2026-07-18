"""Tests for human-review case construction and submission."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from src.agentic_repair.human_review import (
    HumanReviewIssueCode,
    build_human_review_case,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import (
    BlockingField,
    RepairRoute,
    RepairRouteStatus,
)
from src.input_processing.extraction_diagnostics import (
    ExtractionDiagnostics,
    FieldDiagnostic,
    FieldStatus,
)
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
)
from tests.agentic_repair.factories import (
    make_repair_context,
    make_validation_error,
)


def _workflow_result() -> RepairWorkflowResult:
    error = make_validation_error("buyer.nip")
    context = make_repair_context(validation_errors=[error])
    route = RepairRoute(
        status=RepairRouteStatus.MANUAL_REVIEW_REQUIRED,
        repairable_fields=(),
        blocking_fields=(
            BlockingField(
                path="buyer.nip",
                reason="missing_evidence",
                diagnostic_status=FieldStatus.MISSING,
                validation_errors=(error,),
            ),
        ),
    )
    return RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=context.shell,
        route=route,
        context=context,
        reason="blocking_fields",
    )


def test_build_case_uses_attempted_shell_and_complete_field_metadata() -> None:
    original = build_domestic_vat_shell()
    original.seller.nip = "original"
    attempted = copy.deepcopy(original)
    attempted.seller.nip = "attempted"
    buyer_error = make_validation_error("buyer.nip")
    seller_error = make_validation_error("seller.nip")
    candidate = Candidate(
        value="8637940261",
        source="fuzzy",
        confidence=0.83,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="863-794-02-61",
        same_line_text="NIP 863-794-02-61",
        rule="nip_checksum",
        rejected_by=None,
    )
    context = make_repair_context(
        shell=original,
        evidence={
            "seller.nip": FieldEvidence(
                value="attempted",
                source="fuzzy",
                confidence=0.83,
                bbox=(1.0, 2.0, 3.0, 4.0),
                raw_text="863-794-02-61",
                candidates=(candidate,),
            )
        },
        validation_errors=[buyer_error],
        diagnostics=ExtractionDiagnostics(
            fields={
                "seller.nip": FieldDiagnostic(
                    path="seller.nip",
                    status=FieldStatus.AMBIGUOUS,
                    raw_text="863-794-02-61",
                    message="multiple candidates",
                )
            }
        ),
    )
    route = RepairRoute(
        status=RepairRouteStatus.MANUAL_REVIEW_REQUIRED,
        repairable_fields=(),
        blocking_fields=(
            BlockingField(
                path="buyer.nip",
                reason="missing_evidence",
                diagnostic_status=FieldStatus.MISSING,
                validation_errors=(buyer_error,),
            ),
        ),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.INVALID_SHELL,
        shell=attempted,
        validation=ShellValidationResult(errors=[seller_error]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original,
        route=route,
        context=context,
        reason=CorrectnessStatus.INVALID_SHELL.value,
        correctness=correctness,
    )

    result = build_human_review_case(workflow)

    assert result.issues == ()
    assert result.case is not None
    assert result.case.shell == attempted
    assert result.case.shell is not attempted
    assert result.case.context is context
    assert [field.path for field in result.case.fields] == [
        "buyer.nip",
        "seller.nip",
    ]
    seller = result.case.fields[1]
    assert seller.current_value == "attempted"
    assert seller.diagnostic_status is FieldStatus.AMBIGUOUS
    assert seller.validation_errors == (seller_error,)
    assert seller.raw_text == "863-794-02-61"
    assert seller.bbox == (1.0, 2.0, 3.0, 4.0)
    assert seller.candidates[0].index == 0
    assert seller.candidates[0].source == "fuzzy"
    assert seller.candidates[0].rule == "nip_checksum"
    assert result.case.fields[0].blocking_reason == "missing_evidence"
    assert result.case.fields[0].diagnostic_status is FieldStatus.MISSING


def test_build_case_rejects_non_reviewable_workflow_result() -> None:
    workflow = _workflow_result()
    workflow = replace(
        workflow,
        status=RepairWorkflowStatus.NO_REPAIR_NEEDED,
    )

    result = build_human_review_case(workflow)

    assert result.case is None
    assert [issue.code for issue in result.issues] == [
        HumanReviewIssueCode.RESULT_NOT_REVIEWABLE,
    ]


@pytest.mark.parametrize(
    "status",
    [
        CorrectnessStatus.TOTALS_MISMATCH,
        CorrectnessStatus.FA3_MAPPING_FAILED,
        CorrectnessStatus.XML_SERIALIZATION_FAILED,
        CorrectnessStatus.XSD_VALIDATION_FAILED,
    ],
)
def test_build_case_preserves_case_level_correctness_diagnostics(
    status: CorrectnessStatus,
) -> None:
    workflow = _workflow_result()
    correctness = CorrectnessResult(
        status=status,
        shell=workflow.shell,
        validation=ShellValidationResult(errors=[]),
        error="stage failed",
    )
    workflow = replace(workflow, correctness=correctness)

    result = build_human_review_case(workflow)

    assert result.case is not None
    assert result.case.correctness is correctness
    assert result.case.correctness.status is status
