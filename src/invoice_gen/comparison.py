"""Comparison policy and shell/summary comparators for benchmark cases.

This module owns the M1 scoring contract for the domestic VAT pipeline.
A :class:`ComparisonPolicy` enumerates the field paths that should be
scored and the rule for each one (``EXACT`` or ``NORMALIZED``). Field
paths absent from the policy are silently skipped: that is the
roadmap's "not scored" category.

The two public comparators, :func:`compare_shells` and
:func:`compare_summaries`, walk the canonical shell and derived summary
explicitly (no reflection) and emit a :class:`ComparisonReport` listing
every mismatch found.

Wildcards: list and dict members use ``[*]`` in policy paths. The
lookup substitutes any concrete ``[<index>]`` or ``[<key>]`` segment
with ``[*]`` before falling back, so a single rule covers every
position. The wildcard syntax is intentionally minimal and matches one
indexed segment at a time.

Any breaking change to the policy JSON encoding must bump
``COMPARISON_POLICY_SCHEMA_VERSION``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from src.invoice_gen.domain_shell import (
    AdnotationDefaults,
    BuyerShell,
    DomesticVatInvoiceShell,
    LineItemShell,
    PartyShell,
)
from src.invoice_gen.domestic_vat_money import format_money
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
    DomesticVatLineComputation,
)


COMPARISON_POLICY_SCHEMA_VERSION = 1


class ComparisonError(Exception):
    """One error raised while building or applying a ComparisonPolicy."""


class ComparisonMode(Enum):
    """Supported comparison modes for one scored field."""

    EXACT = "exact"
    NORMALIZED = "normalized"


@dataclass(frozen=True, kw_only=True)
class FieldRule:
    """Comparison rule for one field path."""

    mode: ComparisonMode
    normalizer: str | None = None

    def __post_init__(self) -> None:
        """Enforce that normalizer presence matches the rule mode."""

        if self.mode is ComparisonMode.NORMALIZED:
            if self.normalizer is None:
                raise ComparisonError(
                    "normalized rule requires a normalizer name"
                )
        elif self.normalizer is not None:
            raise ComparisonError("exact rule must not carry a normalizer name")


@dataclass(frozen=True, kw_only=True)
class ComparisonPolicy:
    """Frozen field-path → rule mapping for shell and summary scoring."""

    fields: Mapping[str, FieldRule]

    def rule_for(self, path: str) -> FieldRule | None:
        """Return the rule for ``path`` or ``None`` if it is not scored.

        Lookup tries the literal path first, then a wildcard form built
        by replacing every ``[<index>]`` or ``[<key>]`` segment with
        ``[*]``.
        """

        rule = self.fields.get(path)
        if rule is not None:
            return rule
        wildcarded = _WILDCARD_PATTERN.sub("[*]", path)
        if wildcarded != path:
            return self.fields.get(wildcarded)
        return None


@dataclass(frozen=True, kw_only=True)
class Mismatch:
    """One scored field whose values disagreed under its rule."""

    path: str
    mode: ComparisonMode
    expected: str
    actual: str


@dataclass(frozen=True, kw_only=True)
class ComparisonReport:
    """Structured outcome of one shell or summary comparison."""

    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def is_match(self) -> bool:
        """``True`` when no scored field reported a mismatch."""

        return not self.mismatches


# --- Normalizer registry --------------------------------------------------


def _normalize_text(value: Any) -> str | None:
    """Collapse internal whitespace and strip ends; ``None`` stays None."""

    if value is None:
        return None
    return " ".join(str(value).split())


def _normalize_nip(value: Any) -> str | None:
    """Strip every non-digit character so formatted NIPs match."""

    if value is None:
        return None
    return "".join(ch for ch in str(value) if ch.isdigit())


def _normalize_phone(value: Any) -> str | None:
    """Strip every non-digit character; ``+`` and spacing are dropped."""

    if value is None:
        return None
    return "".join(ch for ch in str(value) if ch.isdigit())


def _normalize_invoice_number(value: Any) -> str | None:
    """Strip all whitespace from invoice numbers; case is preserved."""

    if value is None:
        return None
    return "".join(str(value).split())


def _normalize_money(value: Any) -> str | None:
    """Render any money value as the canonical two-decimal string form."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return format_money(value)
    return str(value).strip()


