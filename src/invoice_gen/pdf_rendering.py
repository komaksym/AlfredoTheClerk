"""Native-PDF rendering for the first M2 template.

This is the M2 renderer deliverable, extended in M4 slice 1: turn one
canonical shell into a PDF that pdfplumber can extract cleanly. The
template covers the invoice header (number, issue date, sale date,
currency), the seller/buyer two-column block, and a bordered
line-items table plus a bordered VAT-summary table.

Determinism contract (per ROADMAP.md M2 acceptance):

* the **extracted text and bounding boxes** must be identical for
  re-renders of the same shell — byte-identical PDFs are not required
* fonts are pinned to the DejaVu Sans TTFs committed under
  ``templates/fonts/`` and resolved through WeasyPrint's ``base_url``,
  so rendering does not depend on system fonts
* the template id (file stem) is exposed via
  :data:`SELLER_BUYER_TEMPLATE_ID` so the visibility-manifest layer can
  reference it without re-encoding the string

The HTML template lives next to this module under
``templates/seller_buyer_block_v1.html`` and references the pinned
fonts via relative ``@font-face`` URLs.

System dependency: WeasyPrint requires native pango/cairo libraries.
On macOS install with ``brew install pango``; on Debian/Ubuntu CI use
``apt install libpango-1.0-0 libpangoft2-1.0-0``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

from src.invoice_gen.domain_shell import (
    BuyerShell,
    DomesticVatInvoiceShell,
    LineItemShell,
    PartyShell,
)
from src.invoice_gen.domestic_vat_money import format_decimal
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatBucketSummary,
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
from src.invoice_gen.template_visibility import (
    TemplateVisibilityManifest,
    VisibilityStatus,
)


SELLER_BUYER_TEMPLATE_ID = "seller_buyer_block_v1"

# Field paths the seller/buyer block template actually renders. The
# renderer module is the natural owner of this list because the only
# way it can change is by editing the HTML template that lives next
# door. Anything not in this set is implicitly NOT_RENDERED for
# benchmark scoring.
SELLER_BUYER_VISIBLE_PATHS: frozenset[str] = frozenset(
    {
        "shell.invoice_number",
        "shell.issue_date",
        "shell.sale_date",
        "shell.currency",
        "shell.seller.name",
        "shell.seller.nip",
        "shell.seller.address_line_1",
        "shell.seller.address_line_2",
        "shell.buyer.name",
        "shell.buyer.nip",
        "shell.buyer.address_line_1",
        "shell.buyer.address_line_2",
        "shell.line_items.count",
        "shell.line_items[*].description",
        "shell.line_items[*].unit",
        "shell.line_items[*].quantity",
        "shell.line_items[*].unit_price_net",
        "shell.line_items[*].vat_rate",
        "summary.invoice_net_total",
        "summary.invoice_vat_total",
        "summary.invoice_gross_total",
        "summary.bucket_summaries.count",
        "summary.bucket_summaries[*].vat_rate",
        "summary.bucket_summaries[*].net_total",
        "summary.bucket_summaries[*].vat_total",
        "summary.bucket_summaries[*].gross_total",
    }
)

# Fraction-digit caps must match the frozen JSON serialization rules in
# :mod:`src.invoice_gen.domestic_vat_json` so that values rendered into
# the PDF round-trip through extraction back to canonical Decimals.
_QUANTITY_MAX_FRACTION_DIGITS = 6
_UNIT_PRICE_NET_MAX_FRACTION_DIGITS = 8
_VAT_RATE_MAX_FRACTION_DIGITS = 0
_MONEY_MAX_FRACTION_DIGITS = 2

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_PATH = _TEMPLATES_DIR / f"{SELLER_BUYER_TEMPLATE_ID}.html"


def _format_iso_date(value: date | None) -> str:
    """Render a ``date`` as ``YYYY-MM-DD`` regardless of system locale.

    Locale/timezone are pinned at the renderer boundary so that the
    same shell extracts identically on any host: dates use ISO 8601
    and never call ``strftime`` (which honors the C locale).
    """

    return value.isoformat() if value is not None else ""


def _render_line_items_rows(line_items: list[LineItemShell]) -> str:
    """Build the ``<tbody>`` inner HTML for the line-items table.

    Cell formatting mirrors the frozen JSON serialization rules so the
    extractor can round-trip rendered values back to canonical
    Decimals. Empty / ``None`` values render as empty cells; the row
    itself is still emitted so layout stays stable row-by-row for
    downstream extraction.
    """

    rows: list[str] = []
    for index, item in enumerate(line_items, start=1):
        description = escape(item.description or "")
        unit = escape(item.unit or "")
        quantity = (
            format_decimal(
                item.quantity,
                max_fraction_digits=_QUANTITY_MAX_FRACTION_DIGITS,
            )
            if item.quantity is not None
            else ""
        )
        unit_price_net = (
            format_decimal(
                item.unit_price_net,
                max_fraction_digits=_UNIT_PRICE_NET_MAX_FRACTION_DIGITS,
            )
            if item.unit_price_net is not None
            else ""
        )
        vat_rate = (
            format_decimal(
                item.vat_rate,
                max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
            )
            if item.vat_rate is not None
            else ""
        )
        rows.append(
            "      <tr>"
            f'<td class="num">{index}</td>'
            f"<td>{description}</td>"
            f"<td>{unit}</td>"
            f'<td class="num">{quantity}</td>'
            f'<td class="num">{unit_price_net}</td>'
            f'<td class="num">{vat_rate}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def _render_bucket_rows(
    bucket_summaries: dict[Decimal, DomesticVatBucketSummary],
) -> str:
    """Build ``<tr>`` rows for VAT buckets, sorted by rate ascending."""

    rows: list[str] = []
    for vat_rate, bucket in sorted(bucket_summaries.items()):
        vat_rate_text = format_decimal(
            vat_rate,
            max_fraction_digits=_VAT_RATE_MAX_FRACTION_DIGITS,
        )
        net_total_text = format_decimal(
            bucket.net_total,
            max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
        )
        vat_total_text = format_decimal(
            bucket.vat_total,
            max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
        )
        gross_total_text = format_decimal(
            bucket.gross_total,
            max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
        )
        rows.append(
            "      <tr>"
            f'<td class="num">{vat_rate_text}</td>'
            f'<td class="num">{net_total_text}</td>'
            f'<td class="num">{vat_total_text}</td>'
            f'<td class="num">{gross_total_text}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def _render_totals_row(summary: DomesticVatInvoiceSummary) -> str:
    """Build the final ``Razem`` row with invoice grand totals."""

    invoice_net_total = format_decimal(
        summary.invoice_net_total,
        max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
    )
    invoice_vat_total = format_decimal(
        summary.invoice_vat_total,
        max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
    )
    invoice_gross_total = format_decimal(
        summary.invoice_gross_total,
        max_fraction_digits=_MONEY_MAX_FRACTION_DIGITS,
    )
    return (
        "      <tr>"
        "<td>Razem</td>"
        f'<td class="num">{invoice_net_total}</td>'
        f'<td class="num">{invoice_vat_total}</td>'
        f'<td class="num">{invoice_gross_total}</td>'
        "</tr>"
    )


def _summarize_for_rendering(
    shell: DomesticVatInvoiceShell,
) -> DomesticVatInvoiceSummary:
    """Summarize the rendered line items without requiring every shell field.

    The VAT summary table is pure line-item math. Rendering should still
    tolerate blank presentation fields (for example a missing buyer NIP in
    tests), so the renderer feeds the shared summary helper a minimal valid
    surrogate shell that reuses only the caller's line items.
    """

    summary_shell = DomesticVatInvoiceShell(
        issue_date=date(2000, 1, 1),
        sale_date=date(2000, 1, 1),
        invoice_number="RENDER-SUMMARY",
        issue_city="Warszawa",
        payment_form=1,
        seller=PartyShell(
            nip="1234563218",
            name="Seller",
            address_line_1="ul. Render 1",
            address_line_2="00-000 Warszawa",
        ),
        buyer=BuyerShell(
            nip="5261040828",
            name="Buyer",
            address_line_1="ul. Render 2",
            address_line_2="00-000 Warszawa",
        ),
        line_items=shell.line_items,
    )
    return summarize_domestic_vat_shell(summary_shell)


def render_seller_buyer_block(shell: DomesticVatInvoiceShell) -> bytes:
    """Render the first native template to a PDF byte string.

    The template carries an invoice header (number, issue date, sale
    date, currency) above a two-column seller/buyer block. Empty
    optional fields render as empty strings, not the literal "None";
    the resulting PDF still emits the field's row so layout stays
    stable for downstream extraction. Dates are pinned to ISO
    ``YYYY-MM-DD`` so re-rendering the same shell on a different host
    locale yields identical extracted text.
    """

    # WeasyPrint pulls in heavy native libraries (pango/cairo). Import
    # it lazily so the visibility-manifest builder in this module stays
    # cheap to import from benchmark_case, which is wired into the
    # default pytest path.
    from weasyprint import HTML

    seller, buyer = shell.seller, shell.buyer
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    summary = _summarize_for_rendering(shell)
    rendered = (
        html.replace("__INVOICE_NUMBER__", escape(shell.invoice_number or ""))
        .replace("__ISSUE_DATE__", escape(_format_iso_date(shell.issue_date)))
        .replace("__SALE_DATE__", escape(_format_iso_date(shell.sale_date)))
        .replace("__CURRENCY__", escape(shell.currency or ""))
        .replace("__SELLER_NAME__", escape(seller.name or ""))
        .replace("__SELLER_NIP__", escape(seller.nip or ""))
        .replace("__SELLER_ADDR1__", escape(seller.address_line_1 or ""))
        .replace("__SELLER_ADDR2__", escape(seller.address_line_2 or ""))
        .replace("__BUYER_NAME__", escape(buyer.name or ""))
        .replace("__BUYER_NIP__", escape(buyer.nip or ""))
        .replace("__BUYER_ADDR1__", escape(buyer.address_line_1 or ""))
        .replace("__BUYER_ADDR2__", escape(buyer.address_line_2 or ""))
        .replace(
            "__LINE_ITEMS_ROWS__", _render_line_items_rows(shell.line_items)
        )
        .replace(
            "__BUCKET_ROWS__", _render_bucket_rows(summary.bucket_summaries)
        )
        .replace("__TOTALS_ROW__", _render_totals_row(summary))
    )
    return HTML(string=rendered, base_url=str(_TEMPLATES_DIR)).write_pdf()


def build_seller_buyer_visibility_manifest() -> TemplateVisibilityManifest:
    """Return the visibility manifest for the seller/buyer block template.

    Every path in :data:`SELLER_BUYER_VISIBLE_PATHS` is marked
    ``VISIBLE``; the comparator treats every other policy field as
    ``NOT_RENDERED`` by default. Pair this with
    :func:`comparison.validate_template_visibility` to confirm — or
    deny — that the template honors the bucket-1 required-downstream
    set on a given comparison policy.
    """

    return TemplateVisibilityManifest(
        template_id=SELLER_BUYER_TEMPLATE_ID,
        fields={
            path: VisibilityStatus.VISIBLE
            for path in SELLER_BUYER_VISIBLE_PATHS
        },
    )
