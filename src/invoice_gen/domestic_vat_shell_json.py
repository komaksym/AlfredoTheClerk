"""Frozen JSON serialization for the domestic VAT domain shell.

This module owns the benchmark-contract encoding for
``DomesticVatInvoiceShell``. The encoding is deterministic, lossless, and
governed by ``SHELL_JSON_SCHEMA_VERSION``: any breaking change to the
rules must bump that constant.

The rules mirror ROADMAP.md section 3:

* ``quantity``        -> plain decimal string, max 6 fraction digits
* ``unit_price_net``  -> plain decimal string, max 8 fraction digits
* ``vat_rate``        -> canonical business value like ``"23"`` or ``"5"``
* ``date``            -> ISO ``YYYY-MM-DD``
* enums               -> ``.value``
* nested dataclasses  -> nested JSON objects
* optional fields     -> omitted when ``None``

The serializer intentionally avoids reflection; each dataclass has its
own explicit mapping so the frozen contract stays auditable.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.invoice_gen.domain_shell import (
    AdnotationDefaults,
    BuyerIdMode,
    BuyerShell,
    DomesticVatInvoiceShell,
    InvoiceProfile,
    LineItemShell,
    PartyShell,
)


SHELL_JSON_SCHEMA_VERSION = 1


class ShellJsonError(Exception):
    """One schema or payload error raised while (de)serializing a shell."""


_QUANTITY_MAX_FRACTION_DIGITS = 6
_UNIT_PRICE_NET_MAX_FRACTION_DIGITS = 8
_VAT_RATE_MAX_FRACTION_DIGITS = 0


_SHELL_KEYS = frozenset(
    {
        "schema_version",
        "profile",
        "currency",
        "issue_date",
        "sale_date",
        "invoice_number",
        "issue_city",
        "system_info",
        "payment_form",
        "seller",
        "buyer",
        "line_items",
        "adnotations",
    }
)
_SHELL_REQUIRED_KEYS = frozenset(
    {
        "profile",
        "currency",
        "seller",
        "buyer",
        "line_items",
        "adnotations",
    }
)
_PARTY_KEYS = frozenset(
    {
        "nip",
        "name",
        "address_line_1",
        "address_line_2",
        "email",
        "phone",
        "krs",
        "regon",
        "bdo",
    }
)
_BUYER_KEYS = _PARTY_KEYS | frozenset(
    {"buyer_id_mode", "jst", "gv", "customer_ref"}
)
_BUYER_REQUIRED_KEYS = frozenset({"buyer_id_mode", "jst", "gv"})
_LINE_ITEM_KEYS = frozenset(
    {"description", "unit", "quantity", "unit_price_net", "vat_rate"}
)
_ADNOTATION_KEYS = frozenset(
    {
        "cash_method_flag",
        "self_billing_flag",
        "reverse_charge_flag",
        "split_payment_flag",
        "special_procedure_flag",
        "exemption_mode",
        "new_transport_mode",
        "margin_mode",
    }
)


def shell_to_dict(shell: DomesticVatInvoiceShell) -> dict[str, Any]:
    """Encode one shell into the frozen JSON-ready dict form."""

    data: dict[str, Any] = {
        "schema_version": SHELL_JSON_SCHEMA_VERSION,
        "profile": shell.profile.value,
        "currency": shell.currency,
        "seller": _party_to_dict(shell.seller),
        "buyer": _buyer_to_dict(shell.buyer),
        "line_items": [
            _line_item_to_dict(item, index=index)
            for index, item in enumerate(shell.line_items)
        ],
        "adnotations": _adnotations_to_dict(shell.adnotations),
    }
    if shell.issue_date is not None:
        data["issue_date"] = shell.issue_date.isoformat()
    if shell.sale_date is not None:
        data["sale_date"] = shell.sale_date.isoformat()
    if shell.invoice_number is not None:
        data["invoice_number"] = shell.invoice_number
    if shell.issue_city is not None:
        data["issue_city"] = shell.issue_city
    if shell.system_info is not None:
        data["system_info"] = shell.system_info
    if shell.payment_form is not None:
        data["payment_form"] = shell.payment_form
    return data


def shell_to_json(shell: DomesticVatInvoiceShell) -> str:
    """Encode one shell into a deterministic frozen JSON string."""

    return json.dumps(
        shell_to_dict(shell),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def shell_from_dict(data: Any) -> DomesticVatInvoiceShell:
    """Decode one shell from the frozen JSON-ready dict form."""

    _require_object(data, "shell")
    _require_schema_version(data)
    _reject_unknown_keys(data, _SHELL_KEYS, "shell")
    _require_keys(data, _SHELL_REQUIRED_KEYS, "shell")

    try:
        profile = InvoiceProfile(data["profile"])
    except ValueError as exc:
        raise ShellJsonError(f"invalid shell.profile: {exc}") from exc

    currency = data["currency"]
    if not isinstance(currency, str):
        raise ShellJsonError("shell.currency must be a string")

    line_items_raw = data["line_items"]
    if not isinstance(line_items_raw, list):
        raise ShellJsonError("shell.line_items must be a JSON array")

    return DomesticVatInvoiceShell(
        profile=profile,
        currency=currency,
        issue_date=_decode_date(data.get("issue_date"), "shell.issue_date"),
        sale_date=_decode_date(data.get("sale_date"), "shell.sale_date"),
        invoice_number=_decode_optional_str(
            data.get("invoice_number"), "shell.invoice_number"
        ),
        issue_city=_decode_optional_str(
            data.get("issue_city"), "shell.issue_city"
        ),
        system_info=_decode_optional_str(
            data.get("system_info"), "shell.system_info"
        ),
        payment_form=_decode_optional_int(
            data.get("payment_form"), "shell.payment_form"
        ),
        seller=_party_from_dict(data["seller"], path="shell.seller"),
        buyer=_buyer_from_dict(data["buyer"], path="shell.buyer"),
        line_items=[
            _line_item_from_dict(item, path=f"shell.line_items[{index}]")
            for index, item in enumerate(line_items_raw)
        ],
        adnotations=_adnotations_from_dict(
            data["adnotations"], path="shell.adnotations"
        ),
    )


def shell_from_json(text: str) -> DomesticVatInvoiceShell:
    """Decode one shell from a frozen JSON string."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShellJsonError(f"invalid JSON: {exc}") from exc
    return shell_from_dict(data)


