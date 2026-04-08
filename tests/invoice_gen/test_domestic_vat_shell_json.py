"""Tests for the frozen JSON serialization of the domestic VAT shell."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from src.invoice_gen.domain_shell import (
    AdnotationDefaults,
    BuyerIdMode,
    BuyerShell,
    DomesticVatInvoiceShell,
    InvoiceProfile,
    LineItemShell,
    PartyShell,
)
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_json import (
    SHELL_JSON_SCHEMA_VERSION,
    ShellJsonError,
    shell_from_dict,
    shell_from_json,
    shell_to_dict,
    shell_to_json,
)


# --- helpers --------------------------------------------------------------


def _minimal_shell() -> DomesticVatInvoiceShell:
    """Build one shell fully populated with simple deterministic values."""

    return DomesticVatInvoiceShell(
        profile=InvoiceProfile.DOMESTIC_VAT,
        currency="PLN",
        issue_date=date(2026, 4, 8),
        sale_date=date(2026, 4, 7),
        invoice_number="FV2026/04/001",
        issue_city="Warszawa",
        system_info=None,
        payment_form=1,
        seller=PartyShell(
            nip="1234567890",
            name="Seller sp. z o.o.",
            address_line_1="ul. Kwiatowa 1",
            address_line_2="00-001 Warszawa",
            email="biuro@seller.pl",
            phone="48123456789",
        ),
        buyer=BuyerShell(
            nip="0987654321",
            name="Buyer sp. z o.o.",
            address_line_1="ul. Polna 2",
            address_line_2="30-002 Krakow",
            email="kontakt@buyer.pl",
            phone="48987654321",
            buyer_id_mode=BuyerIdMode.DOMESTIC_NIP,
            jst=2,
            gv=2,
            customer_ref="KL123456",
        ),
        line_items=[
            LineItemShell(
                description="lodowka",
                unit="szt.",
                quantity=Decimal("2"),
                unit_price_net=Decimal("999.99"),
                vat_rate=Decimal("23"),
            ),
        ],
        adnotations=AdnotationDefaults(),
    )


# --- 1. Exact decimal formatting ------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1"), "1"),
        (Decimal("1.5"), "1.5"),
        (Decimal("100.00"), "100"),
        (Decimal("0.000001"), "0.000001"),
    ],
)
def test_quantity_serializes_as_plain_decimal_string(
    value: Decimal, expected: str
) -> None:
    """Quantities should serialize without scientific notation."""

    shell = _minimal_shell()
    shell.line_items[0].quantity = value

    dump = shell_to_dict(shell)

    assert dump["line_items"][0]["quantity"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1"), "1"),
        (Decimal("125.00"), "125"),
        (Decimal("12345.12345678"), "12345.12345678"),
        (Decimal("0.00000001"), "0.00000001"),
    ],
)
def test_unit_price_net_serializes_as_plain_decimal_string(
    value: Decimal, expected: str
) -> None:
    """Unit prices should serialize without scientific notation."""

    shell = _minimal_shell()
    shell.line_items[0].unit_price_net = value

    dump = shell_to_dict(shell)

    assert dump["line_items"][0]["unit_price_net"] == expected


# --- 2. Decimal precision guards ------------------------------------------


def test_quantity_with_seven_fraction_digits_raises() -> None:
    """Quantities beyond 6 fraction digits must be rejected."""

    shell = _minimal_shell()
    shell.line_items[0].quantity = Decimal("0.0000001")

    with pytest.raises(ShellJsonError, match="fraction digits"):
        shell_to_dict(shell)


def test_unit_price_net_with_nine_fraction_digits_raises() -> None:
    """Unit prices beyond 8 fraction digits must be rejected."""

    shell = _minimal_shell()
    shell.line_items[0].unit_price_net = Decimal("1E-9")

    with pytest.raises(ShellJsonError, match="fraction digits"):
        shell_to_dict(shell)


def test_decode_quantity_with_seven_fraction_digits_raises() -> None:
    """Precision guard must also fire on the load path."""

    shell = _minimal_shell()
    dump = shell_to_dict(shell)
    dump["line_items"][0]["quantity"] = "0.0000001"

    with pytest.raises(ShellJsonError, match="fraction digits"):
        shell_from_dict(dump)


# --- 3. vat_rate canonical form -------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("23"), "23"),
        (Decimal("5"), "5"),
        (Decimal("23.00"), "23"),
        (Decimal("5.0"), "5"),
    ],
)
def test_vat_rate_serializes_as_canonical_integer_string(
    value: Decimal, expected: str
) -> None:
    """VAT rates must serialize as plain integer-looking strings."""

    shell = _minimal_shell()
    shell.line_items[0].vat_rate = value

    dump = shell_to_dict(shell)

    assert dump["line_items"][0]["vat_rate"] == expected


# --- 4. Enums --------------------------------------------------------------


def test_enum_fields_serialize_as_values_and_round_trip() -> None:
    """Enums should serialize to their ``.value`` strings."""

    shell = _minimal_shell()

    dump = shell_to_dict(shell)

    assert dump["profile"] == "domestic_vat"
    assert dump["buyer"]["buyer_id_mode"] == "domestic_nip"

    restored = shell_from_dict(dump)

    assert restored.profile is InvoiceProfile.DOMESTIC_VAT
    assert restored.buyer.buyer_id_mode is BuyerIdMode.DOMESTIC_NIP


# --- 5. Dates --------------------------------------------------------------


def test_date_fields_serialize_as_iso_strings_and_round_trip() -> None:
    """Dates should use ISO ``YYYY-MM-DD`` encoding."""

    shell = _minimal_shell()

    dump = shell_to_dict(shell)

    assert dump["issue_date"] == "2026-04-08"
    assert dump["sale_date"] == "2026-04-07"

    restored = shell_from_dict(dump)

    assert restored.issue_date == date(2026, 4, 8)
    assert restored.sale_date == date(2026, 4, 7)


# --- 6. Omit-None ---------------------------------------------------------


def test_optional_none_fields_are_omitted_from_dump() -> None:
    """Optional fields equal to ``None`` must not appear in the dump."""

    shell = _minimal_shell()
    shell.system_info = None
    shell.seller.krs = None
    shell.seller.regon = None
    shell.seller.bdo = None
    shell.buyer.krs = None

    dump = shell_to_dict(shell)

    assert "system_info" not in dump
    assert "krs" not in dump["seller"]
    assert "regon" not in dump["seller"]
    assert "bdo" not in dump["seller"]
    assert "krs" not in dump["buyer"]


def test_missing_optional_keys_load_as_none() -> None:
    """Absent optional keys must become ``None`` on the reconstructed shell."""

    shell = _minimal_shell()
    shell.system_info = None
    shell.seller.krs = None
    shell.buyer.customer_ref = None

    restored = shell_from_dict(shell_to_dict(shell))

    assert restored.system_info is None
    assert restored.seller.krs is None
    assert restored.buyer.customer_ref is None
    assert restored == shell


# --- 7. Full pipeline round-trip ------------------------------------------


@pytest.mark.parametrize("seed", list(range(1, 21)))
def test_seed_pipeline_round_trip_is_lossless(seed: int) -> None:
    """Shells from the seed pipeline must survive JSON round-trip unchanged."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed))

    text = shell_to_json(shell)
    restored = shell_from_json(text)

    assert restored == shell