_NORMALIZERS: Mapping[str, Callable[[Any], Any]] = {
    "text": _normalize_text,
    "nip": _normalize_nip,
    "phone": _normalize_phone,
    "invoice_number": _normalize_invoice_number,
    "money": _normalize_money,
}


# --- Default policy -------------------------------------------------------


def build_default_comparison_policy() -> ComparisonPolicy:
    """Return the M1 default policy for domestic VAT shell + summary.

    Reflects ROADMAP.md section 3:
    * exact:      dates, currency, VAT rates, line count
    * normalized: invoice number, NIP, phone, money, whitespace text
    * not scored: anything not listed (defaults via ``rule_for``)
    """

    rules: dict[str, FieldRule] = {}

    def _exact(path: str) -> None:
        rules[path] = FieldRule(mode=ComparisonMode.EXACT)

    def _norm(path: str, normalizer: str) -> None:
        rules[path] = FieldRule(
            mode=ComparisonMode.NORMALIZED, normalizer=normalizer
        )

    # --- shell header ---
    _exact("shell.profile")
    _exact("shell.currency")
    _exact("shell.issue_date")
    _exact("shell.sale_date")
    _norm("shell.invoice_number", "invoice_number")
    _norm("shell.issue_city", "text")
    # shell.system_info: not scored (metadata)
    # shell.payment_form: not scored until template visibility (M2+)

    # --- seller / buyer ---
    for party in ("seller", "buyer"):
        _norm(f"shell.{party}.nip", "nip")
        _norm(f"shell.{party}.name", "text")
        _norm(f"shell.{party}.address_line_1", "text")
        _norm(f"shell.{party}.address_line_2", "text")
        _norm(f"shell.{party}.phone", "text")
        # email / krs / regon / bdo: not scored (no canonicalizer yet)

    # --- buyer-only structural fields ---
    _exact("shell.buyer.buyer_id_mode")
    _exact("shell.buyer.jst")
    _exact("shell.buyer.gv")
    # shell.buyer.customer_ref: not scored (metadata)

    # --- line items ---
    _exact("shell.line_items.count")
    _norm("shell.line_items[*].description", "text")
    _norm("shell.line_items[*].unit", "text")
    _exact("shell.line_items[*].quantity")
    _exact("shell.line_items[*].unit_price_net")
    _exact("shell.line_items[*].vat_rate")

    # --- adnotations (fixed flag block) ---
    for flag in (
        "cash_method_flag",
        "self_billing_flag",
        "reverse_charge_flag",
        "split_payment_flag",
        "special_procedure_flag",
    ):
        _exact(f"shell.adnotations.{flag}")
    for word in ("exemption_mode", "new_transport_mode", "margin_mode"):
        _exact(f"shell.adnotations.{word}")

    # --- summary invoice totals ---
    _norm("summary.invoice_net_total", "money")
    _norm("summary.invoice_vat_total", "money")
    _norm("summary.invoice_gross_total", "money")

    # --- summary line computations ---
    _exact("summary.line_computations.count")
    _exact("summary.line_computations[*].line_index")
    _norm("summary.line_computations[*].description", "text")
    _exact("summary.line_computations[*].quantity")
    _exact("summary.line_computations[*].unit_price_net")
    _exact("summary.line_computations[*].vat_rate")
    _norm("summary.line_computations[*].line_net_total", "money")
    _norm("summary.line_computations[*].line_vat_total", "money")
    _norm("summary.line_computations[*].line_gross_total", "money")

    # --- summary bucket summaries ---
    _exact("summary.bucket_summaries.count")
    _exact("summary.bucket_summaries[*].vat_rate")
    _norm("summary.bucket_summaries[*].net_total", "money")
    _norm("summary.bucket_summaries[*].vat_total", "money")
    _norm("summary.bucket_summaries[*].gross_total", "money")

    return ComparisonPolicy(fields=rules)


# --- Public comparators ---------------------------------------------------


def compare_shells(
    truth: DomesticVatInvoiceShell,
    candidate: DomesticVatInvoiceShell,
    policy: ComparisonPolicy,
) -> ComparisonReport:
    """Compare one candidate shell against the canonical truth shell."""

    mismatches: list[Mismatch] = []
    _walk_shell(truth, candidate, policy, mismatches)
    return ComparisonReport(mismatches=mismatches)


