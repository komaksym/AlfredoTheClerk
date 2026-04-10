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

from src.invoice_gen.comparison import (
    build_default_comparison_policy,
    validate_template_visibility,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    SELLER_BUYER_VISIBLE_PATHS,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
)
from src.invoice_gen.template_visibility import VisibilityStatus


_SEED = 42


@pytest.fixture(scope="module")
def shell() -> DomesticVatInvoiceShell:
    """Build one deterministic shell once per module."""

    return map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))


@pytest.fixture(scope="module")
def rendered_pdf(shell: DomesticVatInvoiceShell) -> bytes:
    """Render the module shell to PDF once."""

    return render_seller_buyer_block(shell)


def _extract_page_words(pdf_bytes: bytes) -> list[dict]:
    """Return pdfplumber word records from the first page of one PDF."""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return pdf.pages[0].extract_words()


def _normalized_word_boxes(words: list[dict]) -> tuple:
    """Reduce raw pdfplumber words to a stable comparison fingerprint.

    ``extract_words()`` returns dicts with many fields and float-heavy
    coordinates. The determinism tests only care about parser-visible
    geometry, so this helper:

    * orders words in reading order (top-to-bottom, then left-to-right)
    * keeps only the text plus bounding-box edges
    * rounds coordinates to ignore microscopic float noise
    """

    return tuple(
        (
            w["text"],
            round(float(w["x0"]), 2),
            round(float(w["top"]), 2),
            round(float(w["x1"]), 2),
            round(float(w["bottom"]), 2),
        )
        for w in sorted(
            words,
            # Approximate reading order before comparing the extracted page.
            key=lambda w: (round(float(w["top"]), 1), round(float(w["x0"]), 1)),
        )
    )


def test_template_id_is_stable() -> None:
    """The template id is part of the manifest contract — pin it."""

    assert SELLER_BUYER_TEMPLATE_ID == "seller_buyer_block_v1"


def test_render_returns_pdf_bytes(rendered_pdf: bytes) -> None:
    """A real PDF document starts with the ``%PDF-`` magic header."""

    assert rendered_pdf.startswith(b"%PDF-")


def test_seller_and_buyer_names_are_extractable(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Both party names from the seed must appear in the extracted text."""

    words = _extract_page_words(rendered_pdf)
    text_blob = " ".join(w["text"] for w in words)

    assert shell.seller.name is not None
    assert shell.buyer.name is not None
    # The seed name "Sklep Domowy Komfort sp. z o.o." extracts as
    # individual tokens; check the distinctive head word from each.
    assert shell.seller.name.split()[0] in text_blob
    assert shell.buyer.name.split()[0] in text_blob


def test_seller_and_buyer_nips_are_separate_tokens(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """NIP digits must extract as their own token, not glued to ``NIP:``."""

    words = _extract_page_words(rendered_pdf)
    texts = [w["text"] for w in words]

    assert shell.seller.nip in texts
    assert shell.buyer.nip in texts
    # And the label is its own token, not fused with the digits.
    assert any(t.strip(":") == "NIP" for t in texts)


def test_header_fields_extract_as_separate_tokens(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Header fields must extract as their own tokens, ISO-formatted.

    The M2 acceptance gate requires header fields to be parser-visible
    as separate tokens, not glued to their labels. ISO ``YYYY-MM-DD``
    is the renderer's pinned date format so re-rendering the same
    shell on any host locale yields identical extraction.
    """

    words = _extract_page_words(rendered_pdf)
    texts = [w["text"] for w in words]

    assert shell.invoice_number is not None
    assert shell.issue_date is not None
    assert shell.sale_date is not None

    assert shell.invoice_number in texts
    assert shell.issue_date.isoformat() in texts
    assert shell.sale_date.isoformat() in texts
    assert shell.currency in texts
    # Labels are their own tokens, not fused with their values.
    label_stems = {t.strip(":") for t in texts}
    assert {"Numer", "Wystawiono", "Sprzedano", "Waluta"}.issubset(label_stems)


def test_seller_and_buyer_columns_are_horizontally_separable(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """No seller-column word may overlap any buyer-column word in x."""

    words = _extract_page_words(rendered_pdf)

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
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Determinism gate: extracted words + full boxes must be stable."""

    second = render_seller_buyer_block(shell)

    assert _normalized_word_boxes(
        _extract_page_words(rendered_pdf)
    ) == _normalized_word_boxes(_extract_page_words(second))


# --- Visibility manifest contract ---------------------------------------


def test_seller_buyer_manifest_marks_only_party_paths_visible() -> None:
    """Manifest must mark exactly the eight party fields as VISIBLE."""

    manifest = build_seller_buyer_visibility_manifest()

    assert manifest.template_id == SELLER_BUYER_TEMPLATE_ID
    assert dict(manifest.fields) == {
        path: VisibilityStatus.VISIBLE for path in SELLER_BUYER_VISIBLE_PATHS
    }


def test_seller_buyer_manifest_fails_required_path_validation() -> None:
    """The bucket-1 gate must flag every required field this template skips.

    The first M2 template covers header + party fields but not line
    items, so the line-items table entries in the M1 default required
    set must come back as missing. This is the proof that the gate is
    doing real work — header fields no longer appear in the missing
    list because the template now renders them.
    """

    policy = build_default_comparison_policy()
    manifest = build_seller_buyer_visibility_manifest()

    missing = validate_template_visibility(policy, manifest)

    expected_missing = sorted(
        policy.required_paths - SELLER_BUYER_VISIBLE_PATHS
    )
    assert missing == expected_missing
    # Header is satisfied; line items are still out of scope until M4.
    assert "shell.invoice_number" not in missing
    assert "shell.issue_date" not in missing
    assert "shell.line_items.count" in missing


def test_seller_buyer_manifest_visible_paths_are_in_default_policy() -> None:
    """Every VISIBLE path must be a known field of the default policy.

    A VISIBLE entry that the policy does not score is dead weight: the
    comparator could never gate on it because there is no rule to
    apply. Catching this here keeps the manifest honest before it
    reaches benchmark cases.
    """

    policy_paths = set(build_default_comparison_policy().fields.keys())
    assert SELLER_BUYER_VISIBLE_PATHS.issubset(policy_paths)


def test_renderer_handles_missing_optional_fields() -> None:
    """A shell with no buyer NIP must still render without raising.

    Builds a fresh shell instead of taking the module fixture so that
    mutating ``buyer.nip`` does not bleed into sibling tests.
    """

    local_shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(_SEED))
    local_shell.buyer.nip = None
    local_shell.buyer.address_line_2 = None

    pdf = render_seller_buyer_block(local_shell)
    assert pdf.startswith(b"%PDF-")
    texts = [w["text"] for w in _extract_page_words(pdf)]
    # Buyer name is still rendered even though NIP and a line are gone.
    assert local_shell.buyer.name is not None
    assert local_shell.buyer.name.split()[0] in texts
