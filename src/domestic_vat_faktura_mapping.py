"""Map validated domestic VAT shell data into the FA(3) schema model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ksef_schema.elementarne_typy_danych_v10_0_e import Twybor1, Twybor12
from ksef_schema.schemat import (
    Faktura,
    Podmiot2Gv,
    Podmiot2Jst,
    Tadres,
    TkodFormularza,
    TkodKraju,
    TkodWaluty,
    Tnaglowek,
    TnaglowekWariantFormularza,
    Tpodmiot1,
    Tpodmiot2,
    TrodzajFaktury,
    TstawkaPodatku,
)
from xsdata.models.datatype import XmlDateTime

from src.domestic_vat_money import round_money
from src.domain_shell import DomesticVatInvoiceShell, LineItemShell
from src.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
    DomesticVatLineComputation,
)
from src.domestic_vat_shell_validation import (
    ShellValidationResult,
    validate_domestic_vat_shell,
)

_HUNDRED = Decimal("100")
_VAT_ENUMS = {
    Decimal("23"): TstawkaPodatku.VALUE_23,
    Decimal("5"): TstawkaPodatku.VALUE_5,
}
_BUCKET_FIELDS = {
    Decimal("23"): ("p_13_1", "p_14_1"),
    Decimal("5"): ("p_13_3", "p_14_3"),
}


@dataclass(kw_only=True)
class FakturaMappingError(Exception):
    """Raised when shell-to-schema mapping cannot safely proceed."""

    message: str
    validation_result: ShellValidationResult | None = None

    def __post_init__(self) -> None:
        """Pass the human-readable error message to Exception."""

        super().__init__(self.message)


def map_domestic_vat_shell_to_faktura(
    shell: DomesticVatInvoiceShell,
    summary: DomesticVatInvoiceSummary,
    generated_at: datetime | None = None,
) -> Faktura:
    """Map one validated domestic VAT shell and summary into `Faktura`."""

    validation_result = validate_domestic_vat_shell(shell)

    if not validation_result.is_valid:
        raise FakturaMappingError(
            message="Cannot map an invalid domestic VAT shell",
            validation_result=validation_result,
        )

    _validate_summary_against_shell(shell, summary)

    xml_generated_at = _to_xml_datetime(generated_at)

    return Faktura(
        naglowek=Tnaglowek(
            kod_formularza=Tnaglowek.KodFormularza(
                value=TkodFormularza.FA,
            ),
            wariant_formularza=TnaglowekWariantFormularza.VALUE_3,
            data_wytworzenia_fa=xml_generated_at,
            system_info=shell.system_info,
        ),
        podmiot1=_map_seller(shell),
        podmiot2=_map_buyer(shell),
        fa=_map_fa(shell, summary),
    )


def _map_seller(shell: DomesticVatInvoiceShell) -> Faktura.Podmiot1:
    """Map seller shell data into the seller schema wrapper."""

    assert shell.seller.nip is not None
    assert shell.seller.name is not None
    assert shell.seller.address_line_1 is not None
    assert shell.seller.address_line_2 is not None

    return Faktura.Podmiot1(
        dane_identyfikacyjne=Tpodmiot1(
            nip=shell.seller.nip,
            nazwa=shell.seller.name,
        ),
        adres=Tadres(
            kod_kraju=TkodKraju.PL,
            adres_l1=shell.seller.address_line_1,
            adres_l2=shell.seller.address_line_2,
        ),
    )


def _map_buyer(shell: DomesticVatInvoiceShell) -> Faktura.Podmiot2:
    """Map buyer shell data into the buyer schema wrapper."""

    assert shell.buyer.nip is not None
    assert shell.buyer.name is not None
    assert shell.buyer.address_line_1 is not None
    assert shell.buyer.address_line_2 is not None

    return Faktura.Podmiot2(
        dane_identyfikacyjne=Tpodmiot2(
            nip=shell.buyer.nip,
            nazwa=shell.buyer.name,
        ),
        adres=Tadres(
            kod_kraju=TkodKraju.PL,
            adres_l1=shell.buyer.address_line_1,
            adres_l2=shell.buyer.address_line_2,
        ),
        jst=Podmiot2Jst.VALUE_2,
        gv=Podmiot2Gv.VALUE_2,
    )


def _map_fa(
    shell: DomesticVatInvoiceShell,
    summary: DomesticVatInvoiceSummary,
) -> Faktura.Fa:
    """Map invoice body fields, VAT buckets, and rows into `Faktura.Fa`."""

    assert shell.issue_date is not None
    assert shell.sale_date is not None
    assert shell.issue_city is not None
    assert shell.invoice_number is not None

    fa_kwargs: dict[str, object] = {
        "kod_waluty": TkodWaluty.PLN,
        "p_1": shell.issue_date.isoformat(),
        "p_1_m": shell.issue_city,
        "p_2": shell.invoice_number,
        "p_15": _format_money(summary.invoice_gross_total),
        "adnotacje": _map_adnotations(),
        "rodzaj_faktury": TrodzajFaktury.VAT,
        "fa_wiersz": [
            _map_line_item(shell_line, summary_line)
            for shell_line, summary_line in zip(
                shell.line_items,
                summary.line_computations,
                strict=True,
            )
        ],
    }

    if shell.sale_date != shell.issue_date:
        fa_kwargs["p_6"] = shell.sale_date.isoformat()

    for vat_rate, (net_field, vat_field) in _BUCKET_FIELDS.items():
        bucket = summary.bucket_summaries.get(vat_rate)

        if bucket is None:
            continue

        fa_kwargs[net_field] = _format_money(bucket.net_total)
        fa_kwargs[vat_field] = _format_money(bucket.vat_total)

    return Faktura.Fa(**fa_kwargs)


def _map_adnotations() -> Faktura.Fa.Adnotacje:
    """Materialize the fixed negative/default adnotation branch."""

    return Faktura.Fa.Adnotacje(
        p_16=Twybor12.VALUE_2,
        p_17=Twybor12.VALUE_2,
        p_18=Twybor12.VALUE_2,
        p_18_a=Twybor12.VALUE_2,
        zwolnienie=Faktura.Fa.Adnotacje.Zwolnienie(
            p_19_n=Twybor1.VALUE_1,
        ),
        nowe_srodki_transportu=Faktura.Fa.Adnotacje.NoweSrodkiTransportu(
            p_22_n=Twybor1.VALUE_1,
        ),
        p_23=Twybor12.VALUE_2,
        pmarzy=Faktura.Fa.Adnotacje.Pmarzy(
            p_pmarzy_n=Twybor1.VALUE_1,
        ),
    )


def _map_line_item(
    shell_line: LineItemShell,
    summary_line: DomesticVatLineComputation,
) -> Faktura.Fa.FaWiersz:
    """Map one shell line and its summary into one FA(3) row."""

    assert shell_line.description is not None
    assert shell_line.unit is not None
    assert shell_line.quantity is not None
    assert shell_line.unit_price_net is not None

    return Faktura.Fa.FaWiersz(
        nr_wiersza_fa=summary_line.line_index + 1,
        uu_id=f"line-{summary_line.line_index + 1:04d}",
        p_7=shell_line.description,
        p_8_a=shell_line.unit,
        p_8_b=_format_decimal(shell_line.quantity, max_fraction_digits=6),
        p_9_a=_format_decimal(shell_line.unit_price_net, max_fraction_digits=8),
        p_11=_format_money(summary_line.line_net_total),
        p_12=_VAT_ENUMS[summary_line.vat_rate],
    )


def _validate_summary_against_shell(
    shell: DomesticVatInvoiceShell,
    summary: DomesticVatInvoiceSummary,
) -> None:
    """Reject summaries that do not match the shell or each other."""

    if len(summary.line_computations) != len(shell.line_items):
        raise FakturaMappingError(
            message="summary line count must match shell line count",
        )

    expected_buckets: dict[Decimal, tuple[Decimal, Decimal, Decimal]] = {}

    for index, (shell_line, summary_line) in enumerate(
        zip(shell.line_items, summary.line_computations, strict=True)
    ):
        _validate_summary_line(index, shell_line, summary_line)

        existing_bucket = expected_buckets.get(summary_line.vat_rate)

        if existing_bucket is None:
            expected_buckets[summary_line.vat_rate] = (
                summary_line.line_net_total,
                summary_line.line_vat_total,
                summary_line.line_gross_total,
            )
            continue

        net_total, vat_total, gross_total = existing_bucket
        expected_buckets[summary_line.vat_rate] = (
            round_money(net_total + summary_line.line_net_total),
            round_money(vat_total + summary_line.line_vat_total),
            round_money(gross_total + summary_line.line_gross_total),
        )

    if set(summary.bucket_summaries) != set(expected_buckets):
        raise FakturaMappingError(
            message="summary VAT buckets must match line VAT buckets",
        )

    for vat_rate, bucket in summary.bucket_summaries.items():
        if vat_rate not in _BUCKET_FIELDS:
            raise FakturaMappingError(
                message=f"unsupported summary VAT bucket: {vat_rate}",
            )

        expected_net, expected_vat, expected_gross = expected_buckets[vat_rate]

        if (
            bucket.net_total != expected_net
            or bucket.vat_total != expected_vat
            or bucket.gross_total != expected_gross
        ):
            raise FakturaMappingError(
                message=f"inconsistent summary totals for VAT bucket {vat_rate}",
            )

    invoice_net_total = round_money(
        sum(bucket.net_total for bucket in summary.bucket_summaries.values())
    )
    invoice_vat_total = round_money(
        sum(bucket.vat_total for bucket in summary.bucket_summaries.values())
    )
    invoice_gross_total = round_money(
        sum(bucket.gross_total for bucket in summary.bucket_summaries.values())
    )

    if summary.invoice_net_total != invoice_net_total:
        raise FakturaMappingError(
            message="summary invoice net total is inconsistent with VAT buckets",
        )

    if summary.invoice_vat_total != invoice_vat_total:
        raise FakturaMappingError(
            message="summary invoice VAT total is inconsistent with VAT buckets",
        )

    if summary.invoice_gross_total != invoice_gross_total:
        raise FakturaMappingError(
            message="summary invoice gross total is inconsistent with VAT buckets",
        )


def _validate_summary_line(
    index: int,
    shell_line: LineItemShell,
    summary_line: DomesticVatLineComputation,
) -> None:
    """Reject one summary line when it no longer matches its shell line."""

    assert shell_line.description is not None
    assert shell_line.quantity is not None
    assert shell_line.unit_price_net is not None
    assert shell_line.vat_rate is not None

    if summary_line.line_index != index:
        raise FakturaMappingError(
            message=f"summary line index mismatch at row {index}",
        )

    if summary_line.description != shell_line.description:
        raise FakturaMappingError(
            message=f"summary description mismatch at row {index}",
        )

    if summary_line.quantity != shell_line.quantity:
        raise FakturaMappingError(
            message=f"summary quantity mismatch at row {index}",
        )

    if summary_line.unit_price_net != shell_line.unit_price_net:
        raise FakturaMappingError(
            message=f"summary unit price mismatch at row {index}",
        )

    if summary_line.vat_rate != shell_line.vat_rate:
        raise FakturaMappingError(
            message=f"summary VAT rate mismatch at row {index}",
        )

    expected_line_net_total = round_money(
        shell_line.quantity * shell_line.unit_price_net
    )
    expected_line_vat_total = round_money(
        expected_line_net_total * shell_line.vat_rate / _HUNDRED
    )
    expected_line_gross_total = round_money(
        expected_line_net_total + expected_line_vat_total
    )

    if summary_line.line_net_total != expected_line_net_total:
        raise FakturaMappingError(
            message=f"summary line net total mismatch at row {index}",
        )

    if summary_line.line_vat_total != expected_line_vat_total:
        raise FakturaMappingError(
            message=f"summary line VAT total mismatch at row {index}",
        )

    if summary_line.line_gross_total != expected_line_gross_total:
        raise FakturaMappingError(
            message=f"summary line gross total mismatch at row {index}",
        )


def _to_xml_datetime(generated_at: datetime | None) -> XmlDateTime:
    """Convert one aware timestamp to the UTC XML datetime type."""

    resolved_generated_at = generated_at or datetime.now(UTC)

    if (
        resolved_generated_at.tzinfo is None
        or resolved_generated_at.utcoffset() is None
    ):
        raise FakturaMappingError(
            message="generated_at must be timezone-aware",
        )

    return XmlDateTime.from_datetime(resolved_generated_at.astimezone(UTC))


def _format_money(value: Decimal) -> str:
    """Format one money value as a plain two-decimal string."""

    return format(round_money(value), "f")


def _format_decimal(value: Decimal, *, max_fraction_digits: int) -> str:
    """Format one Decimal without scientific notation for schema fields."""

    normalized_value = value.normalize()

    exponent = normalized_value.as_tuple().exponent
    fraction_digits = -exponent if exponent < 0 else 0

    if fraction_digits > max_fraction_digits:
        raise FakturaMappingError(
            message=(
                f"value {value} exceeds the supported {max_fraction_digits} "
                "fraction digits"
            ),
        )

    return format(normalized_value, "f")
