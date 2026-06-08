from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from src.input_processing.extraction_comparison import RepairContext
from src.input_processing.invoice_text_field_extraction import Candidate
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult

TOP_LEVEL_REPAIRABLE = {
    "invoice_number",
    "issue_date",
    "sale_date",
    "issue_city",
    "payment_form",
    "payment_due_date",
}

SELLER_REPAIRABLE = {
    "nip",
    "name",
    "address_line_1",
    "address_line_2",
    "bank_account",
}

BUYER_REPAIRABLE = {
    "nip",
    "name",
    "address_line_1",
    "address_line_2",
}

LINE_ITEM_REPAIRABLE = {
    "description",
    "unit",
    "quantity",
    "unit_price_net",
    "discount",
    "vat_rate",
}

_LINE_ITEM_PATH_PATTERN = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")


class RepairKernelError(ValueError):
    """Raised when an agent repair command fails deterministic safety checks."""

    def __init__(self, *, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


@dataclass(frozen=True)
class RepairDecision:
    path: str
    old_value: object
    new_value: object
    candidate_index: int
    reason: str


@dataclass(frozen=True)
class RepairCommand:
    path: str
    candidate_index: int
    reason: str


@dataclass(frozen=True)
class RepairResult:
    shell: DomesticVatInvoiceShell
    decisions: tuple[RepairDecision, ...]
    validation: ShellValidationResult


@dataclass(frozen=True)
class RepairSession:
    context: RepairContext
    shell: DomesticVatInvoiceShell
    decisions: tuple[RepairDecision, ...]
    validation: ShellValidationResult

    @classmethod
    def from_context(cls, context: RepairContext) -> "RepairSession":
        return cls(
            context=context,
            shell=copy.deepcopy(context.shell),
            decisions=(),
            validation=context.validation,
        )

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

    def promote_candidate(self, command: RepairCommand) -> RepairResult:
        raise NotImplementedError("Candidate promotion is implemented in M6.2")