# --- Nested encoders ------------------------------------------------------


def _party_to_dict(party: PartyShell) -> dict[str, Any]:
    """Encode one PartyShell, omitting keys whose values are None."""

    data: dict[str, Any] = {}
    _set_if_present(data, "nip", party.nip)
    _set_if_present(data, "name", party.name)
    _set_if_present(data, "address_line_1", party.address_line_1)
    _set_if_present(data, "address_line_2", party.address_line_2)
    _set_if_present(data, "email", party.email)
    _set_if_present(data, "phone", party.phone)
    _set_if_present(data, "krs", party.krs)
    _set_if_present(data, "regon", party.regon)
    _set_if_present(data, "bdo", party.bdo)
    return data


def _buyer_to_dict(buyer: BuyerShell) -> dict[str, Any]:
    """Encode one BuyerShell on top of the shared party encoding."""

    data = _party_to_dict(buyer)
    data["buyer_id_mode"] = buyer.buyer_id_mode.value
    data["jst"] = buyer.jst
    data["gv"] = buyer.gv
    _set_if_present(data, "customer_ref", buyer.customer_ref)
    return data


def _line_item_to_dict(item: LineItemShell, *, index: int) -> dict[str, Any]:
    """Encode one LineItemShell with frozen decimal formatting rules."""

    path = f"line_items[{index}]"
    data: dict[str, Any] = {}
    _set_if_present(data, "description", item.description)
    _set_if_present(data, "unit", item.unit)
    if item.quantity is not None:
        data["quantity"] = _format_decimal(
            item.quantity,
            max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
            field_path=f"{path}.quantity",
        )
    if item.unit_price_net is not None:
        data["unit_price_net"] = _format_decimal(
            item.unit_price_net,
            max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
            field_path=f"{path}.unit_price_net",
        )
    if item.vat_rate is not None:
        data["vat_rate"] = _format_decimal(
            item.vat_rate,
            max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
            field_path=f"{path}.vat_rate",
        )
    return data


def _adnotations_to_dict(adnotations: AdnotationDefaults) -> dict[str, Any]:
    """Encode one AdnotationDefaults object with all fields present."""

    return {
        "cash_method_flag": adnotations.cash_method_flag,
        "self_billing_flag": adnotations.self_billing_flag,
        "reverse_charge_flag": adnotations.reverse_charge_flag,
        "split_payment_flag": adnotations.split_payment_flag,
        "special_procedure_flag": adnotations.special_procedure_flag,
        "exemption_mode": adnotations.exemption_mode,
        "new_transport_mode": adnotations.new_transport_mode,
        "margin_mode": adnotations.margin_mode,
    }


