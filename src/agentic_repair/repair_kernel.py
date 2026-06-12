"""Deterministic candidate-promotion primitives for agentic repair.

The kernel is the safety boundary around LLM output: an agent may request a
candidate promotion, but this module validates the command, copies the shell,
applies the selected evidence-backed value, and reruns scoped validation.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.invoice_text_field_extraction import Candidate
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
    validate_pdf_extracted_shell,
)

TOP_LEVEL_REPAIRABLE: set[str] = {
    "invoice_number",
    "issue_date",
    "sale_date",
    "issue_city",
    "payment_form",
    "payment_due_date",
}

SELLER_REPAIRABLE: set[str] = {
    "nip",
    "name",
    "address_line_1",
    "address_line_2",
    "bank_account",
}

BUYER_REPAIRABLE: set[str] = {
    "nip",
    "name",
    "address_line_1",
    "address_line_2",
}

LINE_ITEM_REPAIRABLE: set[str] = {
    "description",
    "unit",
    "quantity",
    "unit_price_net",
    "discount",
    "vat_rate",
}

_LINE_ITEM_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"^line_items\[(\d+)\]\.([a-z_]+)$"
)


class RepairKernelError(ValueError):
    """Raised when an agent repair command fails deterministic safety checks."""

    def __init__(self, *, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


@dataclass(frozen=True)
class RepairDecision:
    """Audit record for one accepted candidate-promotion command."""

    path: str
    old_value: object
    new_value: object
    candidate_index: int
    reason: str


@dataclass(frozen=True)
class RepairCommand:
    """Agent-selected request to promote one existing evidence candidate."""

    path: str
    candidate_index: int
    reason: str


@dataclass(frozen=True)
class RepairPlanCommand:
    """Agent-selected batch of candidate promotions to apply together."""

    repair_commands: tuple[RepairCommand, ...]


@dataclass(frozen=True)
class RepairResult:
    """Shell copy produced by repair plus its decision log and validation."""

    shell: DomesticVatInvoiceShell
    decisions: tuple[RepairDecision, ...]
    validation: ShellValidationResult


@dataclass(frozen=True)
class RepairSession:
    """Immutable repair session state built from one extraction context."""

    context: RepairContext
    shell: DomesticVatInvoiceShell
    decisions: tuple[RepairDecision, ...]
    validation: ShellValidationResult

    @classmethod
    def from_context(cls, context: RepairContext) -> "RepairSession":
        """Start repair from a deep copy of the original extracted shell."""

        return cls(
            context=context,
            shell=copy.deepcopy(context.shell),
            decisions=(),
            validation=context.validation,
        )

    def get_shell_value(
        self,
        shell: DomesticVatInvoiceShell,
        path: str,
    ) -> object:
        """Read a supported repair path from ``shell``."""

        if path in TOP_LEVEL_REPAIRABLE:
            return getattr(shell, path)

        if path.startswith("seller."):
            field = path.removeprefix("seller.")
            return getattr(shell.seller, field)

        if path.startswith("buyer."):
            field = path.removeprefix("buyer.")
            return getattr(shell.buyer, field)

        if match := _LINE_ITEM_PATH_PATTERN.match(path):
            index = int(match.group(1))
            field = match.group(2)
            return getattr(shell.line_items[index], field)

        raise RepairKernelError(path=path, reason="unsupported_path")

    def set_shell_value(
        self,
        shell: DomesticVatInvoiceShell,
        path: str,
        new_value: object,
    ) -> None:
        """Write ``new_value`` into a supported repair path on ``shell``."""

        if path in TOP_LEVEL_REPAIRABLE:
            setattr(shell, path, new_value)
            return

        if path.startswith("seller."):
            field = path.removeprefix("seller.")
            setattr(shell.seller, field, new_value)
            return

        if path.startswith("buyer."):
            field = path.removeprefix("buyer.")
            setattr(shell.buyer, field, new_value)
            return

        if match := _LINE_ITEM_PATH_PATTERN.match(path):
            index = int(match.group(1))
            field = match.group(2)
            setattr(shell.line_items[index], field, new_value)
            return

        raise RepairKernelError(path=path, reason="unsupported_path")

    def validate_path_support(self, path: str) -> bool:
        """Return whether ``path`` names a shell field repair can mutate."""

        if path in TOP_LEVEL_REPAIRABLE:
            return True

        if "." not in path:
            return False

        prefix, suffix = path.split(".", maxsplit=1)
        if prefix == "seller" and suffix in SELLER_REPAIRABLE:
            return True

        if prefix == "buyer" and suffix in BUYER_REPAIRABLE:
            return True

        match = _LINE_ITEM_PATH_PATTERN.match(path)
        if match is not None:
            index = int(match.group(1))
            field = match.group(2)

            if (
                0 <= index < len(self.shell.line_items)
                and field in LINE_ITEM_REPAIRABLE
            ):
                return True

        return False

    def validate_command(self, command: RepairCommand) -> Candidate:
        """Validate an agent command and return its selected candidate."""

        path = command.path

        if path not in self.context.evidence:
            raise RepairKernelError(path=path, reason="missing_evidence")

        if path.startswith("summary.") or not self.validate_path_support(path):
            raise RepairKernelError(path=path, reason="unsupported_path")

        candidates = self.context.evidence[path].candidates
        if not candidates:
            raise RepairKernelError(path=path, reason="no_candidates")

        if not 0 <= command.candidate_index < len(candidates):
            raise RepairKernelError(
                path=path,
                reason="candidate_index_out_of_range",
            )

        selected_candidate = candidates[command.candidate_index]
        if selected_candidate.value is None:
            raise RepairKernelError(path=path, reason="candidate_value_missing")

        return selected_candidate

    def validate_plan(
        self,
        plan: RepairPlanCommand,
    ) -> tuple[Candidate, ...]:
        """Validate a batch plan and return selected candidates in plan order.

        Plan validation rejects malformed batches before mutation. Individual
        command safety still flows through ``validate_command`` so path support,
        evidence, candidate bounds, and candidate values keep one contract.
        """

        if not plan.repair_commands:
            raise ValueError("repair_plan_empty")

        seen_paths: set[str] = set()
        selected_candidates: list[Candidate] = []

        for command in plan.repair_commands:
            if command.path in seen_paths:
                raise RepairKernelError(
                    path=command.path,
                    reason="duplicate_path",
                )

            seen_paths.add(command.path)
            selected_candidates.append(self.validate_command(command))

        return tuple(selected_candidates)

    def apply_repair_plan(self, plan: RepairPlanCommand) -> RepairResult:
        """Apply a validated batch plan to one copied shell.

        All commands are validated before any mutation. The repaired shell is
        validated once after every selected candidate has been promoted.
        """

        selected_candidates = self.validate_plan(plan)
        repaired_shell = copy.deepcopy(self.shell)

        repair_decisions: list[RepairDecision] = []
        for command, candidate in zip(
            plan.repair_commands, selected_candidates
        ):
            new_value = candidate.value
            old_value = self.get_shell_value(repaired_shell, command.path)

            self.set_shell_value(repaired_shell, command.path, new_value)
            repair_decisions.append(
                RepairDecision(
                    path=command.path,
                    old_value=old_value,
                    new_value=new_value,
                    candidate_index=command.candidate_index,
                    reason=command.reason,
                )
            )

        validation_result = validate_pdf_extracted_shell(repaired_shell)
        return RepairResult(
            shell=repaired_shell,
            decisions=(*self.decisions, *repair_decisions),
            validation=validation_result,
        )