def compare_summaries(
    truth: DomesticVatInvoiceSummary,
    candidate: DomesticVatInvoiceSummary,
    policy: ComparisonPolicy,
) -> ComparisonReport:
    """Compare one candidate summary against the canonical truth one."""

    mismatches: list[Mismatch] = []
    _walk_summary(truth, candidate, policy, mismatches)
    return ComparisonReport(mismatches=mismatches)


# --- Shell walkers --------------------------------------------------------


def _walk_shell(
    truth: DomesticVatInvoiceShell,
    candidate: DomesticVatInvoiceShell,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every scored field on the shell and record any mismatches."""

    for attr in (
        "profile",
        "currency",
        "issue_date",
        "sale_date",
        "invoice_number",
        "issue_city",
        "system_info",
        "payment_form",
    ):
        _check_field(
            f"shell.{attr}",
            getattr(truth, attr),
            getattr(candidate, attr),
            policy,
            mismatches,
        )

    _walk_party(
        "shell.seller", truth.seller, candidate.seller, policy, mismatches
    )
    _walk_buyer("shell.buyer", truth.buyer, candidate.buyer, policy, mismatches)
    _walk_line_items(
        "shell.line_items",
        truth.line_items,
        candidate.line_items,
        policy,
        mismatches,
    )
    _walk_adnotations(
        "shell.adnotations",
        truth.adnotations,
        candidate.adnotations,
        policy,
        mismatches,
    )


def _walk_party(
    base: str,
    truth: PartyShell,
    candidate: PartyShell,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every party (seller/buyer base) field."""

    for attr in (
        "nip",
        "name",
        "address_line_1",
        "address_line_2",
        "email",
        "phone",
        "krs",
        "regon",
        "bdo",
    ):
        _check_field(
            f"{base}.{attr}",
            getattr(truth, attr),
            getattr(candidate, attr),
            policy,
            mismatches,
        )


def _walk_buyer(
    base: str,
    truth: BuyerShell,
    candidate: BuyerShell,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk the buyer-specific fields on top of the party walk."""

    _walk_party(base, truth, candidate, policy, mismatches)
    for attr in ("buyer_id_mode", "jst", "gv", "customer_ref"):
        _check_field(
            f"{base}.{attr}",
            getattr(truth, attr),
            getattr(candidate, attr),
            policy,
            mismatches,
        )


def _walk_line_items(
    base: str,
    truth_lines: list[LineItemShell],
    candidate_lines: list[LineItemShell],
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every line item by position; line count is its own field."""

    truth_count = len(truth_lines)
    candidate_count = len(candidate_lines)
    _check_field(
        f"{base}.count",
        truth_count,
        candidate_count,
        policy,
        mismatches,
    )
    if truth_count != candidate_count:
        return
    for index, (truth_item, candidate_item) in enumerate(
        zip(truth_lines, candidate_lines, strict=False)
    ):
        item_base = f"{base}[{index}]"
        for attr in (
            "description",
            "unit",
            "quantity",
            "unit_price_net",
            "vat_rate",
        ):
            _check_field(
                f"{item_base}.{attr}",
                getattr(truth_item, attr),
                getattr(candidate_item, attr),
                policy,
                mismatches,
            )


def _walk_adnotations(
    base: str,
    truth: AdnotationDefaults,
    candidate: AdnotationDefaults,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every adnotations flag and mode field."""

    for attr in (
        "cash_method_flag",
        "self_billing_flag",
        "reverse_charge_flag",
        "split_payment_flag",
        "special_procedure_flag",
        "exemption_mode",
        "new_transport_mode",
        "margin_mode",
    ):
        _check_field(
            f"{base}.{attr}",
            getattr(truth, attr),
            getattr(candidate, attr),
            policy,
            mismatches,
        )


# --- Summary walkers ------------------------------------------------------


def _walk_summary(
    truth: DomesticVatInvoiceSummary,
    candidate: DomesticVatInvoiceSummary,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every scored field on the summary and record any mismatches."""

    for attr in (
        "invoice_net_total",
        "invoice_vat_total",
        "invoice_gross_total",
    ):
        _check_field(
            f"summary.{attr}",
            getattr(truth, attr),
            getattr(candidate, attr),
            policy,
            mismatches,
        )

    _walk_line_computations(
        "summary.line_computations",
        truth.line_computations,
        candidate.line_computations,
        policy,
        mismatches,
    )
    _walk_bucket_summaries(
        "summary.bucket_summaries",
        truth.bucket_summaries,
        candidate.bucket_summaries,
        policy,
        mismatches,
    )


def _walk_line_computations(
    base: str,
    truth_lines: list[DomesticVatLineComputation],
    candidate_lines: list[DomesticVatLineComputation],
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every computed line; line count is its own field."""

    truth_count = len(truth_lines)
    candidate_count = len(candidate_lines)
    _check_field(
        f"{base}.count",
        truth_count,
        candidate_count,
        policy,
        mismatches,
    )
    if truth_count != candidate_count:
        return
    for index, (truth_item, candidate_item) in enumerate(
        zip(truth_lines, candidate_lines, strict=False)
    ):
        item_base = f"{base}[{index}]"
        for attr in (
            "line_index",
            "description",
            "quantity",
            "unit_price_net",
            "vat_rate",
            "line_net_total",
            "line_vat_total",
            "line_gross_total",
        ):
            _check_field(
                f"{item_base}.{attr}",
                getattr(truth_item, attr),
                getattr(candidate_item, attr),
                policy,
                mismatches,
            )


def _walk_bucket_summaries(
    base: str,
    truth_buckets: dict[Decimal, DomesticVatBucketSummary],
    candidate_buckets: dict[Decimal, DomesticVatBucketSummary],
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Walk every VAT bucket; bucket count is its own field."""

    truth_count = len(truth_buckets)
    candidate_count = len(candidate_buckets)
    _check_field(
        f"{base}.count",
        truth_count,
        candidate_count,
        policy,
        mismatches,
    )

    truth_keys = set(truth_buckets.keys())
    candidate_keys = set(candidate_buckets.keys())
    only_in_truth = sorted(truth_keys - candidate_keys)
    only_in_candidate = sorted(candidate_keys - truth_keys)
    for missing_key in only_in_truth:
        mismatches.append(
            Mismatch(
                path=f"{base}[{missing_key}]",
                mode=ComparisonMode.EXACT,
                expected="present",
                actual="missing",
            )
        )
    for extra_key in only_in_candidate:
        mismatches.append(
            Mismatch(
                path=f"{base}[{extra_key}]",
                mode=ComparisonMode.EXACT,
                expected="missing",
                actual="present",
            )
        )

    for key in sorted(truth_keys & candidate_keys):
        bucket_base = f"{base}[{key}]"
        truth_bucket = truth_buckets[key]
        candidate_bucket = candidate_buckets[key]
        for attr in ("vat_rate", "net_total", "vat_total", "gross_total"):
            _check_field(
                f"{bucket_base}.{attr}",
                getattr(truth_bucket, attr),
                getattr(candidate_bucket, attr),
                policy,
                mismatches,
            )


# --- Field comparison primitive ------------------------------------------


def _check_field(
    path: str,
    truth: Any,
    candidate: Any,
    policy: ComparisonPolicy,
    mismatches: list[Mismatch],
) -> None:
    """Apply the policy rule for ``path`` and record any mismatch."""

    rule = policy.rule_for(path)
    if rule is None:
        return

    if rule.mode is ComparisonMode.EXACT:
        if truth != candidate:
            mismatches.append(
                Mismatch(
                    path=path,
                    mode=rule.mode,
                    expected=_canonical_str(truth),
                    actual=_canonical_str(candidate),
                )
            )
        return

    # NORMALIZED
    assert rule.normalizer is not None  # enforced by FieldRule.__post_init__
    normalizer = _NORMALIZERS.get(rule.normalizer)
    if normalizer is None:
        raise ComparisonError(
            f"unknown normalizer at {path}: {rule.normalizer!r}"
        )
    norm_truth = normalizer(truth)
    norm_candidate = normalizer(candidate)
    if norm_truth != norm_candidate:
        mismatches.append(
            Mismatch(
                path=path,
                mode=rule.mode,
                expected=_canonical_str(norm_truth),
                actual=_canonical_str(norm_candidate),
            )
        )


def _canonical_str(value: Any) -> str:
    """Render any value as a stable string for mismatch reporting."""

    if value is None:
        return "null"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Decimal, int, float, bool)):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


_WILDCARD_PATTERN = re.compile(r"\[[^\]]+\]")


# --- JSON encoding --------------------------------------------------------


_POLICY_KEYS = frozenset({"schema_version", "fields"})
_FIELD_RULE_KEYS = frozenset({"mode", "normalizer"})
_FIELD_RULE_REQUIRED_KEYS = frozenset({"mode"})


def policy_to_dict(policy: ComparisonPolicy) -> dict[str, Any]:
    """Encode one comparison policy as a JSON-ready dict."""

    return {
        "schema_version": COMPARISON_POLICY_SCHEMA_VERSION,
        "fields": {
            path: _field_rule_to_dict(rule)
            for path, rule in sorted(policy.fields.items())
        },
    }


def policy_to_json(policy: ComparisonPolicy) -> str:
    """Encode one comparison policy as a deterministic JSON string."""

    return json.dumps(
        policy_to_dict(policy),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def policy_from_dict(data: Any) -> ComparisonPolicy:
    """Decode one comparison policy from its JSON-ready dict form."""

    if not isinstance(data, dict):
        raise ComparisonError("policy payload must be a JSON object")

    extra = sorted(key for key in data if key not in _POLICY_KEYS)
    if extra:
        raise ComparisonError(f"policy payload has unknown keys: {extra}")
    missing = sorted(_POLICY_KEYS - data.keys())
    if missing:
        raise ComparisonError(
            f"policy payload is missing required keys: {missing}"
        )

    schema_version = data["schema_version"]
    if schema_version != COMPARISON_POLICY_SCHEMA_VERSION:
        raise ComparisonError(
            f"unsupported policy schema_version: {schema_version!r}"
        )

    fields_raw = data["fields"]
    if not isinstance(fields_raw, dict):
        raise ComparisonError("policy.fields must be a JSON object")

    fields: dict[str, FieldRule] = {}
    for path, rule_data in fields_raw.items():
        if not isinstance(path, str) or not path:
            raise ComparisonError(
                f"policy.fields key must be a non-empty string, got {path!r}"
            )
        fields[path] = _field_rule_from_dict(rule_data, path=path)

    return ComparisonPolicy(fields=fields)


def policy_from_json(text: str) -> ComparisonPolicy:
    """Decode one comparison policy from its JSON string form."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"invalid JSON: {exc}") from exc
    return policy_from_dict(data)


def _field_rule_to_dict(rule: FieldRule) -> dict[str, Any]:
    """Encode one ``FieldRule`` as a JSON-ready dict."""

    payload: dict[str, Any] = {"mode": rule.mode.value}
    if rule.normalizer is not None:
        payload["normalizer"] = rule.normalizer
    return payload


def _field_rule_from_dict(data: Any, *, path: str) -> FieldRule:
    """Decode one ``FieldRule`` from its JSON-ready dict form."""

    if not isinstance(data, dict):
        raise ComparisonError(f"policy.fields[{path!r}] must be a JSON object")
    extra = sorted(key for key in data if key not in _FIELD_RULE_KEYS)
    if extra:
        raise ComparisonError(
            f"policy.fields[{path!r}] has unknown keys: {extra}"
        )
    missing = sorted(_FIELD_RULE_REQUIRED_KEYS - data.keys())
    if missing:
        raise ComparisonError(
            f"policy.fields[{path!r}] missing required keys: {missing}"
        )

    mode_raw = data["mode"]
    try:
        mode = ComparisonMode(mode_raw)
    except ValueError as exc:
        raise ComparisonError(
            f"policy.fields[{path!r}] has unknown mode: {mode_raw!r}"
        ) from exc

    normalizer = data.get("normalizer")
    if normalizer is not None and not isinstance(normalizer, str):
        raise ComparisonError(
            f"policy.fields[{path!r}].normalizer must be a string"
        )

    if mode is ComparisonMode.NORMALIZED and normalizer not in _NORMALIZERS:
        raise ComparisonError(
            f"policy.fields[{path!r}] uses unknown normalizer: {normalizer!r}"
        )

    return FieldRule(mode=mode, normalizer=normalizer)