# --- Nested decoders ------------------------------------------------------


def _party_from_dict(data: Any, *, path: str) -> PartyShell:
    """Decode one PartyShell from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _PARTY_KEYS, path)
    return PartyShell(
        nip=_decode_optional_str(data.get("nip"), f"{path}.nip"),
        name=_decode_optional_str(data.get("name"), f"{path}.name"),
        address_line_1=_decode_optional_str(
            data.get("address_line_1"), f"{path}.address_line_1"
        ),
        address_line_2=_decode_optional_str(
            data.get("address_line_2"), f"{path}.address_line_2"
        ),
        email=_decode_optional_str(data.get("email"), f"{path}.email"),
        phone=_decode_optional_str(data.get("phone"), f"{path}.phone"),
        krs=_decode_optional_str(data.get("krs"), f"{path}.krs"),
        regon=_decode_optional_str(data.get("regon"), f"{path}.regon"),
        bdo=_decode_optional_str(data.get("bdo"), f"{path}.bdo"),
    )


def _buyer_from_dict(data: Any, *, path: str) -> BuyerShell:
    """Decode one BuyerShell from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _BUYER_KEYS, path)
    _require_keys(data, _BUYER_REQUIRED_KEYS, path)

    try:
        buyer_id_mode = BuyerIdMode(data["buyer_id_mode"])
    except ValueError as exc:
        raise ShellJsonError(f"invalid {path}.buyer_id_mode: {exc}") from exc

    jst = data["jst"]
    gv = data["gv"]
    if not isinstance(jst, int) or isinstance(jst, bool):
        raise ShellJsonError(f"{path}.jst must be an integer")
    if not isinstance(gv, int) or isinstance(gv, bool):
        raise ShellJsonError(f"{path}.gv must be an integer")

    return BuyerShell(
        nip=_decode_optional_str(data.get("nip"), f"{path}.nip"),
        name=_decode_optional_str(data.get("name"), f"{path}.name"),
        address_line_1=_decode_optional_str(
            data.get("address_line_1"), f"{path}.address_line_1"
        ),
        address_line_2=_decode_optional_str(
            data.get("address_line_2"), f"{path}.address_line_2"
        ),
        email=_decode_optional_str(data.get("email"), f"{path}.email"),
        phone=_decode_optional_str(data.get("phone"), f"{path}.phone"),
        krs=_decode_optional_str(data.get("krs"), f"{path}.krs"),
        regon=_decode_optional_str(data.get("regon"), f"{path}.regon"),
        bdo=_decode_optional_str(data.get("bdo"), f"{path}.bdo"),
        buyer_id_mode=buyer_id_mode,
        jst=jst,
        gv=gv,
        customer_ref=_decode_optional_str(
            data.get("customer_ref"), f"{path}.customer_ref"
        ),
    )


def _line_item_from_dict(data: Any, *, path: str) -> LineItemShell:
    """Decode one LineItemShell from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _LINE_ITEM_KEYS, path)
    return LineItemShell(
        description=_decode_optional_str(
            data.get("description"), f"{path}.description"
        ),
        unit=_decode_optional_str(data.get("unit"), f"{path}.unit"),
        quantity=_decode_decimal(
            data.get("quantity"),
            f"{path}.quantity",
            max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
        ),
        unit_price_net=_decode_decimal(
            data.get("unit_price_net"),
            f"{path}.unit_price_net",
            max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
        ),
        vat_rate=_decode_decimal(
            data.get("vat_rate"),
            f"{path}.vat_rate",
            max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
        ),
    )


def _adnotations_from_dict(data: Any, *, path: str) -> AdnotationDefaults:
    """Decode one AdnotationDefaults object from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _ADNOTATION_KEYS, path)
    _require_keys(data, _ADNOTATION_KEYS, path)

    for int_field in (
        "cash_method_flag",
        "self_billing_flag",
        "reverse_charge_flag",
        "split_payment_flag",
        "special_procedure_flag",
    ):
        value = data[int_field]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ShellJsonError(f"{path}.{int_field} must be an integer")
    for str_field in (
        "exemption_mode",
        "new_transport_mode",
        "margin_mode",
    ):
        if not isinstance(data[str_field], str):
            raise ShellJsonError(f"{path}.{str_field} must be a string")

    return AdnotationDefaults(
        cash_method_flag=data["cash_method_flag"],
        self_billing_flag=data["self_billing_flag"],
        reverse_charge_flag=data["reverse_charge_flag"],
        split_payment_flag=data["split_payment_flag"],
        special_procedure_flag=data["special_procedure_flag"],
        exemption_mode=data["exemption_mode"],
        new_transport_mode=data["new_transport_mode"],
        margin_mode=data["margin_mode"],
    )


