"""Tests for the M2 seller/buyer block PDF renderer.

These tests pin the same parser-visible properties the M2 spike used
to pick WeasyPrint over reportlab: the seller and buyer columns must
be cleanly separable, the NIP digits must come out as their own token
(not glued to the ``NIP:`` label), and re-rendering the same shell
must produce identical pdfplumber extractions. Determinism is the
strongest M2 acceptance criterion — the benchmark contract dies the
moment the same shell starts producing different extracted text.
"""

from __future__ import annotations

import io

import pdfplumber
import pytest

from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    render_seller_buyer_block,
)


_SEED = 42


@pytest.fixture(scope="module")
def rendered_pdf() -> bytes:
    """Render one deterministic shell to PDF, shared across the module."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    return render_seller_buyer_block(shell)


def _extract_words(pdf_bytes: bytes) -> list[dict]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return pdf.pages[0].extract_words()


def _words_signature(words: list[dict]) -> tuple:
    return tuple(
        (w["text"], round(float(w["x0"]), 2), round(float(w["top"]), 2))
        for w in sorted(
            words,
            key=lambda w: (round(float(w["top"]), 1), round(float(w["x0"]), 1)),
        )
    )


def test_template_id_is_stable() -> None:
    """The template id is part of the manifest contract — pin it."""

    assert SELLER_BUYER_TEMPLATE_ID == "seller_buyer_block_v1"


def test_render_returns_pdf_bytes(rendered_pdf: bytes) -> None:
    """A real PDF document starts with the ``%PDF-`` magic header."""

    assert rendered_pdf.startswith(b"%PDF-")
    assert len(rendered_pdf) > 1024


def test_seller_and_buyer_names_are_extractable(rendered_pdf: bytes) -> None:
    """Both party names from the seed must appear in the extracted text."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    words = _extract_words(rendered_pdf)
    text_blob = " ".join(w["text"] for w in words)

    assert shell.seller.name is not None
    assert shell.buyer.name is not None
    # The seed name "Sklep Domowy Komfort sp. z o.o." extracts as
    # individual tokens; check the distinctive head word from each.
    assert shell.seller.name.split()[0] in text_blob
    assert shell.buyer.name.split()[0] in text_blob


def test_seller_and_buyer_nips_are_separate_tokens(
    rendered_pdf: bytes,
) -> None:
    """NIP digits must extract as their own token, not glued to ``NIP:``."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    words = _extract_words(rendered_pdf)
    texts = [w["text"] for w in words]

    assert shell.seller.nip in texts
    assert shell.buyer.nip in texts
    # And the label is its own token, not fused with the digits.
    assert any(t.strip(":") == "NIP" for t in texts)


def test_seller_and_buyer_columns_are_horizontally_separable(
    rendered_pdf: bytes,
) -> None:
    """No seller-column word may overlap any buyer-column word in x."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    words = _extract_words(rendered_pdf)

    seller_anchor = next(w for w in words if w["text"] == shell.seller.nip)
    buyer_anchor = next(w for w in words if w["text"] == shell.buyer.nip)
    seller_band = [
        w
        for w in words
        if abs(float(w["top"]) - float(seller_anchor["top"])) < 50
        and float(w["x0"]) <= float(seller_anchor["x1"]) + 5
    ]
    buyer_band = [
        w
        for w in words
        if abs(float(w["top"]) - float(buyer_anchor["top"])) < 50
        and float(w["x0"]) >= float(buyer_anchor["x0"]) - 5
    ]

    seller_max_x1 = max(float(w["x1"]) for w in seller_band)
    buyer_min_x0 = min(float(w["x0"]) for w in buyer_band)
    assert seller_max_x1 < buyer_min_x0, (
        f"columns overlap: seller_max_x1={seller_max_x1} "
        f"buyer_min_x0={buyer_min_x0}"
    )


def test_re_rendering_same_shell_yields_identical_extraction(
    rendered_pdf: bytes,
) -> None:
    """Determinism gate: extracted words + positions must be byte-stable."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    second = render_seller_buyer_block(shell)

    assert _words_signature(_extract_words(rendered_pdf)) == _words_signature(
        _extract_words(second)
    )


def test_renderer_handles_missing_optional_fields() -> None:
    """A shell with no buyer NIP must still render without raising."""

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    shell.buyer.nip = None
    shell.buyer.address_line_2 = None

    pdf = render_seller_buyer_block(shell)
    assert pdf.startswith(b"%PDF-")
    words = _extract_words(pdf)
    texts = [w["text"] for w in words]
    # Buyer name is still rendered even though NIP and a line are gone.
    assert shell.buyer.name is not None
    assert shell.buyer.name.split()[0] in texts
