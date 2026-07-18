"""Tests for human-review case construction and submission."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from src.agentic_repair.human_review import (
    CandidateSelectionCommand,
    HumanReviewCase,
    HumanReviewCommand,
    HumanReviewInputKind,
    HumanReviewIssueCode,
    HumanReviewStatus,
    ManualCorrectionCommand,
    build_human_review_case,
    submit_human_review,
)
from src.agentic_repair.repair_orchestration import (
    RepairWorkflowResult,
    RepairWorkflowStatus,
)
from src.agentic_repair.repair_routing import (
    BlockingField,
    RepairableField,
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
from src.invoice_gen.domain_shell import (
    DomesticVatInvoiceShell,
    LineItemShell,
    build_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
)
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import (
    CorrectnessResult,
    CorrectnessStatus,
)
from tests.agentic_repair.factories import (
    make_candidate,
    make_evidence_with_candidates,
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


def _post_agent_manual_review_case() -> HumanReviewCase:
    """Model agent-available routing followed by failed full correctness."""

    shell = build_domestic_vat_shell()
    shell.invoice_number = "BAD"
    shell.seller.name = "Old Seller"
    error = make_validation_error("invoice_number")
    evidence = make_evidence_with_candidates("BAD", "FV/001")
    context = make_repair_context(
        shell=shell,
        evidence={"invoice_number": evidence},
        validation_errors=[error],
    )
    route = RepairRoute(
        status=RepairRouteStatus.AGENT_REPAIR_AVAILABLE,
        repairable_fields=(
            RepairableField(
                path="invoice_number",
                current_value="BAD",
                diagnostic_status=FieldStatus.AMBIGUOUS,
                validation_errors=(error,),
                candidate_count=2,
            ),
        ),
        blocking_fields=(),
    )
    correctness = CorrectnessResult(
        status=CorrectnessStatus.INVALID_SHELL,
        shell=shell,
        validation=ShellValidationResult(errors=[error]),
    )
    workflow = RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=shell,
        route=route,
        context=context,
        reason=CorrectnessStatus.INVALID_SHELL.value,
        correctness=correctness,
    )
    built = build_human_review_case(workflow)
    assert built.case is not None
    return built.case


def _attempted_shell_workflow() -> RepairWorkflowResult:
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
    return RepairWorkflowResult(
        status=RepairWorkflowStatus.MANUAL_REVIEW_REQUIRED,
        shell=original,
        route=route,
        context=context,
        reason=CorrectnessStatus.INVALID_SHELL.value,
        correctness=correctness,
    )


def test_build_case_copies_latest_attempted_shell() -> None:
    workflow = _attempted_shell_workflow()
    assert workflow.correctness is not None

    result = build_human_review_case(workflow)

    assert result.issues == ()
    assert result.case is not None
    assert result.case.shell.seller.nip == "attempted"
    assert result.case.shell is not workflow.correctness.shell
    assert result.case.shell.seller is not workflow.correctness.shell.seller


def test_build_case_combines_route_and_correctness_paths() -> None:
    result = build_human_review_case(_attempted_shell_workflow())

    assert result.case is not None
    assert [field.path for field in result.case.fields] == [
        "buyer.nip",
        "seller.nip",
    ]
    buyer = result.case.fields[0]
    seller = result.case.fields[1]
    assert buyer.validation_errors == ()
    assert seller.validation_errors == (make_validation_error("seller.nip"),)


def test_build_case_projects_evidence_and_candidate_metadata() -> None:
    result = build_human_review_case(_attempted_shell_workflow())

    assert result.case is not None
    seller = result.case.fields[1]
    assert seller.current_value == "attempted"
    assert seller.diagnostic_status is FieldStatus.AMBIGUOUS
    assert seller.raw_text == "863-794-02-61"
    assert seller.bbox == (1.0, 2.0, 3.0, 4.0)
    assert seller.candidates[0].index == 0
    assert seller.candidates[0].source == "fuzzy"
    assert seller.candidates[0].rule == "nip_checksum"


def test_build_case_preserves_blocking_metadata() -> None:
    result = build_human_review_case(_attempted_shell_workflow())

    assert result.case is not None
    buyer = result.case.fields[0]
    assert buyer.blocking_reason == "missing_evidence"
    assert buyer.diagnostic_status is FieldStatus.MISSING


def test_build_case_snapshots_mutable_extraction_context() -> None:
    workflow = _workflow_result()
    source = workflow.context
    source.evidence["buyer.nip"] = make_evidence_with_candidates("8637940261")
    source.diagnostics.fields["buyer.nip"] = FieldDiagnostic(
        path="buyer.nip",
        status=FieldStatus.AMBIGUOUS,
        raw_text="863-794-02-61",
        message="multiple candidates",
    )
    result = build_human_review_case(workflow)
    assert result.case is not None

    source.evidence["buyer.nip"].candidates = (
        make_candidate("changed-after-case-build"),
    )
    source.extracted_summary.bucket_summaries[Decimal("23")] = (
        DomesticVatBucketSummary(
            vat_rate=Decimal("23"),
            net_total=Decimal("100.00"),
            vat_total=Decimal("23.00"),
            gross_total=Decimal("123.00"),
        )
    )
    source.diagnostics.fields["buyer.nip"] = FieldDiagnostic(
        path="buyer.nip",
        status=FieldStatus.MISSING,
        raw_text=None,
        message="changed after case build",
    )
    source.validation.errors.append(make_validation_error("invoice_number"))

    snapshot = result.case.context
    candidates = snapshot.evidence["buyer.nip"].candidates
    assert snapshot is not source
    assert snapshot.evidence is not source.evidence
    assert snapshot.extracted_summary is not source.extracted_summary
    assert snapshot.diagnostics is not source.diagnostics
    assert candidates is not None
    assert [candidate.value for candidate in candidates] == ["8637940261"]
    assert snapshot.extracted_summary.bucket_summaries == {}
    assert snapshot.diagnostics.fields["buyer.nip"].status is (
        FieldStatus.AMBIGUOUS
    )
    assert snapshot.validation.errors == [make_validation_error("buyer.nip")]


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


def test_submit_applies_candidate_and_manual_commands_with_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _post_agent_manual_review_case()
    correctness_calls: list[DomesticVatInvoiceShell] = []

    def fake_correctness(
        shell: DomesticVatInvoiceShell,
        extracted_summary: DomesticVatInvoiceSummary,
        generated_at: datetime | None = None,
    ) -> CorrectnessResult:
        correctness_calls.append(shell)
        return CorrectnessResult(
            status=CorrectnessStatus.READY_FOR_KSEF,
            shell=shell,
            validation=ShellValidationResult(errors=[]),
        )

    monkeypatch.setattr(
        "src.agentic_repair.human_review.check_invoice_correctness",
        fake_correctness,
    )
    commands = (
        CandidateSelectionCommand(
            path="invoice_number",
            candidate_index=1,
            reason="visible invoice identifier",
        ),
        ManualCorrectionCommand(
            path="seller.name",
            value="Correct Seller",
            reason="reviewed against the party block",
        ),
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=commands,
    )

    assert outcome.status is HumanReviewStatus.READY_FOR_KSEF
    assert outcome.case.shell.invoice_number == "FV/001"
    assert outcome.case.shell.seller.name == "Correct Seller"
    assert case.shell.invoice_number != "FV/001"
    assert case.shell.seller.name == "Old Seller"
    assert correctness_calls == [outcome.case.shell]
    attempt = outcome.case.attempts[-1]
    assert attempt.issues == ()
    assert attempt.correctness_status is CorrectnessStatus.READY_FOR_KSEF
    assert [decision.input_kind for decision in attempt.decisions] == [
        HumanReviewInputKind.CANDIDATE_SELECTION,
        HumanReviewInputKind.MANUAL_CORRECTION,
    ]
    assert [decision.reviewer_id for decision in attempt.decisions] == [
        "reviewer-17",
        "reviewer-17",
    ]
    assert attempt.decisions[0].candidate_index == 1
    assert attempt.decisions[1].candidate_index is None


def test_invalid_batch_applies_nothing_and_skips_correctness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _post_agent_manual_review_case()

    def fail_correctness(*args: object, **kwargs: object) -> None:
        raise AssertionError("correctness must not run for an invalid batch")

    monkeypatch.setattr(
        "src.agentic_repair.human_review.check_invoice_correctness",
        fail_correctness,
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=(
            ManualCorrectionCommand(
                path="invoice_number",
                value="FV/001",
                reason="reviewed identifier",
            ),
            ManualCorrectionCommand(
                path="summary.invoice_gross_total",
                value=Decimal("999.00"),
                reason="must remain evidence",
            ),
        ),
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert outcome.case.shell == case.shell
    assert outcome.case.shell.invoice_number == case.shell.invoice_number
    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert attempt.correctness_status is None
    assert [issue.code for issue in attempt.issues] == [
        HumanReviewIssueCode.IMMUTABLE_PATH,
    ]


@pytest.mark.parametrize(
    ("command", "evidence"),
    [
        (
            ManualCorrectionCommand(
                path="invoice_number",
                value=1,
                reason="wrong runtime type",
            ),
            None,
        ),
        (
            ManualCorrectionCommand(
                path="issue_date",
                value="2026-07-18",
                reason="wrong runtime type",
            ),
            None,
        ),
        (
            ManualCorrectionCommand(
                path="payment_form",
                value=True,
                reason="bool must not pass as int",
            ),
            None,
        ),
        (
            ManualCorrectionCommand(
                path="line_items[0].quantity",
                value="2",
                reason="wrong runtime type",
            ),
            None,
        ),
        (
            CandidateSelectionCommand(
                path="invoice_number",
                candidate_index=0,
                reason="candidate has wrong runtime type",
            ),
            {"invoice_number": make_evidence_with_candidates(1)},
        ),
    ],
)
def test_incompatible_value_type_rejects_the_batch_atomically(
    monkeypatch: pytest.MonkeyPatch,
    command: HumanReviewCommand,
    evidence: dict[str, FieldEvidence] | None,
) -> None:
    case = _post_agent_manual_review_case()
    shell = copy.deepcopy(case.shell)
    shell.line_items = [LineItemShell(quantity=Decimal("1"))]
    context = (
        replace(case.context, evidence=evidence)
        if evidence is not None
        else case.context
    )
    case = replace(case, shell=shell, context=context)
    original = copy.deepcopy(case.shell)

    def fail_correctness(*args: object, **kwargs: object) -> None:
        raise AssertionError("correctness must not run for an invalid batch")

    monkeypatch.setattr(
        "src.agentic_repair.human_review.check_invoice_correctness",
        fail_correctness,
    )

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=(
            ManualCorrectionCommand(
                path="seller.name",
                value="Would Be Applied First",
                reason="valid command in the rejected batch",
            ),
            command,
        ),
    )

    attempt = outcome.case.attempts[-1]
    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert outcome.case.shell == original
    assert attempt.decisions == ()
    assert attempt.correctness_status is None
    assert [issue.code for issue in attempt.issues] == [
        HumanReviewIssueCode.INVALID_VALUE_TYPE,
    ]


@pytest.mark.parametrize(
    ("reviewer_id", "commands", "code"),
    [
        (
            "",
            (
                ManualCorrectionCommand(
                    path="invoice_number",
                    value="FV/001",
                    reason="reviewed identifier",
                ),
            ),
            HumanReviewIssueCode.REVIEWER_ID_REQUIRED,
        ),
        ("reviewer-17", (), HumanReviewIssueCode.COMMANDS_REQUIRED),
        (
            "reviewer-17",
            (
                ManualCorrectionCommand(
                    path="invoice_number",
                    value="FV/001",
                    reason="",
                ),
            ),
            HumanReviewIssueCode.REASON_REQUIRED,
        ),
    ],
)
def test_submission_metadata_failures_are_structured(
    reviewer_id: str,
    commands: tuple[HumanReviewCommand, ...],
    code: HumanReviewIssueCode,
) -> None:
    outcome = submit_human_review(
        _post_agent_manual_review_case(),
        reviewer_id=reviewer_id,
        commands=commands,
    )

    assert outcome.status is HumanReviewStatus.MANUAL_REVIEW_REQUIRED
    assert [issue.code for issue in outcome.case.attempts[-1].issues] == [code]


def test_duplicate_paths_are_rejected_once() -> None:
    command = ManualCorrectionCommand(
        path="invoice_number",
        value="FV/001",
        reason="reviewed identifier",
    )

    outcome = submit_human_review(
        _post_agent_manual_review_case(),
        reviewer_id="reviewer-17",
        commands=(command, command),
    )

    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert [(issue.path, issue.code) for issue in attempt.issues] == [
        ("invoice_number", HumanReviewIssueCode.DUPLICATE_PATH),
    ]


@pytest.mark.parametrize(
    ("command", "evidence", "code"),
    [
        (
            ManualCorrectionCommand(
                path="currency",
                value="EUR",
                reason="unsafe field",
            ),
            {},
            HumanReviewIssueCode.UNSUPPORTED_PATH,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {},
            HumanReviewIssueCode.MISSING_EVIDENCE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {
                "seller.nip": FieldEvidence(
                    value=None,
                    source="unresolved",
                    confidence=0.0,
                    bbox=None,
                    candidates=(),
                )
            },
            HumanReviewIssueCode.CANDIDATES_REQUIRED,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=-1,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates("8637940261")},
            HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=1,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates("8637940261")},
            HumanReviewIssueCode.CANDIDATE_INDEX_OUT_OF_RANGE,
        ),
        (
            CandidateSelectionCommand(
                path="seller.nip",
                candidate_index=0,
                reason="selected source value",
            ),
            {"seller.nip": make_evidence_with_candidates(None)},
            HumanReviewIssueCode.CANDIDATE_VALUE_MISSING,
        ),
    ],
)
def test_unsafe_commands_are_structured(
    command: HumanReviewCommand,
    evidence: dict[str, FieldEvidence],
    code: HumanReviewIssueCode,
) -> None:
    case = _post_agent_manual_review_case()
    context = replace(case.context, evidence=evidence)
    case = replace(case, context=context)

    outcome = submit_human_review(
        case,
        reviewer_id="reviewer-17",
        commands=(command,),
    )

    attempt = outcome.case.attempts[-1]
    assert attempt.decisions == ()
    assert [issue.code for issue in attempt.issues] == [code]
