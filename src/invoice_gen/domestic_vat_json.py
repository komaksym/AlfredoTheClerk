"""Frozen JSON serialization for domestic VAT benchmark artifacts.

This module owns the benchmark-contract encoding for both
``DomesticVatInvoiceShell`` (the canonical business truth) and
``DomesticVatInvoiceSummary`` (derived monetary totals). Each payload is
deterministic, lossless, and governed by its own schema-version constant:
any breaking change to the rules must bump that constant.

The rules mirror ROADMAP.md section 3:

* money fields        -> canonical two-decimal money strings
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
from src.invoice_gen.domestic_vat_money import format_decimal, format_money
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
    DomesticVatLineComputation,
)


SHELL_JSON_SCHEMA_VERSION = 1
SUMMARY_JSON_SCHEMA_VERSION = 1


class DomesticVatJsonError(Exception):
    """One schema or payload error raised while (de)serializing JSON."""


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
        "payment_due_date",
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
        "bank_account",
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
_SUMMARY_KEYS = frozenset(
    {
        "schema_version",
        "line_computations",
        "bucket_summaries",
        "invoice_net_total",
        "invoice_vat_total",
        "invoice_gross_total",
    }
)
_SUMMARY_REQUIRED_KEYS = frozenset(
    {
        "line_computations",
        "bucket_summaries",
        "invoice_net_total",
        "invoice_vat_total",
        "invoice_gross_total",
    }
)
_LINE_COMPUTATION_KEYS = frozenset(
    {
        "line_index",
        "description",
        "quantity",
        "unit_price_net",
        "vat_rate",
        "line_net_total",
        "line_vat_total",
        "line_gross_total",
    }
)
_BUCKET_SUMMARY_KEYS = frozenset({"net_total", "vat_total", "gross_total"})


# --- Public API (shell) --------------------------------------------------


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
    if shell.payment_due_date is not None:
        data["payment_due_date"] = shell.payment_due_date.isoformat()
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
    _require_schema_version(
        data, expected=SHELL_JSON_SCHEMA_VERSION, payload_name="shell"
    )
    _reject_unknown_keys(data, _SHELL_KEYS, "shell")
    _require_keys(data, _SHELL_REQUIRED_KEYS, "shell")

    try:
        profile = InvoiceProfile(data["profile"])
    except ValueError as exc:
        raise DomesticVatJsonError(f"invalid shell.profile: {exc}") from exc

    currency = data["currency"]
    if not isinstance(currency, str):
        raise DomesticVatJsonError("shell.currency must be a string")

    line_items_raw = data["line_items"]
    if not isinstance(line_items_raw, list):
        raise DomesticVatJsonError("shell.line_items must be a JSON array")

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
        payment_due_date=_decode_date(
            data.get("payment_due_date"), "shell.payment_due_date"
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
        raise DomesticVatJsonError(f"invalid JSON: {exc}") from exc
    return shell_from_dict(data)


# --- Public API (summary) ------------------------------------------------


def summary_to_dict(
    summary: DomesticVatInvoiceSummary,
) -> dict[str, Any]:
    """Encode one invoice summary into the frozen JSON-ready dict form."""

    return {
        "schema_version": SUMMARY_JSON_SCHEMA_VERSION,
        "line_computations": [
            _line_computation_to_dict(lc) for lc in summary.line_computations
        ],
        "bucket_summaries": {
            _encode_decimal(
                vat_rate,
                max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
                field_path="summary.bucket_summaries.key",
            ): _bucket_summary_to_dict(bucket)
            for vat_rate, bucket in summary.bucket_summaries.items()
        },
        "invoice_net_total": _encode_money(
            summary.invoice_net_total, "summary.invoice_net_total"
        ),
        "invoice_vat_total": _encode_money(
            summary.invoice_vat_total, "summary.invoice_vat_total"
        ),
        "invoice_gross_total": _encode_money(
            summary.invoice_gross_total, "summary.invoice_gross_total"
        ),
    }


def summary_to_json(summary: DomesticVatInvoiceSummary) -> str:
    """Encode one invoice summary into a deterministic frozen JSON string."""

    return json.dumps(
        summary_to_dict(summary),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def summary_from_dict(data: Any) -> DomesticVatInvoiceSummary:
    """Decode one invoice summary from the frozen JSON-ready dict form."""

    _require_object(data, "summary")
    _require_schema_version(
        data, expected=SUMMARY_JSON_SCHEMA_VERSION, payload_name="summary"
    )
    _reject_unknown_keys(data, _SUMMARY_KEYS, "summary")
    _require_keys(data, _SUMMARY_REQUIRED_KEYS, "summary")

    line_computations_raw = data["line_computations"]
    if not isinstance(line_computations_raw, list):
        raise DomesticVatJsonError(
            "summary.line_computations must be a JSON array"
        )

    bucket_summaries_raw = data["bucket_summaries"]
    if not isinstance(bucket_summaries_raw, dict):
        raise DomesticVatJsonError(
            "summary.bucket_summaries must be a JSON object"
        )

    bucket_summaries: dict[Decimal, DomesticVatBucketSummary] = {}
    for key, value in bucket_summaries_raw.items():
        key_path = f"summary.bucket_summaries[{key!r}]"
        try:
            vat_rate = Decimal(key)
        except InvalidOperation as exc:
            raise DomesticVatJsonError(
                f"{key_path} key is not a valid decimal"
            ) from exc
        _assert_fraction_digits(
            vat_rate,
            max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
            field_path=f"{key_path} key",
        )
        bucket_summaries[vat_rate] = _bucket_summary_from_dict(
            value, vat_rate=vat_rate, path=key_path
        )

    return DomesticVatInvoiceSummary(
        line_computations=[
            _line_computation_from_dict(
                item, path=f"summary.line_computations[{index}]"
            )
            for index, item in enumerate(line_computations_raw)
        ],
        bucket_summaries=bucket_summaries,
        invoice_net_total=_decode_money(
            data["invoice_net_total"], "summary.invoice_net_total"
        ),
        invoice_vat_total=_decode_money(
            data["invoice_vat_total"], "summary.invoice_vat_total"
        ),
        invoice_gross_total=_decode_money(
            data["invoice_gross_total"], "summary.invoice_gross_total"
        ),
    )


def summary_from_json(text: str) -> DomesticVatInvoiceSummary:
    """Decode one invoice summary from a frozen JSON string."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DomesticVatJsonError(f"invalid JSON: {exc}") from exc
    return summary_from_dict(data)


