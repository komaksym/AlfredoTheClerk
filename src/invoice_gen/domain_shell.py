"""Domain-level shell objects for the domestic VAT MVP profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class InvoiceProfile(Enum):
    """Supported invoice profiles in the handwritten domain layer."""

    DOMESTIC_VAT = "domestic_vat"


class BuyerIdMode(Enum):
    """Supported buyer-identification modes for the current MVP."""

    DOMESTIC_NIP = "domestic_nip"


@dataclass(kw_only=True)
class AdnotationDefaults:
    """Fixed negative/default adnotation flags for the domestic VAT MVP."""

    cash_method_flag: int = 2
    self_billing_flag: int = 2
    reverse_charge_flag: int = 2
    split_payment_flag: int = 2
    special_procedure_flag: int = 2
    exemption_mode: str = "none"
    new_transport_mode: str = "none"
    margin_mode: str = "none"


@dataclass(kw_only=True)
class PartyShell:
    """Editable seller/buyer party data before schema mapping."""

    nip: str | None = None
    name: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    email: str | None = None
    phone: str | None = None
    krs: str | None = None
    regon: str | None = None
    bdo: str | None = None


@dataclass(kw_only=True)
class BuyerShell(PartyShell):
    """Buyer-specific domestic defaults layered on top of party data."""

    buyer_id_mode: BuyerIdMode = BuyerIdMode.DOMESTIC_NIP
    jst: int = 2
    gv: int = 2
    customer_ref: str | None = None


@dataclass(kw_only=True)
class LineItemShell:
    """Commercial line-item data captured before totals are computed."""

    description: str | None = None
    unit: str | None = None
    quantity: Decimal | None = None
    unit_price_net: Decimal | None = None
    vat_rate: Decimal | None = None


@dataclass(kw_only=True)
class DomesticVatInvoiceShell:
    """Editable domain shell for an ordinary domestic VAT invoice."""

    profile: InvoiceProfile = InvoiceProfile.DOMESTIC_VAT
    currency: str = "PLN"
    issue_date: date | None = None
    sale_date: date | None = None
    invoice_number: str | None = None
    issue_city: str | None = None
    system_info: str | None = None
    payment_form: int | None = None
    seller: PartyShell = field(default_factory=PartyShell)
    buyer: BuyerShell = field(default_factory=BuyerShell)
    line_items: list[LineItemShell] = field(default_factory=list)
    adnotations: AdnotationDefaults = field(default_factory=AdnotationDefaults)


def build_domestic_vat_shell() -> DomesticVatInvoiceShell:
    """Build an empty domestic VAT shell with fixed MVP defaults applied."""

    # The shell stays intentionally incomplete; later steps populate it with
    # extracted business values before validation, mapping, and rendering.
    return DomesticVatInvoiceShell(
        seller=PartyShell(),
        buyer=BuyerShell(
            buyer_id_mode=BuyerIdMode.DOMESTIC_NIP,
            jst=2,
            gv=2,
        ),
        line_items=[],
        adnotations=AdnotationDefaults(
            cash_method_flag=2,
            self_billing_flag=2,
            reverse_charge_flag=2,
            split_payment_flag=2,
            special_procedure_flag=2,
            exemption_mode="none",
            new_transport_mode="none",
            margin_mode="none",
        ),
    )
