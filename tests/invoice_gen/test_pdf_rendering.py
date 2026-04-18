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
from decimal import Decimal

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
from src.invoice_gen.domestic_vat_shell_summary import (
    summarize_domestic_vat_shell,
)
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    SELLER_BUYER_VISIBLE_PATHS,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
)
from src.invoice_gen.template_visibility import VisibilityStatus


_SEED = 42
_TABLE_LINE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}


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
    """Manifest must mark every renderer-visible path as VISIBLE."""

    manifest = build_seller_buyer_visibility_manifest()

    assert manifest.template_id == SELLER_BUYER_TEMPLATE_ID
    assert dict(manifest.fields) == {
        path: VisibilityStatus.VISIBLE for path in SELLER_BUYER_VISIBLE_PATHS
    }


def test_seller_buyer_manifest_required_path_validation_after_m4_slice1() -> (
    None
):
    """Bucket-1 gate: header + parties + line items are now all covered.

    After M4 slice 1 extended the template with a bordered line-items
    table, every required path in the default policy is visible.
    The gate should return an empty missing-list; if later work trims
    the required set or adds new required paths, the subset assertion
    keeps this test honest.
    """

    policy = build_default_comparison_policy()
    manifest = build_seller_buyer_visibility_manifest()

    missing = validate_template_visibility(policy, manifest)

    expected_missing = sorted(
        policy.required_paths - SELLER_BUYER_VISIBLE_PATHS
    )
    assert missing == expected_missing
    assert "shell.invoice_number" not in missing
    assert "shell.issue_date" not in missing
    assert "shell.line_items.count" not in missing
    assert "shell.line_items[*].description" not in missing


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


# --- M4 slice 1: line-items table ---------------------------------------


def _extract_tables(pdf_bytes: bytes) -> list[list[list[str | None]]]:
    """Return every bordered table extracted from the first page."""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        tables = pdf.pages[0].extract_tables(
            table_settings=_TABLE_LINE_SETTINGS
        )
    assert len(tables) == 2, f"expected exactly two tables, got {len(tables)}"
    return tables


def _extract_first_table(pdf_bytes: bytes) -> list[list[str | None]]:
    """Return the rendered line-items table."""

    return _extract_tables(pdf_bytes)[0]


def _extract_second_table(pdf_bytes: bytes) -> list[list[str | None]]:
    """Return the rendered VAT-summary table."""

    return _extract_tables(pdf_bytes)[1]


def test_line_items_table_has_expected_header_row(
    rendered_pdf: bytes,
) -> None:
    """The header row must expose the six column labels as separate cells."""

    table = _extract_first_table(rendered_pdf)

    header = [cell.strip() if cell else "" for cell in table[0]]
    assert header == [
        "Lp.",
        "Nazwa",
        "J.m.",
        "Ilość",
        "Cena netto",
        "Stawka VAT",
    ]


def test_line_items_rows_round_trip_canonical_values(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Each rendered cell must match the frozen Decimal formatting exactly.

    This is the round-trip contract the M4 extractor will rely on: a
    cell string parsed back to ``Decimal`` must equal the shell value.
    """

    table = _extract_first_table(rendered_pdf)
    data_rows = table[1:]

    assert len(data_rows) == len(shell.line_items)
    for index, (row, item) in enumerate(
        zip(data_rows, shell.line_items), start=1
    ):
        cells = [(cell or "").strip() for cell in row]
        lp, description, unit, quantity, unit_price_net, vat_rate = cells

        assert lp == str(index)
        assert description == item.description
        assert unit == item.unit
        assert item.quantity is not None
        assert item.unit_price_net is not None
        assert item.vat_rate is not None
        assert Decimal(quantity) == item.quantity
        assert Decimal(unit_price_net) == item.unit_price_net
        assert Decimal(vat_rate) == item.vat_rate


def test_re_rendering_same_shell_yields_identical_tables(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Table-extraction determinism: cell strings must be byte-stable."""

    second = render_seller_buyer_block(shell)

    assert _extract_first_table(rendered_pdf) == _extract_first_table(second)


# --- M4 slice 2: VAT summary table --------------------------------------


def test_summary_table_has_expected_header_row_and_bucket_count(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """The second table must expose bucket rows plus a final ``Razem`` row."""

    summary = summarize_domestic_vat_shell(shell)
    table = _extract_second_table(rendered_pdf)

    header = [cell.strip() if cell else "" for cell in table[0]]
    assert header == [
        "Stawka VAT",
        "Wartość netto",
        "VAT",
        "Wartość brutto",
    ]

    data_rows = table[1:]
    assert len(data_rows) == len(summary.bucket_summaries) + 1
    assert (data_rows[-1][0] or "").strip() == "Razem"


def test_summary_rows_round_trip_canonical_values(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """Each VAT bucket cell and the final totals row must parse back exactly."""

    summary = summarize_domestic_vat_shell(shell)
    table = _extract_second_table(rendered_pdf)
    data_rows = table[1:]
    bucket_rows = data_rows[:-1]
    totals_row = [(cell or "").strip() for cell in data_rows[-1]]

    assert len(bucket_rows) == len(summary.bucket_summaries)
    for row, (vat_rate, bucket) in zip(
        bucket_rows,
        sorted(summary.bucket_summaries.items()),
        strict=True,
    ):
        cells = [(cell or "").strip() for cell in row]
        rate_text, net_total, vat_total, gross_total = cells

        assert Decimal(rate_text) == vat_rate
        assert Decimal(net_total) == bucket.net_total
        assert Decimal(vat_total) == bucket.vat_total
        assert Decimal(gross_total) == bucket.gross_total

    assert totals_row[0] == "Razem"
    assert Decimal(totals_row[1]) == summary.invoice_net_total
    assert Decimal(totals_row[2]) == summary.invoice_vat_total
    assert Decimal(totals_row[3]) == summary.invoice_gross_total


def test_re_rendering_same_shell_yields_identical_summary_table(
    shell: DomesticVatInvoiceShell, rendered_pdf: bytes
) -> None:
    """The extracted VAT-summary table must stay identical on re-render."""

    second = render_seller_buyer_block(shell)

    assert _extract_second_table(rendered_pdf) == _extract_second_table(second)