# --- Nested encoders (shell) ---------------------------------------------


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
    _set_if_present(data, "bank_account", party.bank_account)
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
        data["quantity"] = _encode_decimal(
            item.quantity,
            max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
            field_path=f"{path}.quantity",
        )
    if item.unit_price_net is not None:
        data["unit_price_net"] = _encode_decimal(
            item.unit_price_net,
            max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
            field_path=f"{path}.unit_price_net",
        )
    if item.vat_rate is not None:
        data["vat_rate"] = _encode_decimal(
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


# --- Nested encoders (summary) -------------------------------------------


def _line_computation_to_dict(
    lc: DomesticVatLineComputation,
) -> dict[str, Any]:
    """Encode one computed line into the frozen dict form."""

    path = f"summary.line_computations[{lc.line_index}]"
    return {
        "line_index": lc.line_index,
        "description": lc.description,
        "quantity": _encode_decimal(
            lc.quantity,
            max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
            field_path=f"{path}.quantity",
        ),
        "unit_price_net": _encode_decimal(
            lc.unit_price_net,
            max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
            field_path=f"{path}.unit_price_net",
        ),
        "vat_rate": _encode_decimal(
            lc.vat_rate,
            max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
            field_path=f"{path}.vat_rate",
        ),
        "line_net_total": _encode_money(
            lc.line_net_total, f"{path}.line_net_total"
        ),
        "line_vat_total": _encode_money(
            lc.line_vat_total, f"{path}.line_vat_total"
        ),
        "line_gross_total": _encode_money(
            lc.line_gross_total, f"{path}.line_gross_total"
        ),
    }


def _bucket_summary_to_dict(
    bucket: DomesticVatBucketSummary,
) -> dict[str, Any]:
    """Encode one VAT bucket summary, with vat_rate carried by the key."""

    return {
        "net_total": _encode_money(bucket.net_total, "bucket.net_total"),
        "vat_total": _encode_money(bucket.vat_total, "bucket.vat_total"),
        "gross_total": _encode_money(bucket.gross_total, "bucket.gross_total"),
    }


# --- Nested decoders (shell) ---------------------------------------------


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
        bank_account=_decode_optional_str(
            data.get("bank_account"), f"{path}.bank_account"
        ),
    )


