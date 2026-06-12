"""Tests for agent repair tool context and schema."""

from __future__ import annotations

from decimal import Decimal

from src.agentic_repair.agent_extraction_repair import (
    SYSTEM_PROMPT,
    build_repair_tools,
    format_repair_result_for_tool,
)
from src.agentic_repair.repair_kernel import (
    RepairDecision,
    RepairResult,
    RepairSession,
)
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
from src.input_processing.invoice_text_field_extraction import (
    Candidate,
    FieldEvidence,
)
from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
)
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult


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
        raw_text=str(value),
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
) -> RepairSession:
    context = RepairContext(
        shell=build_domestic_vat_shell(),
        extracted_summary=_summary(),
        evidence=evidence or {},
        validation=ShellValidationResult(errors=[]),
        diagnostics=ExtractionDiagnostics(fields={}),
    )
    return RepairSession.from_context(context)


def test_system_prompt_describes_batch_repair_tool_contract() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "apply_repair_plan" in prompt
    assert "once" in prompt
    assert "repair_commands" in prompt
    assert "path" in prompt
    assert "candidate_index" in prompt
    assert "reason" in prompt
    assert "do not invent" in prompt
    assert "promote_candidate" not in prompt
    assert "apply_repair_plan(path" not in prompt


def test_apply_repair_plan_tool_description_describes_json_shape() -> None:
    tools, _ = build_repair_tools(_session())
    tool = tools[0]
    description = tool.description.lower()

    assert tool.name == "apply_repair_plan"
    assert "once" in description
    assert "repair_commands" in description
    assert "path" in description
    assert "candidate_index" in description
    assert "reason" in description
    assert "do not invent" in description


def test_apply_repair_plan_tool_schema_exposes_command_list() -> None:
    tools, _ = build_repair_tools(_session())
    schema = tools[0].args_schema.model_json_schema()

    repair_commands = schema["properties"]["repair_commands"]
    command_schema = schema["$defs"]["RepairCommandInput"]

    assert schema["required"] == ["repair_commands"]
    assert repair_commands["type"] == "array"
    assert set(command_schema["required"]) == {
        "path",
        "candidate_index",
        "reason",
    }


def test_apply_repair_plan_tool_applies_multiple_repairs_in_one_call(
    monkeypatch,
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

    monkeypatch.setattr(
        "src.agentic_repair.repair_kernel.validate_pdf_extracted_shell",
        lambda shell: validation,
    )

    tools, get_latest_result = build_repair_tools(session)
    result = tools[0].invoke(
        {
            "repair_commands": [
                {
                    "path": "invoice_number",
                    "candidate_index": 1,
                    "reason": "candidate is next to invoice number label",
                },
                {
                    "path": "seller.nip",
                    "candidate_index": 1,
                    "reason": "candidate is next to seller NIP label",
                },
            ]
        }
    )

    assert result.shell.invoice_number == "FV/001"
    assert result.shell.seller.nip == "8637940261"
    assert session.shell.invoice_number == "BAD"
    assert session.shell.seller.nip == "1111111111"
    assert [decision.path for decision in result.decisions] == [
        "invoice_number",
        "seller.nip",
    ]
    assert get_latest_result() is result


def test_format_repair_result_for_tool_includes_all_batch_decisions() -> None:
    result = RepairResult(
        shell=build_domestic_vat_shell(),
        decisions=(
            RepairDecision(
                path="invoice_number",
                old_value="BAD",
                new_value="FV/001",
                candidate_index=1,
                reason="candidate is next to invoice number label",
            ),
            RepairDecision(
                path="seller.nip",
                old_value="1111111111",
                new_value="8637940261",
                candidate_index=1,
                reason="candidate is next to seller NIP label",
            ),
        ),
        validation=ShellValidationResult(errors=[]),
    )

    formatted = format_repair_result_for_tool(result)

    assert '"decisions"' in formatted
    assert '"invoice_number"' in formatted
    assert '"seller.nip"' in formatted
