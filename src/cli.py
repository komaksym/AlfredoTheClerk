"""CLI for generating one synthetic FA(3) domestic VAT invoice."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src.domestic_vat_faktura_mapping import map_domestic_vat_shell_to_faktura
from src.domestic_vat_seed import build_domestic_vat_seed
from src.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.domestic_vat_xml_rendering import render_faktura_to_xml


def generate_invoice(
    seed: int | None,
    output_dir: Path,
    generated_at: datetime | None = None,
) -> tuple[Path, str]:
    """Run the full pipeline and write the XML file.

    Returns (output_path, summary_text).
    """

    invoice_seed = build_domestic_vat_seed(seed)
    shell = map_domestic_vat_seed_to_shell(invoice_seed)
    summary = summarize_domestic_vat_shell(shell)
    faktura = map_domestic_vat_shell_to_faktura(
        shell, summary, generated_at=generated_at
    )
    xml = render_faktura_to_xml(faktura)

    assert shell.invoice_number is not None
    filename = shell.invoice_number.replace("/", "_") + ".xml"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    output_path.write_text(xml, encoding="utf-8")

    assert shell.seller.nip is not None
    assert shell.seller.name is not None
    assert shell.buyer.nip is not None
    assert shell.buyer.name is not None

    summary_text = (
        f"Generated: {shell.invoice_number}\n"
        f"  Seller:  {shell.seller.name} (NIP {shell.seller.nip})\n"
        f"  Buyer:   {shell.buyer.name} (NIP {shell.buyer.nip})\n"
        f"  Lines:   {len(shell.line_items)}\n"
        f"  Total:   {summary.invoice_gross_total} PLN\n"
        f"  Output:  {output_path}"
    )

    return output_path, summary_text


def main() -> None:
    """Parse CLI args and generate one synthetic invoice."""

    parser = argparse.ArgumentParser(
        description="Generate a synthetic FA(3) domestic VAT invoice."
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
        default=Path("."),
        help="Directory to write the XML file (default: current directory).",
    )
    args = parser.parse_args()

    _, summary_text = generate_invoice(
        seed=args.seed,
        output_dir=args.output_dir,
    )
    print(summary_text)


if __name__ == "__main__":
    main()
