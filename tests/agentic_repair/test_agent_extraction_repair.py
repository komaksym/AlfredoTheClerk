"""Tests for the combined agent decision tool context and schema."""

from __future__ import annotations

from src.agentic_repair.agent_extraction_repair import (
    AgentDecisionResult,
    AgentHumanReviewDecision,
    SYSTEM_PROMPT,
    build_repair_tools,
    format_agent_decision_result_for_tool,
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


def _candidate(index: int, value: str) -> AgentRepairCandidate:
    """Build one compact model-facing candidate for tool-contract tests."""

    return AgentRepairCandidate(
        index=index,
        value=value,
        confidence=0.9,
        raw_text=value,
        same_line_text=f"Label: {value}",
        rule=None,
        rejected_by=None,
    )


def _payload() -> AgentRepairPayload:
    """Build a two-field payload whose second candidate repairs each field."""

    return AgentRepairPayload(
        payload=(
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
                    _candidate(0, "PO/001"),
                    _candidate(1, "FV/001"),
                ),
            ),
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
                    _candidate(0, "1111111111"),
                    _candidate(1, "8637940261"),
                ),
            ),
        )
    )


def test_system_prompt_describes_combined_decision_tool_contract() -> None:
    """The model instructions should expose only the complete decision batch."""

    prompt = " ".join(SYSTEM_PROMPT.lower().split())

    assert "submit_repair_decisions" in prompt
    assert "exactly once" in prompt
    assert "one decision for every field" in prompt
    assert "action" in prompt
    assert "candidate_index" in prompt
    assert "reason" in prompt
    assert "human_review" in prompt
    assert "do not invent" in prompt
    assert "do not call apply_repair_plan directly" in prompt
    assert "promote_candidate" not in prompt


def test_combined_tool_description_describes_complete_json_shape() -> None:
    """The bound tool should document repair and review decisions together."""

    tools, _ = build_repair_tools(make_repair_session(), _payload())
    tool = tools[0]
    description = tool.description.lower()

    assert tool.name == "submit_repair_decisions"
    assert "exactly one" in description
    assert "every payload field" in description
    assert "repair" in description
    assert "human_review" in description
    assert "candidate index" in description


def test_combined_tool_schema_exposes_field_decision_list() -> None:
    """The JSON schema should require every property of one field decision."""

    tools, _ = build_repair_tools(make_repair_session(), _payload())
    schema = tools[0].args_schema.model_json_schema()

    decisions = schema["properties"]["decisions"]
    decision_schema = schema["$defs"]["AgentFieldDecisionInput"]

    assert schema["required"] == ["decisions"]
    assert decisions["type"] == "array"
    assert set(decision_schema["required"]) == {
        "path",
        "action",
        "reason",
    }
    assert set(decision_schema["properties"]) == {
        "path",
        "action",
        "candidate_index",
        "reason",
    }


def test_combined_tool_applies_multiple_repairs_in_one_call(
    monkeypatch,
) -> None:
    """A complete repair-only batch should delegate once to the repair kernel."""

    session = make_repair_session(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
            "seller.nip": make_evidence_with_candidates(
                "1111111111", "8637940261"
            ),
        }
    )
    session.shell.invoice_number = "BAD"
    session.shell.seller.nip = "1111111111"
    validation = ShellValidationResult(errors=[])

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        lambda shell: validation,
    )

    tools, get_latest_result = build_repair_tools(session, _payload())
    result = tools[0].invoke(
        {
            "decisions": [
                {
                    "path": "invoice_number",
                    "action": "repair",
                    "candidate_index": 1,
                    "reason": "candidate is next to invoice number label",
                },
                {
                    "path": "seller.nip",
                    "action": "repair",
                    "candidate_index": 1,
                    "reason": "candidate is next to seller NIP label",
                },
            ]
        }
    )

    assert result.repair_result is not None
    assert result.repair_result.shell.invoice_number == "FV/001"
    assert result.repair_result.shell.seller.nip == "8637940261"
    assert result.human_review_decisions == ()
    assert session.shell.invoice_number == "BAD"
    assert session.shell.seller.nip == "1111111111"
    assert [decision.path for decision in result.repair_result.decisions] == [
        "invoice_number",
        "seller.nip",
    ]
    assert get_latest_result() is result


def test_format_agent_decision_result_includes_both_outcome_types() -> None:
    """Tool feedback should serialize repairs, reviews, and validation together."""

    session = make_repair_session(
        evidence={
            "invoice_number": make_evidence_with_candidates("BAD", "FV/001"),
        }
    )
    session.shell.invoice_number = "BAD"
    tools, _ = build_repair_tools(
        session,
        AgentRepairPayload(payload=(_payload().payload[0],)),
    )
    result = tools[0].invoke(
        {
            "decisions": [
                {
                    "path": "invoice_number",
                    "action": "human_review",
                    "candidate_index": None,
                    "reason": "invoice reference remains ambiguous",
                }
            ]
        }
    )

    formatted = format_agent_decision_result_for_tool(
        AgentDecisionResult(
            repair_result=result.repair_result,
            human_review_decisions=(
                AgentHumanReviewDecision(
                    path="invoice_number",
                    reason="invoice reference remains ambiguous",
                ),
            ),
        )
    )

    assert '"repairs": []' in formatted
    assert '"human_review"' in formatted
    assert '"invoice_number"' in formatted
    assert '"validation": null' in formatted
