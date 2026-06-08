import copy
import re
from dataclasses import dataclass

from src.input_processing.extraction_comparison import RepairContext
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

pattern = re.compile(r"^line_items\[(\d+)\]\.([a-z_]+)$")


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

    def validate_path_support(self, path):
        # is a supported shell path
        if path in TOP_LEVEL_REPAIRABLE:
            return True

        if "." not in path:
            return False

        prefix, suf = path.split(".", maxsplit=1)
        if prefix == "seller" and suf in SELLER_REPAIRABLE:
            return True

        if prefix == "buyer" and suf in BUYER_REPAIRABLE:
            return True

        match = pattern.match(path)
        if match is not None:
            index = int(match.group(1))
            field = match.group(2)

            if (
                0 <= index < len(self.shell.line_items)
                and field in LINE_ITEM_REPAIRABLE
            ):
                return True

        return False

    def validate_command(self, command):
        path = command.path

        # Validate path exists in evidence
        assert path in self.context.evidence, (
            "Path should exist in field evidence"
        )
        # is not summary.*
        assert not path.startswith("summary.")

        # is a supported shell path
        assert self.validate_path_support(path)

        # evidence has candidates
        candidates = self.context.evidence[path].candidates
        assert candidates

        # candidate index is valid
        candidates_len = len(candidates)
        assert 0 <= command.candidate_index < candidates_len

        # selected candidate value is not None
        selected_candidate = candidates[command.candidate_index]
        assert selected_candidate.value is not None

    def promote_candidate(self, command: RepairCommand) -> RepairResult:
        pass
