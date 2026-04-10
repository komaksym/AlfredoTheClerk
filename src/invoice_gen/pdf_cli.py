"""CLI for generating one synthetic native-PDF invoice template."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.macos_dyld import (
    relaunch_module_with_homebrew_dyld_if_needed,
)
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    render_seller_buyer_block,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "synthetic_data"


def generate_invoice_pdf(
    seed: int | None,
    output_dir: Path,
) -> tuple[Path, str]:
    """Render one synthetic shell through the M2 PDF template.

    Returns ``(output_path, summary_text)``.
    """

    invoice_seed = build_domestic_vat_seed(seed)
    shell = map_domestic_vat_seed_to_shell(invoice_seed)
    pdf_bytes = render_seller_buyer_block(shell)

    assert shell.invoice_number is not None
    filename = (
        shell.invoice_number.replace("/", "_")
        + f"_{SELLER_BUYER_TEMPLATE_ID}.pdf"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    output_path.write_bytes(pdf_bytes)

    assert shell.seller.nip is not None
    assert shell.seller.name is not None
    assert shell.buyer.nip is not None
    assert shell.buyer.name is not None

    summary_text = (
        f"Generated PDF: {shell.invoice_number}\n"
        f"  Template: {SELLER_BUYER_TEMPLATE_ID}\n"
        f"  Seller:   {shell.seller.name} (NIP {shell.seller.nip})\n"
        f"  Buyer:    {shell.buyer.name} (NIP {shell.buyer.nip})\n"
        f"  Output:   {output_path}"
    )

    return output_path, summary_text


def main() -> None:
    """Parse CLI args and render one synthetic PDF template."""

    relaunch_module_with_homebrew_dyld_if_needed("src.invoice_gen.pdf_cli")

    parser = argparse.ArgumentParser(
        description="Generate a synthetic native-PDF invoice template."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Integer seed for deterministic generation (omit for random).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory to write the PDF file "
            "(default: data/synthetic_data relative to the repo root)."
        ),
    )
    args = parser.parse_args()

    _, summary_text = generate_invoice_pdf(
        seed=args.seed,
        output_dir=args.output_dir,
    )
    print(summary_text)


if __name__ == "__main__":
    main()
