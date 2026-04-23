"""Tests for the curated M4 hard-case corpus."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.invoice_gen.benchmark_case import (
    XsdValidationResult,
    build_benchmark_case_from_shell,
    load_benchmark_case,
)
from src.invoice_gen.domain_shell import LineItemShell, build_domestic_vat_shell
from src.invoice_gen.hard_case_corpus import (
    HARD_CASE_PDF_FILENAME,
    HARD_CASES_ROOT,
    HardCaseCorpusError,
    iter_hard_case_fixtures,
    load_hard_case_fixture,
    regenerate_hard_case_corpus,
    save_hard_case_fixture,
)


_FIXED_GENERATED_AT = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
_EXPECTED_CASE_IDS = [
    "long_parties_v1",
    "nearby_dates_v1",
    "punctuation_identifiers_v1",
    "seller_buyer_confusion_v1",
    "totals_near_rows_v1",
    "wrapped_description_v1",
]


def _stub_validator_valid(_xml: str) -> XsdValidationResult:
    return XsdValidationResult(is_valid=True, error=None)


def _reference_shell():
    shell = build_domestic_vat_shell()
    shell.invoice_number = "FV/CASE/001"
    shell.issue_date = date(2026, 4, 23)
    shell.sale_date = date(2026, 4, 22)
    shell.issue_city = "Warszawa"
    shell.payment_form = 6
    shell.payment_due_date = date(2026, 5, 7)
    shell.seller.name = "Alfa Sp. z o.o."
    shell.seller.nip = "8637940261"
    shell.seller.address_line_1 = "ul. Polna 29"
    shell.seller.address_line_2 = "90-001 Lodz"
    shell.seller.bank_account = "PL61419283276483503056413953"
    shell.buyer.name = "Beta Sp. z o.o."
    shell.buyer.nip = "5423511615"
    shell.buyer.address_line_1 = "ul. Ogrodowa 70 m. 3"
    shell.buyer.address_line_2 = "00-001 Warszawa"
    shell.line_items = [
        LineItemShell(
            description="Pakiet serwisowy",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("250.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell


def test_build_benchmark_case_from_shell_is_deterministic() -> None:
    case_a = build_benchmark_case_from_shell(
        case_id="case-0001",
        shell=_reference_shell(),
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    case_b = build_benchmark_case_from_shell(
        case_id="case-0001",
        shell=_reference_shell(),
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    assert case_a.target_xml == case_b.target_xml
    assert case_a.summary == case_b.summary
    assert case_a.shell == case_b.shell
    assert case_a.xsd_validation == case_b.xsd_validation


def test_save_hard_case_fixture_writes_pinned_pdf(tmp_path: Path) -> None:
    case = build_benchmark_case_from_shell(
        case_id="case-0001",
        shell=_reference_shell(),
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    directory = tmp_path / "case-0001"
    save_hard_case_fixture(case, b"%PDF-1.4\n", directory)

    fixture = load_hard_case_fixture("case-0001", root=tmp_path)

    assert fixture.pdf_path == directory / HARD_CASE_PDF_FILENAME
    assert fixture.pdf_path.read_bytes() == b"%PDF-1.4\n"
    assert fixture.case == case


def test_load_hard_case_fixture_rejects_missing_pdf_companion(
    tmp_path: Path,
) -> None:
    case = build_benchmark_case_from_shell(
        case_id="case-0001",
        shell=_reference_shell(),
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    directory = tmp_path / "case-0001"
    directory.mkdir()
    from src.invoice_gen.benchmark_case import save_benchmark_case

    save_benchmark_case(case, directory)

    with pytest.raises(HardCaseCorpusError, match=HARD_CASE_PDF_FILENAME):
        load_hard_case_fixture("case-0001", root=tmp_path)


def test_iter_hard_case_fixtures_returns_sorted_directory_names(
    tmp_path: Path,
) -> None:
    case = build_benchmark_case_from_shell(
        case_id="shared",
        shell=_reference_shell(),
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    save_hard_case_fixture(case, b"%PDF-1.4\n", tmp_path / "z-case")
    save_hard_case_fixture(case, b"%PDF-1.4\n", tmp_path / "a-case")

    assert [
        fixture.directory.name
        for fixture in iter_hard_case_fixtures(root=tmp_path)
    ] == [
        "a-case",
        "z-case",
    ]


def test_regenerate_hard_case_corpus_round_trips_cases(tmp_path: Path) -> None:
    fixtures = regenerate_hard_case_corpus(_stub_validator_valid, root=tmp_path)

    assert [fixture.case_id for fixture in fixtures] == _EXPECTED_CASE_IDS
    for fixture in fixtures:
        assert fixture.pdf_path.name == HARD_CASE_PDF_FILENAME
        assert fixture.pdf_path.is_file()
        assert load_benchmark_case(fixture.directory) == fixture.case


def test_checked_in_hard_case_corpus_is_complete() -> None:
    fixtures = iter_hard_case_fixtures(root=HARD_CASES_ROOT)

    assert [fixture.case_id for fixture in fixtures] == _EXPECTED_CASE_IDS
    for fixture in fixtures:
        assert fixture.pdf_path.name == HARD_CASE_PDF_FILENAME
        assert fixture.pdf_path.is_file()