# --- Primitive helpers ----------------------------------------------------


def _set_if_present(data: dict[str, Any], key: str, value: Any) -> None:
    """Assign ``value`` under ``key`` only when the value is not ``None``."""

    if value is not None:
        data[key] = value


def _require_object(data: Any, path: str) -> None:
    """Raise ``ShellJsonError`` unless ``data`` is a JSON object (dict)."""

    if not isinstance(data, dict):
        raise ShellJsonError(f"{path} payload must be a JSON object")


def _reject_unknown_keys(
    data: dict[str, Any],
    allowed: frozenset[str],
    path: str,
) -> None:
    """Raise ``ShellJsonError`` if ``data`` carries any key outside ``allowed``."""

    extra = sorted(key for key in data if key not in allowed)
    if extra:
        raise ShellJsonError(f"{path} payload has unknown keys: {extra}")


def _require_keys(
    data: dict[str, Any],
    required: frozenset[str],
    path: str,
) -> None:
    """Raise ``ShellJsonError`` if any ``required`` key is absent from ``data``."""

    missing = sorted(required - data.keys())
    if missing:
        raise ShellJsonError(
            f"{path} payload is missing required keys: {missing}"
        )


def _require_schema_version(data: dict[str, Any]) -> None:
    """Enforce that ``data`` declares the expected frozen schema version."""

    if "schema_version" not in data:
        raise ShellJsonError("shell payload is missing 'schema_version'")
    version = data["schema_version"]
    if version != SHELL_JSON_SCHEMA_VERSION:
        raise ShellJsonError(
            f"shell payload schema_version {version!r} does not match "
            f"expected {SHELL_JSON_SCHEMA_VERSION}"
        )


def _decode_optional_str(value: Any, path: str) -> str | None:
    """Decode one optional string field, rejecting non-string non-``None`` input."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ShellJsonError(f"{path} must be a string")
    return value


def _decode_optional_int(value: Any, path: str) -> int | None:
    """Decode one optional integer field, rejecting bools and non-int input."""

    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ShellJsonError(f"{path} must be an integer")
    return value


def _decode_date(value: Any, path: str) -> date | None:
    """Decode one optional ISO ``YYYY-MM-DD`` date string into a ``date``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ShellJsonError(f"{path} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ShellJsonError(f"invalid {path}: {exc}") from exc


def _decode_decimal(
    value: Any,
    path: str,
    *,
    max_fraction_digits: int,
) -> Decimal | None:
    """Decode one optional decimal string, enforcing finiteness and precision."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ShellJsonError(f"{path} must be a plain decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ShellJsonError(f"invalid {path}: {exc}") from exc
    if not parsed.is_finite():
        raise ShellJsonError(f"{path} must be a finite decimal")
    _check_fraction_digits(
        parsed, max_fraction_digits=max_fraction_digits, field_path=path
    )
    return parsed


def _format_decimal(
    value: Decimal,
    *,
    max_fraction_digits: int,
    field_path: str,
) -> str:
    """Format one finite ``Decimal`` as a plain decimal string with no exponent."""

    if not value.is_finite():
        raise ShellJsonError(f"{field_path} must be a finite decimal")
    normalized = value.normalize()
    _check_fraction_digits(
        normalized,
        max_fraction_digits=max_fraction_digits,
        field_path=field_path,
    )
    return format(normalized, "f")


def _check_fraction_digits(
    value: Decimal,
    *,
    max_fraction_digits: int,
    field_path: str,
) -> None:
    """Raise if ``value`` has more fraction digits than the frozen rule allows."""

    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    assert isinstance(exponent, int)  # finite => int exponent
    fraction_digits = -exponent if exponent < 0 else 0
    if fraction_digits > max_fraction_digits:
        raise ShellJsonError(
            f"{field_path} exceeds the supported "
            f"{max_fraction_digits} fraction digits"
        )
