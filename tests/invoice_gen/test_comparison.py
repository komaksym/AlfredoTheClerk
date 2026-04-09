"""Tests for the comparison policy and shell/summary comparators."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.invoice_gen.comparison import (
    COMPARISON_POLICY_SCHEMA_VERSION,
    ComparisonError,
    ComparisonMode,
    ComparisonPolicy,
    FieldRule,
    Mismatch,
    build_default_comparison_policy,
    compare_shells,
    compare_summaries,
    policy_from_dict,
    policy_from_json,
    policy_to_dict,
    policy_to_json,
)
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
from src.invoice_gen.domestic_vat_shell_summary import (
    summarize_domestic_vat_shell,
)


# --- helpers --------------------------------------------------------------


def _shell_from_seed(seed: int) -> DomesticVatInvoiceShell:
    """Build one fully populated canonical shell from a deterministic seed."""

    return map_domestic_vat_seed_to_shell(build_domestic_vat_seed(seed))


def _populated_shell() -> DomesticVatInvoiceShell:
    """Build one hand-rolled shell with simple deterministic values."""

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
            address_line_1="ul. Sprzedawcy 1",
            address_line_2="00-001 Warszawa",
            phone="+48 123 456 789",
        ),
        buyer=BuyerShell(
            nip="9876543210",
            name="Buyer sp. z o.o.",
            address_line_1="ul. Klienta 2",
            address_line_2="00-002 Warszawa",
            phone="+48 987 654 321",
            buyer_id_mode=BuyerIdMode.DOMESTIC_NIP,
            jst=2,
            gv=2,
        ),
        line_items=[
            LineItemShell(
                description="Service A",
                unit="szt",
                quantity=Decimal("1"),
                unit_price_net=Decimal("100"),
                vat_rate=Decimal("23"),
            ),
            LineItemShell(
                description="Service B",
                unit="szt",
                quantity=Decimal("2"),
                unit_price_net=Decimal("50"),
                vat_rate=Decimal("5"),
            ),
        ],
        adnotations=AdnotationDefaults(),
    )


# --- FieldRule construction ----------------------------------------------


def test_normalized_rule_requires_a_normalizer_name() -> None:
    """A normalized rule with no normalizer must be rejected at build time."""

    with pytest.raises(ComparisonError, match="normalized rule requires"):
        FieldRule(mode=ComparisonMode.NORMALIZED)


def test_exact_rule_must_not_carry_a_normalizer_name() -> None:
    """An exact rule that carries a normalizer name must be rejected."""

    with pytest.raises(ComparisonError, match="exact rule must not"):
        FieldRule(mode=ComparisonMode.EXACT, normalizer="text")


# --- Policy lookup --------------------------------------------------------


def test_policy_returns_none_for_unknown_path() -> None:
    """An unknown field path is implicitly not_scored."""

    policy = ComparisonPolicy(fields={})
    assert policy.rule_for("anything.at.all") is None


def test_policy_wildcard_lookup_collapses_indexed_segments() -> None:
    """A ``[*]`` rule must match any concrete index in that segment."""

    policy = ComparisonPolicy(
        fields={
            "shell.line_items[*].quantity": FieldRule(
                mode=ComparisonMode.EXACT
            ),
        }
    )

    rule = policy.rule_for("shell.line_items[7].quantity")
    assert rule is not None
    assert rule.mode is ComparisonMode.EXACT


def test_policy_wildcard_lookup_handles_dict_keys() -> None:
    """A ``[*]`` rule must also match string-key dict segments."""

    policy = ComparisonPolicy(
        fields={
            "summary.bucket_summaries[*].net_total": FieldRule(
                mode=ComparisonMode.NORMALIZED, normalizer="money"
            ),
        }
    )

    rule = policy.rule_for("summary.bucket_summaries[23].net_total")
    assert rule is not None
    assert rule.normalizer == "money"


def test_policy_literal_path_takes_precedence_over_wildcard() -> None:
    """A literal entry must win over the wildcard fallback."""

    policy = ComparisonPolicy(
        fields={
            "shell.line_items[*].quantity": FieldRule(
                mode=ComparisonMode.EXACT
            ),
            "shell.line_items[0].quantity": FieldRule(
                mode=ComparisonMode.NORMALIZED, normalizer="money"
            ),
        }
    )

    rule = policy.rule_for("shell.line_items[0].quantity")
    assert rule is not None
    assert rule.mode is ComparisonMode.NORMALIZED


# --- compare_shells: matching paths --------------------------------------


def test_compare_shell_against_itself_is_a_match() -> None:
    """A shell compared to itself must produce zero mismatches."""

    shell = _populated_shell()
    policy = build_default_comparison_policy()

    report = compare_shells(shell, shell, policy)

    assert report.is_match
    assert report.mismatches == []


def test_compare_seed_shell_against_itself_is_a_match() -> None:
    """The default policy must hold over a fully synthetic seeded shell."""

    shell = _shell_from_seed(7)
    policy = build_default_comparison_policy()

    report = compare_shells(shell, shell, policy)

    assert report.is_match


# --- compare_shells: exact mismatch detection ----------------------------


def test_compare_shells_detects_exact_currency_mismatch() -> None:
    """A different currency must surface as one EXACT mismatch."""

    truth = _populated_shell()
    candidate = replace(truth, currency="EUR")
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    assert not report.is_match
    paths = {m.path for m in report.mismatches}
    assert "shell.currency" in paths
    [currency_mismatch] = [
        m for m in report.mismatches if m.path == "shell.currency"
    ]
    assert currency_mismatch.mode is ComparisonMode.EXACT
    assert currency_mismatch.expected == "PLN"
    assert currency_mismatch.actual == "EUR"


def test_compare_shells_detects_date_mismatch() -> None:
    """A different issue_date must surface as one EXACT mismatch."""

    truth = _populated_shell()
    candidate = replace(truth, issue_date=date(2027, 1, 1))
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    [date_mismatch] = [
        m for m in report.mismatches if m.path == "shell.issue_date"
    ]
    assert date_mismatch.expected == "2026-04-08"
    assert date_mismatch.actual == "2027-01-01"


# --- compare_shells: normalized matches and mismatches ------------------


def test_normalized_nip_collapses_punctuation() -> None:
    """A formatted NIP must compare equal to a digit-only NIP."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    object.__setattr__(
        candidate.seller, "nip", "123-456-78-90"
    )  # PartyShell is not frozen, but be defensive
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    assert report.is_match


