"""Tests for deterministic repair command validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agentic_repair.repair_kernel import (
    RepairCommand,
    RepairDecision,
    RepairKernelError,
    RepairPlanCommand,
    RepairSession,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)


def _summary() -> DomesticVatInvoiceSummary:
    return DomesticVatInvoiceSummary(
        line_computations=[],
        bucket_summaries={},
        invoice_net_total=Decimal("0.00"),
        invoice_vat_total=Decimal("0.00"),
        invoice_gross_total=Decimal("0.00"),
    )


def _candidate(value: object) -> Candidate:
    return Candidate(
        value=value,
        source="fuzzy",
        confidence=0.9,
        bbox=(0.0, 0.0, 10.0, 10.0),
        raw_text=str(value) if value is not None else None,
    )


def _evidence_with_candidates(*values: object) -> FieldEvidence:
    return FieldEvidence(
        value=values[0] if values else None,
        source="fuzzy",
        confidence=0.9,
        bbox=(0.0, 0.0, 10.0, 10.0),
        candidates=tuple(_candidate(value) for value in values),
    )


def _session(
    *,
    evidence: dict[str, FieldEvidence] | None = None,
    line_item_count: int = 1,
) -> RepairSession:
    shell = build_domestic_vat_shell()
    shell.line_items = [LineItemShell() for _ in range(line_item_count)]

    context = RepairContext(
        shell=shell,
        extracted_summary=_summary(),
        evidence=evidence or {},
        validation=ShellValidationResult(errors=[]),
        diagnostics=ExtractionDiagnostics(fields={}),
    )

    return RepairSession.from_context(context)


def _command(
    path: str,
    *,
    candidate_index: int = 0,
) -> RepairCommand:
    return RepairCommand(
        path=path,
        candidate_index=candidate_index,
        reason="candidate is better supported by context",
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("invoice_number", True),
        ("seller.nip", True),
        ("seller.bank_account", True),
        ("buyer.nip", True),
        ("buyer.bank_account", False),
        ("line_items[0].quantity", True),
        ("line_items[1].quantity", False),
        ("line_items[0].unknown", False),
        ("currency", False),
        ("summary.invoice_net_total", False),
    ],
)
def test_validate_path_support_recognizes_supported_shell_paths(
    path: str,
    expected: bool,
) -> None:
    assert _session().validate_path_support(path) is expected


def test_validate_command_returns_selected_candidate() -> None:
    session = _session(
        evidence={
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
        }
    )

    candidate = session.validate_command(
        _command("invoice_number", candidate_index=1)
    )

    assert candidate.value == "FV/001"


@pytest.mark.parametrize(
    ("command", "evidence", "reason"),
    [
        (_command("seller.nip"), {}, "missing_evidence"),
        (
            _command("summary.invoice_net_total"),
            {"summary.invoice_net_total": _evidence_with_candidates("10.00")},
            "unsupported_path",
        ),
        (
            _command("buyer.bank_account"),
            {"buyer.bank_account": _evidence_with_candidates("PL...")},
            "unsupported_path",
        ),
        (
            _command("seller.nip"),
            {
                "seller.nip": FieldEvidence(
                    value=None,
                    source="unresolved",
                    confidence=0.0,
                    bbox=None,
                    candidates=(),
                )
            },
            "no_candidates",
        ),
        (
            _command("seller.nip", candidate_index=-1),
            {"seller.nip": _evidence_with_candidates("1234567890")},
            "candidate_index_out_of_range",
        ),
        (
            _command("seller.nip", candidate_index=1),
            {"seller.nip": _evidence_with_candidates("1234567890")},
            "candidate_index_out_of_range",
        ),
        (
            _command("seller.nip"),
            {"seller.nip": _evidence_with_candidates(None)},
            "candidate_value_missing",
        ),
    ],
)
def test_validate_command_rejects_unsafe_commands(
    command: RepairCommand,
    evidence: dict[str, FieldEvidence],
    reason: str,
) -> None:
    session = _session(evidence=evidence)

    with pytest.raises(RepairKernelError) as error:
        session.validate_command(command)

    assert error.value.reason == reason
    assert error.value.path == command.path


def test_validate_plan_rejects_empty_plan() -> None:
    session = _session()

    with pytest.raises(ValueError, match="repair_plan_empty"):
        session.validate_plan(RepairPlanCommand(repair_commands=()))


def test_validate_plan_rejects_duplicate_paths() -> None:
    session = _session(
        evidence={
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
        }
    )

    with pytest.raises(RepairKernelError) as error:
        session.validate_plan(
            RepairPlanCommand(
                repair_commands=(
                    _command("invoice_number", candidate_index=0),
                    _command("invoice_number", candidate_index=1),
                )
            )
        )

    assert error.value.reason == "duplicate_path"
    assert error.value.path == "invoice_number"


def test_validate_plan_rejects_invalid_command() -> None:
    session = _session(evidence={})

    with pytest.raises(RepairKernelError) as error:
        session.validate_plan(
            RepairPlanCommand(repair_commands=(_command("seller.nip"),))
        )

    assert error.value.reason == "missing_evidence"
    assert error.value.path == "seller.nip"


def test_validate_plan_returns_selected_candidates_in_command_order() -> None:
    session = _session(
        evidence={
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
            "seller.nip": _evidence_with_candidates("1111111111", "8637940261"),
        }
    )

    candidates = session.validate_plan(
        RepairPlanCommand(
            repair_commands=(
                _command("seller.nip", candidate_index=1),
                _command("invoice_number", candidate_index=1),
            )
        )
    )

    assert isinstance(candidates, tuple)
    assert [candidate.value for candidate in candidates] == [
        "8637940261",
        "FV/001",
    ]


def test_apply_repair_plan_returns_repaired_shell_without_mutating_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(
        evidence={
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
            "seller.nip": _evidence_with_candidates("1111111111", "8637940261"),
        }
    )
    session.shell.invoice_number = "BAD"
    session.shell.seller.nip = "1111111111"
    validation = ShellValidationResult(errors=[])
    validated_shells = []

    def fake_validate(shell):
        validated_shells.append(shell)
        assert shell is not session.shell
        assert shell.invoice_number == "FV/001"
        assert shell.seller.nip == "8637940261"
        return validation

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        fake_validate,
    )

    result = session.apply_repair_plan(
        RepairPlanCommand(
            repair_commands=(
                _command("invoice_number", candidate_index=1),
                _command("seller.nip", candidate_index=1),
            )
        )
    )

    assert result.shell.invoice_number == "FV/001"
    assert result.shell.seller.nip == "8637940261"
    assert session.shell.invoice_number == "BAD"
    assert session.shell.seller.nip == "1111111111"
    assert result.decisions == (
        RepairDecision(
            path="invoice_number",
            old_value="BAD",
            new_value="FV/001",
            candidate_index=1,
            reason="candidate is better supported by context",
        ),
        RepairDecision(
            path="seller.nip",
            old_value="1111111111",
            new_value="8637940261",
            candidate_index=1,
            reason="candidate is better supported by context",
        ),
    )
    assert result.validation is validation
    assert validated_shells == [result.shell]


def test_apply_repair_plan_returns_failed_validation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(
        evidence={
            "line_items[0].quantity": _evidence_with_candidates(
                Decimal("1"), Decimal("-2")
            ),
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
        }
    )
    session.shell.line_items[0].quantity = Decimal("1")
    session.shell.invoice_number = "BAD"
    validation = ShellValidationResult(
        errors=[
            ShellValidationError(
                path="line_items[0].quantity",
                code="invalid_value",
                message="quantity must be positive",
            )
        ]
    )

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        lambda shell: validation,
    )

    result = session.apply_repair_plan(
        RepairPlanCommand(
            repair_commands=(
                _command("line_items[0].quantity", candidate_index=1),
                _command("invoice_number", candidate_index=1),
            )
        )
    )

    assert result.shell.line_items[0].quantity == Decimal("-2")
    assert result.shell.invoice_number == "FV/001"
    assert session.shell.line_items[0].quantity == Decimal("1")
    assert result.validation is validation
    assert result.validation.is_valid is False


def test_apply_repair_plan_rejects_empty_plan_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()

    def fail_if_called(shell):
        raise AssertionError("validation should not run for empty plans")

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        fail_if_called,
    )

    with pytest.raises(ValueError, match="repair_plan_empty"):
        session.apply_repair_plan(RepairPlanCommand(repair_commands=()))


def test_apply_repair_plan_rejects_unsafe_plan_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(
        evidence={
            "invoice_number": _evidence_with_candidates("BAD", "FV/001"),
        }
    )
    session.shell.invoice_number = "BAD"

    def fail_if_called(shell):
        raise AssertionError("validation should not run for unsafe plans")

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        fail_if_called,
    )

    with pytest.raises(RepairKernelError) as error:
        session.apply_repair_plan(
            RepairPlanCommand(
                repair_commands=(
                    _command("invoice_number", candidate_index=1),
                    _command("invoice_number", candidate_index=0),
                )
            )
        )

    assert error.value.reason == "duplicate_path"
    assert error.value.path == "invoice_number"
    assert session.shell.invoice_number == "BAD"
