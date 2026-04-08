"""Validation helpers for the domestic VAT domain shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re

from src.invoice_gen.domain_shell import (
    AdnotationDefaults,
    BuyerIdMode,
    BuyerShell,
    DomesticVatInvoiceShell,
    InvoiceProfile,
    LineItemShell,
    PartyShell,
)

_NIP_PATTERN = re.compile(r"^[1-9](?:\d[1-9]|[1-9]\d)\d{7}$")
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_ALLOWED_VAT_RATES = {Decimal("23"), Decimal("5")}
_ALLOWED_PAYMENT_FORMS = {1, 2, 6}


# --- Public API and data structures --------------------------------------


@dataclass(frozen=True, kw_only=True)
class ShellValidationError:
    """One machine-readable validation problem found in the shell."""

    path: str
    code: str
    message: str


@dataclass(kw_only=True)
class ShellValidationResult:
    """Collected validation result for one domestic VAT shell."""

    errors: list[ShellValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Whether the shell passed every current MVP validation rule."""

        return not self.errors


def validate_domestic_vat_shell(
    shell: DomesticVatInvoiceShell,
) -> ShellValidationResult:
    """Validate one domestic VAT shell against the current MVP rules."""

    errors: list[ShellValidationError] = []

    _validate_invoice_fields(shell, errors)
    _validate_party_fields(shell.seller, "seller", errors)
    _validate_buyer_fields(shell.buyer, errors)
    _validate_cross_party_rules(shell, errors)
    _validate_line_items(shell.line_items, errors)
    _validate_adnotations(shell.adnotations, errors)

    return ShellValidationResult(errors=errors)


# --- Shell-section validators --------------------------------------------


def _validate_invoice_fields(
    shell: DomesticVatInvoiceShell,
    errors: list[ShellValidationError],
) -> None:
    """Validate invoice-level rules on the domestic shell."""

    if shell.profile is not InvoiceProfile.DOMESTIC_VAT:
        _add_error(
            errors,
            path="profile",
            code="unsupported_value",
            message="profile must be DOMESTIC_VAT",
        )

    if shell.currency != "PLN":
        _add_error(
            errors,
            path="currency",
            code="unsupported_value",
            message="currency must be PLN for the domestic VAT MVP",
        )

    if shell.issue_date is None:
        _add_error(
            errors,
            path="issue_date",
            code="required",
            message="issue_date is required",
        )

    if shell.sale_date is None:
        _add_error(
            errors,
            path="sale_date",
            code="required",
            message="sale_date is required",
        )

    if (
        shell.issue_date is not None
        and shell.sale_date is not None
        and shell.sale_date > shell.issue_date
    ):
        _add_error(
            errors,
            path="sale_date",
            code="invalid_relation",
            message="sale_date must not be later than issue_date",
        )

    _validate_required_string(
        shell.invoice_number,
        "invoice_number",
        errors,
    )
    _validate_required_string(
        shell.issue_city,
        "issue_city",
        errors,
    )
    _validate_payment_form(
        shell.payment_form,
        "payment_form",
        errors,
    )