def _buyer_from_dict(data: Any, *, path: str) -> BuyerShell:
    """Decode one BuyerShell from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _BUYER_KEYS, path)
    _require_keys(data, _BUYER_REQUIRED_KEYS, path)

    try:
        buyer_id_mode = BuyerIdMode(data["buyer_id_mode"])
    except ValueError as exc:
        raise DomesticVatJsonError(
            f"invalid {path}.buyer_id_mode: {exc}"
        ) from exc

    jst = data["jst"]
    gv = data["gv"]
    if not isinstance(jst, int) or isinstance(jst, bool):
        raise DomesticVatJsonError(f"{path}.jst must be an integer")
    if not isinstance(gv, int) or isinstance(gv, bool):
        raise DomesticVatJsonError(f"{path}.gv must be an integer")

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
        bank_account=_decode_optional_str(
            data.get("bank_account"), f"{path}.bank_account"
        ),
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
            raise DomesticVatJsonError(f"{path}.{int_field} must be an integer")
    for str_field in (
        "exemption_mode",
        "new_transport_mode",
        "margin_mode",
    ):
        if not isinstance(data[str_field], str):
            raise DomesticVatJsonError(f"{path}.{str_field} must be a string")

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


# --- Nested decoders (summary) -------------------------------------------


def _line_computation_from_dict(
    data: Any, *, path: str
) -> DomesticVatLineComputation:
    """Decode one computed line from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _LINE_COMPUTATION_KEYS, path)
    _require_keys(data, _LINE_COMPUTATION_KEYS, path)

    line_index = data["line_index"]
    if not isinstance(line_index, int) or isinstance(line_index, bool):
        raise DomesticVatJsonError(f"{path}.line_index must be an integer")

    description = data["description"]
    if not isinstance(description, str):
        raise DomesticVatJsonError(f"{path}.description must be a string")

    quantity = _decode_required_decimal(
        data["quantity"],
        f"{path}.quantity",
        max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
    )
    unit_price_net = _decode_required_decimal(
        data["unit_price_net"],
        f"{path}.unit_price_net",
        max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
    )
    vat_rate = _decode_required_decimal(
        data["vat_rate"],
        f"{path}.vat_rate",
        max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
    )

    return DomesticVatLineComputation(
        line_index=line_index,
        description=description,
        quantity=quantity,
        unit_price_net=unit_price_net,
        vat_rate=vat_rate,
        line_net_total=_decode_money(
            data["line_net_total"], f"{path}.line_net_total"
        ),
        line_vat_total=_decode_money(
            data["line_vat_total"], f"{path}.line_vat_total"
        ),
        line_gross_total=_decode_money(
            data["line_gross_total"], f"{path}.line_gross_total"
        ),
    )


def _bucket_summary_from_dict(
    data: Any, *, vat_rate: Decimal, path: str
) -> DomesticVatBucketSummary:
    """Decode one VAT bucket summary from its frozen dict form."""

    _require_object(data, path)
    _reject_unknown_keys(data, _BUCKET_SUMMARY_KEYS, path)
    _require_keys(data, _BUCKET_SUMMARY_KEYS, path)

    return DomesticVatBucketSummary(
        vat_rate=vat_rate,
        net_total=_decode_money(data["net_total"], f"{path}.net_total"),
        vat_total=_decode_money(data["vat_total"], f"{path}.vat_total"),
        gross_total=_decode_money(data["gross_total"], f"{path}.gross_total"),
    )


# --- Primitive helpers ----------------------------------------------------


def _set_if_present(data: dict[str, Any], key: str, value: Any) -> None:
    """Assign ``value`` under ``key`` only when the value is not ``None``."""

    if value is not None:
        data[key] = value


def _require_object(data: Any, path: str) -> None:
    """Raise ``DomesticVatJsonError`` unless ``data`` is a JSON object."""

    if not isinstance(data, dict):
        raise DomesticVatJsonError(f"{path} payload must be a JSON object")