def test_normalized_text_collapses_whitespace() -> None:
    """An issue_city differing only by whitespace must still match."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.issue_city = "  Warszawa\t\n"
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    assert report.is_match


def test_normalized_invoice_number_strips_whitespace() -> None:
    """An invoice number differing only by spaces must match."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.invoice_number = "FV2026 / 04 / 001"
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    assert report.is_match


def test_normalized_nip_mismatch_reports_canonical_form() -> None:
    """A genuinely different NIP must surface with normalized values."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.seller.nip = "0000000000"
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    [nip_mismatch] = [
        m for m in report.mismatches if m.path == "shell.seller.nip"
    ]
    assert nip_mismatch.mode is ComparisonMode.NORMALIZED
    assert nip_mismatch.expected == "1234567890"
    assert nip_mismatch.actual == "0000000000"


# --- compare_shells: line items -----------------------------------------


def test_line_count_mismatch_short_circuits_per_line_walk() -> None:
    """When line counts differ, no per-line mismatches must be reported."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.line_items.pop()
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    paths = [m.path for m in report.mismatches]
    assert paths == ["shell.line_items.count"]
    [count_mismatch] = report.mismatches
    assert count_mismatch.expected == "2"
    assert count_mismatch.actual == "1"


def test_per_line_description_mismatch_uses_indexed_path() -> None:
    """A description mismatch on row 1 must report ``[1]`` in its path."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.line_items[1].description = "Totally different service"
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    paths = {m.path for m in report.mismatches}
    assert "shell.line_items[1].description" in paths
    assert "shell.line_items[0].description" not in paths


# --- compare_shells: not_scored fields ----------------------------------


def test_unscored_fields_never_produce_mismatches() -> None:
    """Editing a field absent from the policy must not surface mismatches."""

    truth = _populated_shell()
    candidate = deepcopy(truth)
    candidate.system_info = "anything goes here"
    candidate.seller.email = "different@example.com"
    candidate.seller.krs = "0000000000"
    policy = build_default_comparison_policy()

    report = compare_shells(truth, candidate, policy)

    assert report.is_match


# --- compare_summaries --------------------------------------------------


def test_compare_summary_against_itself_is_a_match() -> None:
    """A summary compared to itself must produce zero mismatches."""

    shell = _shell_from_seed(7)
    summary = summarize_domestic_vat_shell(shell)
    policy = build_default_comparison_policy()

    report = compare_summaries(summary, summary, policy)

    assert report.is_match


def test_summary_money_normalization_treats_value_equal_decimals() -> None:
    """A candidate built from value-equal Decimals must still match."""

    shell = _shell_from_seed(7)
    truth = summarize_domestic_vat_shell(shell)
    # Re-quantize each total to a different exponent so the underlying
    # Decimal tuples differ even though the rounded money strings agree.
    candidate = replace(
        truth,
        invoice_net_total=truth.invoice_net_total + Decimal("0.000"),
        invoice_vat_total=truth.invoice_vat_total + Decimal("0.000"),
        invoice_gross_total=truth.invoice_gross_total + Decimal("0.000"),
    )
    policy = build_default_comparison_policy()

    report = compare_summaries(truth, candidate, policy)

    assert report.is_match


def test_summary_bucket_count_and_keyed_paths() -> None:
    """Removing one bucket must surface count + missing-key mismatches."""

    # seed 0 deterministically produces both 23% and 5% buckets.
    shell = _shell_from_seed(0)
    truth = summarize_domestic_vat_shell(shell)
    assert len(truth.bucket_summaries) >= 2
    candidate_buckets = dict(truth.bucket_summaries)
    removed_key = sorted(candidate_buckets.keys())[0]
    candidate_buckets.pop(removed_key)
    candidate = replace(truth, bucket_summaries=candidate_buckets)
    policy = build_default_comparison_policy()

    report = compare_summaries(truth, candidate, policy)

    paths = {m.path for m in report.mismatches}
    assert "summary.bucket_summaries.count" in paths
    assert f"summary.bucket_summaries[{removed_key}]" in paths


# --- Policy JSON round-trip ---------------------------------------------


def test_default_policy_round_trips_through_json() -> None:
    """The default policy must survive a ``to_json -> from_json`` cycle."""

    original = build_default_comparison_policy()
    text = policy_to_json(original)
    decoded = policy_from_json(text)

    assert dict(decoded.fields) == dict(original.fields)


def test_policy_to_json_is_deterministic() -> None:
    """Two encodings of the same policy must be byte-identical."""

    policy = build_default_comparison_policy()
    assert policy_to_json(policy) == policy_to_json(policy)


def test_policy_from_dict_rejects_unknown_schema_version() -> None:
    """Bumping the schema version must raise on decode."""

    payload = policy_to_dict(build_default_comparison_policy())
    payload["schema_version"] = COMPARISON_POLICY_SCHEMA_VERSION + 1

    with pytest.raises(ComparisonError, match="schema_version"):
        policy_from_dict(payload)


def test_policy_from_dict_rejects_unknown_keys() -> None:
    """An extra top-level key in the payload must raise."""

    payload = policy_to_dict(build_default_comparison_policy())
    payload["extra"] = "nope"

    with pytest.raises(ComparisonError, match="unknown keys"):
        policy_from_dict(payload)


def test_policy_from_dict_rejects_unknown_normalizer() -> None:
    """A normalized rule referencing an unknown normalizer must raise."""

    payload = {
        "schema_version": COMPARISON_POLICY_SCHEMA_VERSION,
        "fields": {
            "shell.invoice_number": {
                "mode": "normalized",
                "normalizer": "made_up_normalizer",
            },
        },
    }

    with pytest.raises(ComparisonError, match="unknown normalizer"):
        policy_from_dict(payload)


def test_policy_from_dict_rejects_unknown_mode() -> None:
    """An unknown ``mode`` value must raise."""

    payload = {
        "schema_version": COMPARISON_POLICY_SCHEMA_VERSION,
        "fields": {
            "shell.invoice_number": {"mode": "fuzzy"},
        },
    }

    with pytest.raises(ComparisonError, match="unknown mode"):
        policy_from_dict(payload)


def test_policy_from_dict_rejects_normalized_rule_without_normalizer() -> None:
    """A normalized rule with no normalizer field must raise."""

    payload = {
        "schema_version": COMPARISON_POLICY_SCHEMA_VERSION,
        "fields": {
            "shell.invoice_number": {"mode": "normalized"},
        },
    }

    with pytest.raises(ComparisonError, match="unknown normalizer"):
        policy_from_dict(payload)


def test_policy_from_json_rejects_invalid_json() -> None:
    """Malformed JSON must raise a ComparisonError, not JSONDecodeError."""

    with pytest.raises(ComparisonError, match="invalid JSON"):
        policy_from_json("not json {")


def test_policy_to_json_emits_sorted_keys_and_no_not_scored_entries() -> None:
    """The encoded policy must be sorted and contain only scored fields."""

    text = policy_to_json(build_default_comparison_policy())
    decoded = json.loads(text)

    assert decoded["schema_version"] == COMPARISON_POLICY_SCHEMA_VERSION
    field_paths = list(decoded["fields"].keys())
    assert field_paths == sorted(field_paths)
    for rule in decoded["fields"].values():
        assert rule["mode"] in {"exact", "normalized"}


# --- ComparisonReport ----------------------------------------------------


def test_empty_report_is_match() -> None:
    """An empty mismatch list must mark the report as a match."""

    from src.invoice_gen.comparison import ComparisonReport

    report = ComparisonReport(mismatches=[])
    assert report.is_match


def test_non_empty_report_is_not_match() -> None:
    """Any mismatch must flip the report to non-match."""

    from src.invoice_gen.comparison import ComparisonReport

    report = ComparisonReport(
        mismatches=[
            Mismatch(
                path="shell.currency",
                mode=ComparisonMode.EXACT,
                expected="PLN",
                actual="EUR",
            )
        ]
    )
    assert not report.is_match
