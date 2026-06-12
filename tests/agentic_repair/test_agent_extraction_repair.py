"""Tests for agent repair tool context and schema."""

from __future__ import annotations

from decimal import Decimal

from src.agentic_repair.agent_extraction_repair import (
    SYSTEM_PROMPT,
    build_repair_tools,
)
from src.agentic_repair.repair_kernel import RepairSession
from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.extraction_diagnostics import ExtractionDiagnostics
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


def _session() -> RepairSession:
    context = RepairContext(
        shell=build_domestic_vat_shell(),
        extracted_summary=_summary(),
        evidence={},
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