def _reject_unknown_keys(
    data: dict[str, Any],
    allowed: frozenset[str],
    path: str,
) -> None:
    """Raise if ``data`` carries any key outside ``allowed``."""

    extra = sorted(key for key in data if key not in allowed)
    if extra:
        raise DomesticVatJsonError(f"{path} payload has unknown keys: {extra}")


def _require_keys(
    data: dict[str, Any],
    required: frozenset[str],
    path: str,
) -> None:
    """Raise if any ``required`` key is absent from ``data``."""

    missing = sorted(required - data.keys())
    if missing:
        raise DomesticVatJsonError(
            f"{path} payload is missing required keys: {missing}"
        )


def _require_schema_version(
    data: dict[str, Any],
    *,
    expected: int,
    payload_name: str,
) -> None:
    """Enforce that ``data`` declares the expected frozen schema version."""

    if "schema_version" not in data:
        raise DomesticVatJsonError(
            f"{payload_name} payload is missing 'schema_version'"
        )
    version = data["schema_version"]
    if version != expected:
        raise DomesticVatJsonError(
            f"{payload_name} payload schema_version {version!r} does not "
            f"match expected {expected}"
        )


def _encode_decimal(
    value: Decimal,
    *,
    max_fraction_digits: int,
    field_path: str,
) -> str:
    """Format one Decimal via ``format_decimal``, wrapping errors with path."""

    try:
        return format_decimal(value, max_fraction_digits=max_fraction_digits)
    except ValueError as exc:
        raise DomesticVatJsonError(f"{field_path}: {exc}") from exc


def _encode_money(value: Decimal, field_path: str) -> str:
    """Format one Decimal via ``format_money``, wrapping errors with path."""

    try:
        return format_money(value)
    except ValueError as exc:
        raise DomesticVatJsonError(f"{field_path}: {exc}") from exc


def _decode_optional_str(value: Any, path: str) -> str | None:
    """Decode one optional string, rejecting non-string non-``None`` input."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise DomesticVatJsonError(f"{path} must be a string")
    return value


def _decode_optional_int(value: Any, path: str) -> int | None:
    """Decode one optional integer, rejecting bools and non-int input."""

    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise DomesticVatJsonError(f"{path} must be an integer")
    return value


def _decode_date(value: Any, path: str) -> date | None:
    """Decode one optional ISO ``YYYY-MM-DD`` date string into a ``date``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise DomesticVatJsonError(f"{path} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomesticVatJsonError(f"invalid {path}: {exc}") from exc


def _decode_decimal(
    value: Any,
    path: str,
    *,
    max_fraction_digits: int,
) -> Decimal | None:
    """Decode one optional decimal string, enforcing finiteness and precision."""

    if value is None:
        return None
    return _decode_required_decimal(
        value, path, max_fraction_digits=max_fraction_digits
    )


def _decode_required_decimal(
    value: Any,
    path: str,
    *,
    max_fraction_digits: int,
) -> Decimal:
    """Decode one required decimal string, enforcing finiteness and precision."""

    if not isinstance(value, str):
        raise DomesticVatJsonError(f"{path} must be a plain decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise DomesticVatJsonError(f"invalid {path}: {exc}") from exc
    _assert_fraction_digits(
        parsed,
        max_fraction_digits=max_fraction_digits,
        field_path=path,
    )
    return parsed


def _decode_money(value: Any, path: str) -> Decimal:
    """Decode one money string, enforcing canonical two-decimal form."""

    if not isinstance(value, str):
        raise DomesticVatJsonError(f"{path} must be a money string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise DomesticVatJsonError(f"invalid {path}: {exc}") from exc
    try:
        canonical = format_money(parsed)
    except ValueError as exc:
        raise DomesticVatJsonError(f"{path}: {exc}") from exc
    if canonical != value:
        raise DomesticVatJsonError(
            f"{path} must be in canonical money form: "
            f"got {value!r}, expected {canonical!r}"
        )
    return parsed


def _assert_fraction_digits(
    value: Decimal,
    *,
    max_fraction_digits: int,
    field_path: str,
) -> None:
    """Raise if ``value`` violates the finiteness or precision contract."""

    try:
        format_decimal(value, max_fraction_digits=max_fraction_digits)
    except ValueError as exc:
        raise DomesticVatJsonError(f"{field_path}: {exc}") from exc
