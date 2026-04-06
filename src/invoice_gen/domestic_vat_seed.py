"""Structured synthetic seed objects for the domestic VAT MVP profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
import random

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_PARTY_NAMES = (
    "ABC AGD sp. z o.o.",
    "FHU Jan Kowalski",
    "Meblotronik sp. z o.o.",
    "Biuro Handlowe Sigma sp. z o.o.",
    "Zaklad Uslug Technicznych Delta",
    "Sklep Domowy Komfort sp. z o.o.",
)
_STREET_NAMES = (
    "Kwiatowa",
    "Polna",
    "Lesna",
    "Lipowa",
    "Slowicza",
    "Ogrodowa",
)
_CITIES = (
    ("Warszawa", "00-001"),
    ("Krakow", "30-002"),
    ("Gdansk", "80-001"),
    ("Poznan", "60-101"),
    ("Wroclaw", "50-001"),
    ("Lodz", "90-001"),
)
_LINE_ITEM_TEMPLATES = (
    ("lodowka Zimnotech mk1", "szt.", Decimal("23")),
    ("wniesienie sprzetu", "szt.", Decimal("23")),
    ("pralka HydroMax 3000", "szt.", Decimal("23")),
    ("przeglad instalacji", "usl.", Decimal("23")),
    ("ksiazka kucharska", "szt.", Decimal("5")),
    ("promocja produktowa", "szt.", Decimal("5")),
)
_REFERENCE_START_DATE = date(2026, 1, 1)
_REFERENCE_DAY_COUNT = 365


@dataclass(kw_only=True)
class DomesticVatPartySeed:
    """Structured seller or buyer data for one domestic VAT sample."""

    nip: str
    name: str
    address_line_1: str
    address_line_2: str


@dataclass(kw_only=True)
class DomesticVatLineItemSeed:
    """Structured commercial line-item data for one domestic VAT sample."""

    description: str
    unit: str
    quantity: Decimal
    unit_price_net: Decimal
    vat_rate: Decimal


@dataclass(kw_only=True)
class DomesticVatInvoiceSeed:
    """Structured domestic VAT invoice seed generated before shell mapping."""

    currency: str
    issue_date: date
    sale_date: date
    invoice_number: str
    issue_city: str
    seller: DomesticVatPartySeed
    buyer: DomesticVatPartySeed
    line_items: list[DomesticVatLineItemSeed] = field(default_factory=list)


def build_domestic_vat_seed(seed: int | None = None) -> DomesticVatInvoiceSeed:
    """Build one structured domestic VAT seed with deterministic randomness."""

    rng = random.Random(seed)
    issue_date = _build_issue_date(rng)
    sale_date = _build_sale_date(rng, issue_date)
    issue_city, _postal_code = rng.choice(_CITIES)
    seller, buyer = _build_parties(rng)

    return DomesticVatInvoiceSeed(
        currency="PLN",
        issue_date=issue_date,
        sale_date=sale_date,
        invoice_number=_build_invoice_number(rng, issue_date),
        issue_city=issue_city,
        seller=seller,
        buyer=buyer,
        line_items=_build_line_items(rng),
    )


def _build_issue_date(rng: random.Random) -> date:
    """Generate a deterministic issue date within the reference sample year."""

    return _REFERENCE_START_DATE + timedelta(
        days=rng.randrange(_REFERENCE_DAY_COUNT)
    )


def _build_sale_date(rng: random.Random, issue_date: date) -> date:
    """Generate a sale date that never falls after the issue date."""

    days_before_issue = rng.randint(0, 14)
    sale_date = issue_date - timedelta(days=days_before_issue)
    return max(sale_date, _REFERENCE_START_DATE)


def _build_parties(
    rng: random.Random,
) -> tuple[DomesticVatPartySeed, DomesticVatPartySeed]:
    """Generate distinct seller and buyer parties with legal-formatted fields."""

    seller_name, buyer_name = rng.sample(_PARTY_NAMES, k=2)
    seller_address, buyer_address = _build_address(rng), _build_address(rng)
    seller_nip = _build_nip(rng)
    buyer_nip = _build_nip(rng)

    while buyer_address == seller_address:
        buyer_address = _build_address(rng)

    while buyer_nip == seller_nip:
        buyer_nip = _build_nip(rng)

    return (
        DomesticVatPartySeed(
            nip=seller_nip,
            name=seller_name,
            address_line_1=seller_address[0],
            address_line_2=seller_address[1],
        ),
        DomesticVatPartySeed(
            nip=buyer_nip,
            name=buyer_name,
            address_line_1=buyer_address[0],
            address_line_2=buyer_address[1],
        ),
    )


def _build_address(rng: random.Random) -> tuple[str, str]:
    """Generate address lines in the broad shape used by the official samples."""

    street_name = rng.choice(_STREET_NAMES)
    building_number = rng.randint(1, 99)
    apartment_number = rng.choice((None, rng.randint(1, 20)))
    city, postal_code = rng.choice(_CITIES)
    address_line_1 = f"ul. {street_name} {building_number}"

    if apartment_number is not None:
        address_line_1 = f"{address_line_1} m. {apartment_number}"

    return address_line_1, f"{postal_code} {city}"


def _build_line_items(rng: random.Random) -> list[DomesticVatLineItemSeed]:
    """Generate one to three domestic VAT line items with allowed tax rates."""

    line_count = rng.randint(1, 3)
    selected_templates = rng.sample(_LINE_ITEM_TEMPLATES, k=line_count)

    return [
        DomesticVatLineItemSeed(
            description=description,
            unit=unit,
            quantity=Decimal(str(rng.randint(1, 5))),
            unit_price_net=_build_unit_price_net(rng),
            vat_rate=vat_rate,
        )
        for description, unit, vat_rate in selected_templates
    ]


def _build_unit_price_net(rng: random.Random) -> Decimal:
    """Generate a positive net unit price with two decimal places."""

    grosze = rng.randint(500, 250_000)
    return (Decimal(grosze) / Decimal("100")).quantize(Decimal("0.01"))


def _build_invoice_number(rng: random.Random, issue_date: date) -> str:
    """Generate invoice numbers in the fixed domestic style used in this MVP."""

    sequence = rng.randint(1, 999)
    return f"FV{issue_date.year}/{issue_date.month:02d}/{sequence:03d}"


def _build_nip(rng: random.Random) -> str:
    """Generate a checksum-valid, ten-digit NIP."""

    while True:
        prefix_digits = [str(rng.randint(0, 9)) for _ in range(9)]
        checksum = (
            sum(
                int(digit) * weight
                for digit, weight in zip(
                    prefix_digits, _NIP_WEIGHTS, strict=True
                )
            )
            % 11
        )

        if checksum == 10:
            continue

        return "".join(prefix_digits) + str(checksum)
