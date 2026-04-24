"""Curated hard-case corpus utilities for the M4 robustness milestone."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from src.invoice_gen.benchmark_case import (
    BenchmarkCase,
    XsdValidationResult,
    build_benchmark_case_from_shell,
    load_benchmark_case,
    save_benchmark_case,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell, LineItemShell
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.macos_dyld import (
    relaunch_module_with_homebrew_dyld_if_needed,
)
from src.invoice_gen.pdf_rendering import SELLER_BUYER_TEMPLATE_ID
from src.invoice_gen.template_registry import TEMPLATE_REGISTRY


ROOT_DIR = Path(__file__).resolve().parents[2]
HARD_CASES_ROOT = ROOT_DIR / "data" / "benchmark_cases" / "hard_cases"

# v1 stays the canonical "default" hard-case template for callers that
# haven't migrated to per-template iteration. ``pdf_paths`` on the
# fixture below carries one entry per registered template.
HARD_CASE_TEMPLATE_ID = SELLER_BUYER_TEMPLATE_ID
HARD_CASE_PDF_FILENAME = f"{HARD_CASE_TEMPLATE_ID}.pdf"

_SCHEMA_DIR = ROOT_DIR / "data" / "schemas"
_SCHEMA_FILES = (
    "schemat.xsd",
    "StrukturyDanych_v10-0E.xsd",
    "ElementarneTypyDanych_v10-0E.xsd",
    "KodyKrajow_v10-0E.xsd",
)
_SCHEMA_LOCATION_REWRITES = {
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/StrukturyDanych_v10-0E.xsd"
    ): "StrukturyDanych_v10-0E.xsd",
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/ElementarneTypyDanych_v10-0E.xsd"
    ): "ElementarneTypyDanych_v10-0E.xsd",
    (
        "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/"
        "DefinicjeTypy/KodyKrajow_v10-0E.xsd"
    ): "KodyKrajow_v10-0E.xsd",
}

_FIXED_GENERATED_AT = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)

_SEED_42 = build_domestic_vat_seed(42)
_VALID_SELLER_NIP = _SEED_42.seller.nip
_VALID_BUYER_NIP = _SEED_42.buyer.nip
_VALID_BANK_ACCOUNT = _SEED_42.seller.bank_account


class HardCaseCorpusError(Exception):
    """Raised when the curated hard-case corpus is missing or malformed."""


@dataclass(frozen=True, kw_only=True)
class HardCaseFixture:
    """One persisted hard case plus its pinned rendered PDF artifacts.

    ``pdf_paths`` maps each registered ``template_id`` to its pinned
    PDF on disk. ``pdf_path`` is a convenience shortcut pointing at
    the v1 template's PDF so existing callers keep working.
    """

    case_id: str
    directory: Path
    pdf_path: Path
    pdf_paths: dict[str, Path]
    case: BenchmarkCase


def load_hard_case_fixture(
    case_id: str, *, root: Path = HARD_CASES_ROOT
) -> HardCaseFixture:
    """Load one curated hard-case fixture from disk."""

    directory = root / case_id
    case = load_benchmark_case(directory)

    pdf_paths: dict[str, Path] = {}
    for template_id in TEMPLATE_REGISTRY:
        pdf_path = directory / f"{template_id}.pdf"
        if not pdf_path.is_file():
            raise HardCaseCorpusError(
                f"missing {template_id}.pdf in hard case {directory}"
            )
        pdf_paths[template_id] = pdf_path

    return HardCaseFixture(
        case_id=case_id,
        directory=directory,
        pdf_path=pdf_paths[HARD_CASE_TEMPLATE_ID],
        pdf_paths=pdf_paths,
        case=case,
    )


def iter_hard_case_fixtures(
    *, root: Path = HARD_CASES_ROOT
) -> list[HardCaseFixture]:
    """Return every curated hard case, ordered by directory name."""

    if not root.is_dir():
        raise HardCaseCorpusError(f"missing hard-case corpus root {root}")

    fixtures: list[HardCaseFixture] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        fixtures.append(load_hard_case_fixture(directory.name, root=root))
    return fixtures


def save_hard_case_fixture(
    case: BenchmarkCase,
    pdfs: dict[str, bytes],
    directory: Path,
) -> None:
    """Persist one hard case's benchmark bundle plus pinned PDFs.

    ``pdfs`` maps each registered ``template_id`` to its rendered
    bytes. The file on disk is named ``<template_id>.pdf`` so
    per-template artifacts stay side by side inside the case directory.
    """

    save_benchmark_case(case, directory)
    for template_id, pdf_bytes in pdfs.items():
        (directory / f"{template_id}.pdf").write_bytes(pdf_bytes)


def regenerate_hard_case_corpus(
    xsd_validator, *, root: Path = HARD_CASES_ROOT
) -> list[HardCaseFixture]:
    """Rebuild the entire curated hard-case corpus under ``root``."""

    root.mkdir(parents=True, exist_ok=True)

    for case_id, builder in _CASE_BUILDERS.items():
        shell, generated_at = builder()
        case = build_benchmark_case_from_shell(
            case_id=case_id,
            shell=shell,
            generated_at=generated_at,
            xsd_validator=xsd_validator,
        )
        pdfs = {
            template_id: spec.renderer(shell)
            for template_id, spec in TEMPLATE_REGISTRY.items()
        }
        directory = root / case_id
        save_hard_case_fixture(case, pdfs, directory)

    return iter_hard_case_fixtures(root=root)


def validate_xml_against_local_schema_bundle(xml: str) -> XsdValidationResult:
    """Validate one FA(3) XML payload with the checked-in local XSD bundle."""

    xmllint_path = shutil.which("xmllint")
    if xmllint_path is None:
        raise HardCaseCorpusError(
            "xmllint is required to regenerate hard-case corpus artifacts"
        )

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        schema_path = _build_local_schema_bundle(tmp_dir)
        xml_path = tmp_dir / "candidate.xml"
        xml_path.write_text(xml, encoding="utf-8")

        result = subprocess.run(
            [
                xmllint_path,
                "--nonet",
                "--noout",
                "--schema",
                str(schema_path),
                str(xml_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode == 0:
        return XsdValidationResult(is_valid=True, error=None)

    error_output = result.stderr.strip() or result.stdout.strip()
    first_error_line = error_output.splitlines()[0] if error_output else ""
    return XsdValidationResult(is_valid=False, error=first_error_line or None)


def _build_local_schema_bundle(tmp_path: Path) -> Path:
    """Copy the checked-in schemas and rewrite their dependency paths."""

    bundle_dir = tmp_path / "schema-bundle"
    bundle_dir.mkdir()

    for schema_name in _SCHEMA_FILES:
        source_path = _SCHEMA_DIR / schema_name
        target_path = bundle_dir / schema_name
        text = source_path.read_text(encoding="utf-8")

        for old, new in _SCHEMA_LOCATION_REWRITES.items():
            text = text.replace(old, new)

        target_path.write_text(text, encoding="utf-8")

    return bundle_dir / "schemat.xsd"


def _blank_shell(invoice_number: str) -> DomesticVatInvoiceShell:
    """Return one fully populated baseline shell for curated hard cases."""

    from src.invoice_gen.domain_shell import build_domestic_vat_shell

    shell = build_domestic_vat_shell()
    shell.invoice_number = invoice_number
    shell.issue_date = date(2026, 4, 23)
    shell.sale_date = date(2026, 4, 22)
    shell.issue_city = "Warszawa"
    shell.payment_form = 6
    shell.payment_due_date = date(2026, 5, 7)

    shell.seller.name = "Alfa Instalacje i Serwis Sp. z o.o."
    shell.seller.nip = _VALID_SELLER_NIP
    shell.seller.address_line_1 = "ul. Polna 29"
    shell.seller.address_line_2 = "90-001 Lodz"
    shell.seller.bank_account = _VALID_BANK_ACCOUNT

    shell.buyer.name = "Beta Handel i Wyposazenie Sp. z o.o."
    shell.buyer.nip = _VALID_BUYER_NIP
    shell.buyer.address_line_1 = "ul. Ogrodowa 70 m. 3"
    shell.buyer.address_line_2 = "00-001 Warszawa"

    return shell


def _wrapped_description_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FVW/26/001")
    shell.line_items = [
        LineItemShell(
            description=(
                "Kompleksowa usluga serwisowa obejmujaca przeglad okresowy, "
                "dojazd technika, wymiane materialow eksploatacyjnych oraz "
                "sporzadzenie rozszerzonego protokolu odbioru prac"
            ),
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("1234.56"),
            discount=Decimal("12.34"),
            vat_rate=Decimal("23"),
        )
    ]
    return shell, _FIXED_GENERATED_AT


def _long_parties_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FVL/26/002")
    shell.seller.name = (
        "Przedsiebiorstwo Instalacyjno Serwisowe Alfa Beta Gamma Delta "
        "Sp. z o.o."
    )
    shell.seller.address_line_1 = (
        "ul. Bardzo Dluga Ulica Serwisowa i Magazynowa 123 lokal 45A"
    )
    shell.seller.address_line_2 = "00-123 Warszawa Mokotow woj. mazowieckie"
    shell.buyer.name = (
        "Przedsiebiorstwo Instalacyjno Serwisowe Alfa Beta Gamma Delta "
        "Bis Sp. z o.o."
    )
    shell.buyer.address_line_1 = (
        "al. Wyjatkowo Rozbudowana Aleja Handlowa 987 budynek C"
    )
    shell.buyer.address_line_2 = "31-234 Krakow Nowa Huta woj. malopolskie"
    shell.line_items = [
        LineItemShell(
            description="Pakiet serwisowy premium",
            unit="kpl.",
            quantity=Decimal("2"),
            unit_price_net=Decimal("499.99"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell, _FIXED_GENERATED_AT


def _seller_buyer_confusion_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FVP/26/003")
    shell.seller.name = "Alfa Instalacje Serwis Sp. z o.o."
    shell.seller.address_line_1 = "ul. Wspolna 10 bud. A"
    shell.seller.address_line_2 = "00-950 Warszawa"
    shell.buyer.name = "Alfa Instalacje Serwis Bis Sp. z o.o."
    shell.buyer.address_line_1 = "ul. Wspolna 10A bud. B"
    shell.buyer.address_line_2 = "00-951 Warszawa"
    shell.line_items = [
        LineItemShell(
            description="Kontrola instalacji",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("800.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell, _FIXED_GENERATED_AT


def _nearby_dates_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FVD/26/004")
    shell.issue_date = date(2026, 5, 20)
    shell.sale_date = date(2026, 5, 19)
    shell.payment_due_date = date(2026, 5, 21)
    shell.issue_city = "Poznan"
    shell.line_items = [
        LineItemShell(
            description="Abonament serwisowy maj 2026",
            unit="mies.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("250.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell, _FIXED_GENERATED_AT


def _totals_near_rows_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FVT/26/005")
    shell.line_items = [
        LineItemShell(
            description="Diagnostyka systemu",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("99.99"),
            discount=None,
            vat_rate=Decimal("23"),
        ),
        LineItemShell(
            description="Kalibracja ukladu",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("100.01"),
            discount=None,
            vat_rate=Decimal("23"),
        ),
    ]
    return shell, _FIXED_GENERATED_AT


def _punctuation_identifiers_case() -> tuple[DomesticVatInvoiceShell, datetime]:
    shell = _blank_shell("FV/26-A.17")
    shell.seller.name = "A.B.C. Serwis Sp. z o.o."
    shell.seller.address_line_1 = "al. Jana Pawla II 10/7, kl. B"
    shell.seller.address_line_2 = "01-234 Warszawa"
    shell.buyer.name = "M.D.K.-Trade Sp. z o.o."
    shell.buyer.address_line_1 = "ul. 3 Maja 4/5, lok. 8"
    shell.buyer.address_line_2 = "40-096 Katowice"
    shell.line_items = [
        LineItemShell(
            description="Przeglad A/B-C, etap 1.",
            unit="usl.",
            quantity=Decimal("1"),
            unit_price_net=Decimal("321.00"),
            discount=None,
            vat_rate=Decimal("23"),
        )
    ]
    return shell, _FIXED_GENERATED_AT


_CASE_BUILDERS = {
    "wrapped_description_v1": _wrapped_description_case,
    "long_parties_v1": _long_parties_case,
    "seller_buyer_confusion_v1": _seller_buyer_confusion_case,
    "nearby_dates_v1": _nearby_dates_case,
    "totals_near_rows_v1": _totals_near_rows_case,
    "punctuation_identifiers_v1": _punctuation_identifiers_case,
}


def main() -> None:
    """Regenerate the checked-in hard-case corpus under ``data/``."""

    relaunch_module_with_homebrew_dyld_if_needed(
        "src.invoice_gen.hard_case_corpus"
    )

    parser = argparse.ArgumentParser(
        description="Regenerate curated M4 hard-case benchmark artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=HARD_CASES_ROOT,
        help=(
            "Directory to write the hard-case corpus "
            "(default: data/benchmark_cases/hard_cases)."
        ),
    )
    args = parser.parse_args()

    fixtures = regenerate_hard_case_corpus(
        validate_xml_against_local_schema_bundle,
        root=args.root,
    )
    for fixture in fixtures:
        print(f"{fixture.case_id}: {fixture.directory}")


if __name__ == "__main__":
    main()
