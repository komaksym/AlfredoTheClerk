"""Tests for the structured domestic VAT synthetic seed layer."""

from __future__ import annotations

import importlib
import re
import sys

from src.invoice_gen.domestic_vat_seed import (
    DomesticVatInvoiceSeed,
    build_domestic_vat_seed,
)

_NIP_PATTERN = re.compile(r"^[1-9](?:\d[1-9]|[1-9]\d)\d{7}$")
_INVOICE_NUMBER_PATTERN = re.compile(r"^FV\d{4}/\d{2}/\d{3}$")
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def test_build_domestic_vat_seed_returns_structured_seed_with_domestic_defaults() -> (
    None
):
    """The factory should return a populated seed for one domestic VAT sample."""

    invoice_seed = build_domestic_vat_seed(seed=7)

    assert isinstance(invoice_seed, DomesticVatInvoiceSeed)
    assert invoice_seed.currency == "PLN"
    assert invoice_seed.seller.name
    assert invoice_seed.buyer.name
    assert invoice_seed.seller.address_line_1
    assert invoice_seed.buyer.address_line_2
    assert len(invoice_seed.line_items) >= 1


def test_build_domestic_vat_seed_generates_checksum_valid_distinct_nips() -> (
    None
):
    """Seller and buyer NIPs should follow the domestic formal rules."""

    for seed in range(50):
        invoice_seed = build_domestic_vat_seed(seed=seed)

        assert _NIP_PATTERN.fullmatch(invoice_seed.seller.nip)
        assert _NIP_PATTERN.fullmatch(invoice_seed.buyer.nip)
        assert _is_valid_nip(invoice_seed.seller.nip)
        assert _is_valid_nip(invoice_seed.buyer.nip)
        assert invoice_seed.seller.nip != invoice_seed.buyer.nip


def test_build_domestic_vat_seed_generates_distinct_party_addresses() -> None:
    """Seller and buyer addresses should not collide within one sample."""

    invoice_seed = build_domestic_vat_seed(seed=17)

    seller_address = (
        invoice_seed.seller.address_line_1,
        invoice_seed.seller.address_line_2,
    )
    buyer_address = (
        invoice_seed.buyer.address_line_1,
        invoice_seed.buyer.address_line_2,
    )

    assert seller_address != buyer_address


def test_build_domestic_vat_seed_generates_ordered_dates_and_invoice_number_pattern() -> (
    None
):
    """Dates and invoice numbers should follow the domestic seed constraints."""

    invoice_seed = build_domestic_vat_seed(seed=23)

    assert invoice_seed.sale_date <= invoice_seed.issue_date
    assert _INVOICE_NUMBER_PATTERN.fullmatch(invoice_seed.invoice_number)


def test_build_domestic_vat_seed_generates_positive_line_values_with_allowed_vat_rates() -> (
    None
):
    """Line items should use positive Decimals and the fixed VAT-rate set."""

    invoice_seed = build_domestic_vat_seed(seed=31)
    allowed_vat_rates = {"23", "5"}

    for line_item in invoice_seed.line_items:
        assert line_item.quantity > 0
        assert line_item.unit_price_net > 0
        assert str(line_item.vat_rate) in allowed_vat_rates


def test_build_domestic_vat_seed_generates_optional_discounts_as_valid_money() -> (
    None
):
    """Discounts should be optional positive money amounts within line gross net."""

    for seed in range(50):
        invoice_seed = build_domestic_vat_seed(seed=seed)

        for line_item in invoice_seed.line_items:
            if line_item.discount is None:
                continue

            assert line_item.discount > 0
            assert line_item.discount.as_tuple().exponent >= -2
            assert line_item.discount <= (
                line_item.quantity * line_item.unit_price_net
            )


def test_build_domestic_vat_seed_is_reproducible_for_the_same_seed() -> None:
    """The same input seed should yield the same generated invoice seed."""

    first = build_domestic_vat_seed(seed=101)
    second = build_domestic_vat_seed(seed=101)

    assert first == second


def test_domestic_vat_seed_import_does_not_load_ksef_schema(
    monkeypatch,
) -> None:
    """Importing the seed module should not import the schema layer."""

    for module_name in list(sys.modules):
        if (
            module_name == "src.invoice_gen.domestic_vat_seed"
            or module_name.startswith("ksef_schema")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.invalidate_caches()
    importlib.import_module("src.invoice_gen.domestic_vat_seed")

    assert not any(
        module_name == "ksef_schema" or module_name.startswith("ksef_schema.")
        for module_name in sys.modules
    )


def _is_valid_nip(value: str) -> bool:
    """Check the weighted modulo-11 checksum used by Polish NIP numbers."""

    if not _NIP_PATTERN.fullmatch(value):
        return False

    checksum = (
        sum(
            int(digit) * weight
            for digit, weight in zip(value[:9], _NIP_WEIGHTS, strict=True)
        )
        % 11
    )
    return checksum != 10 and checksum == int(value[9])