# --- 8. Determinism -------------------------------------------------------


def test_encoding_is_deterministic_for_same_shell() -> None:
    """Two encodings of the same shell must be byte-identical."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(7))

    first = shell_to_json(shell)
    second = shell_to_json(shell)

    assert first == second


def test_encoding_is_byte_stable_across_full_round_trip() -> None:
    """``encode(decode(encode(shell)))`` must be byte-identical to ``encode``."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(13))

    first = shell_to_json(shell)
    second = shell_to_json(shell_from_json(first))

    assert first == second


# --- 9. Schema version required ------------------------------------------


def test_missing_schema_version_raises() -> None:
    """Loading a payload without ``schema_version`` must raise."""

    dump = shell_to_dict(_minimal_shell())
    dump.pop("schema_version")

    with pytest.raises(ShellJsonError, match="schema_version"):
        shell_from_dict(dump)


def test_mismatched_schema_version_raises() -> None:
    """Loading a payload with a different schema version must raise."""

    dump = shell_to_dict(_minimal_shell())
    dump["schema_version"] = SHELL_JSON_SCHEMA_VERSION + 1

    with pytest.raises(ShellJsonError, match="schema_version"):
        shell_from_dict(dump)


# --- 10. Unknown keys ------------------------------------------------------


def test_unknown_top_level_key_raises() -> None:
    """Unknown top-level keys must be rejected, not silently accepted."""

    dump = shell_to_dict(_minimal_shell())
    dump["unexpected"] = True

    with pytest.raises(ShellJsonError, match="unknown keys"):
        shell_from_dict(dump)


def test_unknown_nested_key_raises() -> None:
    """Unknown keys inside nested objects must also be rejected."""

    dump = shell_to_dict(_minimal_shell())
    dump["seller"]["unexpected"] = "x"

    with pytest.raises(ShellJsonError, match="unknown keys"):
        shell_from_dict(dump)


# --- 11. Invalid enum value ----------------------------------------------


def test_invalid_profile_enum_raises() -> None:
    """Unknown enum values must raise ``ShellJsonError``."""

    dump = shell_to_dict(_minimal_shell())
    dump["profile"] = "foreign_vat"

    with pytest.raises(ShellJsonError, match="profile"):
        shell_from_dict(dump)


# --- 12. Public shape sanity checks --------------------------------------


def test_shell_to_json_output_is_valid_json_with_schema_version() -> None:
    """Output must parse as valid JSON and embed the schema version."""

    shell = _minimal_shell()

    text = shell_to_json(shell)
    parsed = json.loads(text)

    assert parsed["schema_version"] == SHELL_JSON_SCHEMA_VERSION
    assert parsed["profile"] == "domestic_vat"
    assert parsed["seller"]["nip"] == "1234567890"


def test_shell_to_json_uses_sorted_keys_for_determinism() -> None:
    """Top-level keys in the JSON string should appear in sorted order."""

    shell = _minimal_shell()

    text = shell_to_json(shell)
    parsed_keys = list(json.loads(text).keys())

    assert parsed_keys == sorted(parsed_keys)
