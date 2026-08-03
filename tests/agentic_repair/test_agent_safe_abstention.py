"""Behavioral tests for explicit per-field agent abstention."""

from __future__ import annotations

import pytest

from src.agentic_repair.agent_extraction_repair import (
    SYSTEM_PROMPT,
    build_repair_tools,
)
from src.agentic_repair.repair_payload import (
    AgentRepairCandidate,
    AgentRepairField,
    AgentRepairPayload,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationError,
    ShellValidationResult,
)
from tests.agentic_repair.factories import (
    make_evidence_with_candidates,
    make_repair_session,
)


def _candidate(index: int, value: str, line: str) -> AgentRepairCandidate:
    return AgentRepairCandidate(
        index=index,
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=line,
        rule=None,
        rejected_by=None,
    )


def _payload() -> AgentRepairPayload:
    return AgentRepairPayload(
        payload=(
            AgentRepairField(
                path="seller.nip",
                current_value="1111111111",
                diagnostic_status=None,
                validation_errors=(
                    ShellValidationError(
                        path="seller.nip",
                        code="invalid_nip",
                        message="seller NIP requires repair",
                    ),
                ),
                candidates=(
                    _candidate(0, "1111111111", "Odbiorca: 1111111111"),
                    _candidate(1, "8637940261", "Wystawca: 8637940261"),
                ),
            ),
            AgentRepairField(
                path="invoice_number",
                current_value="BAD",
                diagnostic_status=None,
                validation_errors=(
                    ShellValidationError(
                        path="invoice_number",
                        code="invalid_invoice_number",
                        message="invoice number requires repair",
                    ),
                ),
                candidates=(
                    _candidate(0, "FV/001", "Numer dokumentu: FV/001"),
                    _candidate(1, "FV/002", "Numer dokumentu: FV/002"),
                ),
            ),
        )
    )


def _session():
    session = make_repair_session(
        evidence={
            "seller.nip": make_evidence_with_candidates(
                "1111111111", "8637940261"
            ),
            "invoice_number": make_evidence_with_candidates(
                "BAD", "FV/002"
            ),
        }
    )
    session.shell.seller.nip = "1111111111"
    session.shell.invoice_number = "BAD"
    return session


def test_combined_tool_repairs_clear_field_and_escalates_ambiguous_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        lambda shell: ShellValidationResult(errors=[]),
    )

    tools, get_latest_result = build_repair_tools(session, _payload())

    assert [bound_tool.name for bound_tool in tools] == [
        "submit_repair_decisions"
    ]
    result = tools[0].invoke(
        {
            "decisions": [
                {
                    "path": "seller.nip",
                    "action": "repair",
                    "candidate_index": 1,
                    "reason": "The evidence identifies the invoice issuer.",
                },
                {
                    "path": "invoice_number",
                    "action": "human_review",
                    "candidate_index": None,
                    "reason": "Both invoice-number candidates are plausible.",
                },
            ]
        }
    )

    assert result.repair_result is not None
    assert result.repair_result.shell.seller.nip == "8637940261"
    assert result.repair_result.shell.invoice_number == "BAD"
    assert session.shell.seller.nip == "1111111111"
    assert [decision.path for decision in result.repair_result.decisions] == [
        "seller.nip"
    ]
    assert [
        (decision.path, decision.reason)
        for decision in result.human_review_decisions
    ] == [
        ("invoice_number", "Both invoice-number candidates are plausible.")
    ]
    assert get_latest_result() is result


def test_combined_tool_allows_every_field_to_require_human_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()

    def fail_if_repair_runs(*args: object, **kwargs: object) -> None:
        raise AssertionError("all-escalated decisions must not call repair kernel")

    monkeypatch.setattr(
        type(session),
        "apply_repair_plan",
        fail_if_repair_runs,
    )
    tools, _ = build_repair_tools(session, _payload())

    result = tools[0].invoke(
        {
            "decisions": [
                {
                    "path": "seller.nip",
                    "action": "human_review",
                    "candidate_index": None,
                    "reason": "Seller role is not uniquely supported.",
                },
                {
                    "path": "invoice_number",
                    "action": "human_review",
                    "candidate_index": None,
                    "reason": "Invoice reference is not uniquely supported.",
                },
            ]
        }
    )

    assert result.repair_result is None
    assert [decision.path for decision in result.human_review_decisions] == [
        "seller.nip",
        "invoice_number",
    ]


def test_combined_tool_rejects_incomplete_batch_before_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()

    def fail_if_repair_runs(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid batches must be atomic")

    monkeypatch.setattr(
        type(session),
        "apply_repair_plan",
        fail_if_repair_runs,
    )
    tools, _ = build_repair_tools(session, _payload())

    with pytest.raises(ValueError, match="exactly cover payload"):
        tools[0].invoke(
            {
                "decisions": [
                    {
                        "path": "seller.nip",
                        "action": "repair",
                        "candidate_index": 1,
                        "reason": "Issuer evidence is clear.",
                    }
                ]
            }
        )


def test_system_prompt_requires_explicit_per_field_decisions() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "one decision for every field" in prompt
    assert "uniquely supported" in prompt
    assert "does not mean that only one candidate exists" in prompt
    assert "human_review" in prompt
    assert "confidence cannot break a semantic tie" in prompt
    assert "do not omit fields" in prompt
    assert "contains only fields" not in prompt
