"""Native-PDF rendering for the first M2 template.

This is the M2 renderer deliverable: turn one canonical shell into a
PDF that pdfplumber can extract cleanly. The template covers the
invoice header (number, issue date, sale date, currency) and the
seller/buyer two-column block. Line items, totals, and adnotations
are out of scope until M4.

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
from html import escape
from pathlib import Path

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
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
    }
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_PATH = _TEMPLATES_DIR / f"{SELLER_BUYER_TEMPLATE_ID}.html"


def _format_iso_date(value: date | None) -> str:
    """Render a ``date`` as ``YYYY-MM-DD`` regardless of system locale.

    Locale/timezone are pinned at the renderer boundary so that the
    same shell extracts identically on any host: dates use ISO 8601
    and never call ``strftime`` (which honors the C locale).
    """

    return value.isoformat() if value is not None else ""


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