def _validate_party_fields(
    party: PartyShell | None,
    prefix: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate seller or buyer party fields shared by both roles."""

    if party is None:
        _add_error(
            errors,
            path=prefix,
            code="required",
            message=f"{prefix} is required",
        )
        return

    _validate_nip(
        party.nip,
        f"{prefix}.nip",
        errors,
    )
    _validate_required_string(
        party.name,
        f"{prefix}.name",
        errors,
    )
    _validate_required_string(
        party.address_line_1,
        f"{prefix}.address_line_1",
        errors,
    )
    _validate_required_string(
        party.address_line_2,
        f"{prefix}.address_line_2",
        errors,
    )


def _validate_buyer_fields(
    buyer: BuyerShell | None,
    errors: list[ShellValidationError],
) -> None:
    """Validate buyer-specific domestic rules."""

    _validate_party_fields(buyer, "buyer", errors)

    if buyer is None:
        return

    if buyer.buyer_id_mode is not BuyerIdMode.DOMESTIC_NIP:
        _add_error(
            errors,
            path="buyer.buyer_id_mode",
            code="unsupported_value",
            message="buyer_id_mode must be DOMESTIC_NIP",
        )

    if buyer.jst != 2:
        _add_error(
            errors,
            path="buyer.jst",
            code="unsupported_value",
            message="buyer.jst must be 2 for the domestic VAT MVP",
        )

    if buyer.gv != 2:
        _add_error(
            errors,
            path="buyer.gv",
            code="unsupported_value",
            message="buyer.gv must be 2 for the domestic VAT MVP",
        )


def _validate_cross_party_rules(
    shell: DomesticVatInvoiceShell,
    errors: list[ShellValidationError],
) -> None:
    """Validate shell rules that depend on multiple fields together."""

    seller_nip = shell.seller.nip if shell.seller is not None else None
    buyer_nip = shell.buyer.nip if shell.buyer is not None else None

    if (
        isinstance(seller_nip, str)
        and isinstance(buyer_nip, str)
        and seller_nip.strip()
        and buyer_nip.strip()
        and seller_nip == buyer_nip
    ):
        _add_error(
            errors,
            path="buyer.nip",
            code="invalid_relation",
            message="buyer.nip must differ from seller.nip",
        )


def _validate_line_items(
    line_items: list[LineItemShell] | None,
    errors: list[ShellValidationError],
) -> None:
    """Validate domestic VAT line-item presence and field constraints."""

    if not line_items:
        _add_error(
            errors,
            path="line_items",
            code="required",
            message="at least one line item is required",
        )
        return

    for index, line_item in enumerate(line_items):
        prefix = f"line_items[{index}]"

        _validate_required_string(
            line_item.description,
            f"{prefix}.description",
            errors,
        )
        _validate_required_string(
            line_item.unit,
            f"{prefix}.unit",
            errors,
        )
        _validate_positive_decimal(
            line_item.quantity,
            f"{prefix}.quantity",
            errors,
        )
        _validate_positive_decimal(
            line_item.unit_price_net,
            f"{prefix}.unit_price_net",
            errors,
        )
        _validate_vat_rate(
            line_item.vat_rate,
            f"{prefix}.vat_rate",
            errors,
        )


def _validate_adnotations(
    adnotations: AdnotationDefaults | None,
    errors: list[ShellValidationError],
) -> None:
    """Validate the fixed adnotation defaults used by the current MVP."""

    if adnotations is None:
        _add_error(
            errors,
            path="adnotations",
            code="required",
            message="adnotations are required",
        )
        return

    _validate_expected_value(
        adnotations.cash_method_flag,
        2,
        "adnotations.cash_method_flag",
        errors,
    )
    _validate_expected_value(
        adnotations.self_billing_flag,
        2,
        "adnotations.self_billing_flag",
        errors,
    )
    _validate_expected_value(
        adnotations.reverse_charge_flag,
        2,
        "adnotations.reverse_charge_flag",
        errors,
    )
    _validate_expected_value(
        adnotations.split_payment_flag,
        2,
        "adnotations.split_payment_flag",
        errors,
    )
    _validate_expected_value(
        adnotations.special_procedure_flag,
        2,
        "adnotations.special_procedure_flag",
        errors,
    )
    _validate_expected_value(
        adnotations.exemption_mode,
        "none",
        "adnotations.exemption_mode",
        errors,
    )
    _validate_expected_value(
        adnotations.new_transport_mode,
        "none",
        "adnotations.new_transport_mode",
        errors,
    )
    _validate_expected_value(
        adnotations.margin_mode,
        "none",
        "adnotations.margin_mode",
        errors,
    )


# --- Primitive field validators ------------------------------------------


def _validate_required_string(
    value: str | None,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate that a string field exists and is not blank."""

    if value is None:
        _add_error(
            errors,
            path=path,
            code="required",
            message=f"{path} is required",
        )
        return

    if not value.strip():
        _add_error(
            errors,
            path=path,
            code="blank",
            message=f"{path} must not be blank",
        )


def _validate_nip(
    value: str | None,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate the basic NIP format and checksum rules."""

    if value is None:
        _add_error(
            errors,
            path=path,
            code="required",
            message=f"{path} is required",
        )
        return

    if not value.strip():
        _add_error(
            errors,
            path=path,
            code="blank",
            message=f"{path} must not be blank",
        )
        return

    if not _NIP_PATTERN.fullmatch(value):
        _add_error(
            errors,
            path=path,
            code="invalid_format",
            message=f"{path} must match the FA(3) NIP lexical format",
        )
        return

    if not _is_valid_nip(value):
        _add_error(
            errors,
            path=path,
            code="invalid_checksum",
            message=f"{path} failed the NIP checksum",
        )


def _validate_positive_decimal(
    value: Decimal | None,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate that a numeric shell field is a positive Decimal."""

    if value is None:
        _add_error(
            errors,
            path=path,
            code="required",
            message=f"{path} is required",
        )
        return

    if not isinstance(value, Decimal):
        _add_error(
            errors,
            path=path,
            code="invalid_value",
            message=f"{path} must be a Decimal",
        )
        return

    if value <= 0:
        _add_error(
            errors,
            path=path,
            code="invalid_value",
            message=f"{path} must be greater than zero",
        )


def _validate_vat_rate(
    value: Decimal | None,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate that the VAT rate is present and allowed in the MVP."""

    if value is None:
        _add_error(
            errors,
            path=path,
            code="required",
            message=f"{path} is required",
        )
        return

    if not isinstance(value, Decimal):
        _add_error(
            errors,
            path=path,
            code="invalid_value",
            message=f"{path} must be a Decimal",
        )
        return

    if value not in _ALLOWED_VAT_RATES:
        _add_error(
            errors,
            path=path,
            code="unsupported_value",
            message=f"{path} must be one of {sorted(_ALLOWED_VAT_RATES)}",
        )


def _validate_payment_form(
    value: int | None,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate the optional domestic MVP payment-form code."""

    if value is None:
        return

    if not isinstance(value, int) or isinstance(value, bool):
        _add_error(
            errors,
            path=path,
            code="invalid_value",
            message=f"{path} must be an int",
        )
        return

    if value not in _ALLOWED_PAYMENT_FORMS:
        _add_error(
            errors,
            path=path,
            code="unsupported_value",
            message=f"{path} must be one of {sorted(_ALLOWED_PAYMENT_FORMS)}",
        )


def _validate_expected_value(
    value: object,
    expected: object,
    path: str,
    errors: list[ShellValidationError],
) -> None:
    """Validate that a fixed MVP default still has the expected value."""

    if value != expected:
        _add_error(
            errors,
            path=path,
            code="unsupported_value",
            message=f"{path} must equal {expected!r}",
        )


# --- Internal helpers ----------------------------------------------------


def _is_valid_nip(value: str) -> bool:
    """Check the weighted modulo-11 checksum for a ten-digit NIP."""

    checksum = (
        sum(
            int(digit) * weight
            for digit, weight in zip(value[:9], _NIP_WEIGHTS, strict=True)
        )
        % 11
    )
    return checksum != 10 and checksum == int(value[9])


def _add_error(
    errors: list[ShellValidationError],
    *,
    path: str,
    code: str,
    message: str,
) -> None:
    """Append one validation error to the shared error list."""

    errors.append(
        ShellValidationError(
            path=path,
            code=code,
            message=message,
        )
    )
