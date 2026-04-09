"""Native-PDF rendering for the M2 seller/buyer block.

This is the first M2 deliverable: turn one canonical shell into a PDF
that pdfplumber can extract cleanly. Scope is intentionally narrow —
only the seller/buyer two-column block, no header fields, no line
items, no totals. Those land in later M2/M3 chunks once this is
reviewed and pinned.

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

from html import escape
from pathlib import Path

from weasyprint import HTML

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell


SELLER_BUYER_TEMPLATE_ID = "seller_buyer_block_v1"

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_PATH = _TEMPLATES_DIR / f"{SELLER_BUYER_TEMPLATE_ID}.html"


def render_seller_buyer_block(shell: DomesticVatInvoiceShell) -> bytes:
    """Render the seller/buyer two-column block to a PDF byte string.

    Empty optional fields render as empty strings, not the literal
    "None"; the resulting PDF still emits the field's row so the layout
    remains stable for downstream extraction. The renderer does not
    consult ``shell.line_items`` or any other field outside the
    seller/buyer parties — that scope expands in later M2 work.
    """

    seller, buyer = shell.seller, shell.buyer
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = (
        html.replace("__SELLER_NAME__", escape(seller.name or ""))
        .replace("__SELLER_NIP__", escape(seller.nip or ""))
        .replace("__SELLER_ADDR1__", escape(seller.address_line_1 or ""))
        .replace("__SELLER_ADDR2__", escape(seller.address_line_2 or ""))
        .replace("__BUYER_NAME__", escape(buyer.name or ""))
        .replace("__BUYER_NIP__", escape(buyer.nip or ""))
        .replace("__BUYER_ADDR1__", escape(buyer.address_line_1 or ""))
        .replace("__BUYER_ADDR2__", escape(buyer.address_line_2 or ""))
    )
    return HTML(string=rendered, base_url=str(_TEMPLATES_DIR)).write_pdf()
