"""Smoke-test packaged FA(3) and review-UI resources from an installed wheel."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


_SMOKE_PROGRAM = r"""
import sys
from importlib.resources import files
from pathlib import Path

import src
from src.invoice_gen.fa3_xsd_validation import (
    validate_xml_against_local_schema_bundle,
)

required = {
    "schemat.xsd",
    "StrukturyDanych_v10-0E.xsd",
    "ElementarneTypyDanych_v10-0E.xsd",
    "KodyKrajow_v10-0E.xsd",
}
available = {
    item.name for item in files("src.invoice_gen.schemas").iterdir()
}
assert required <= available, required - available

review_root = files("src.review_ui")
for relative_path in (
    "templates/base.html",
    "templates/upload.html",
    "templates/review.html",
    "templates/result.html",
    "static/review.css",
    "static/review.js",
):
    assert review_root.joinpath(relative_path).is_file(), relative_path

assert Path(src.__file__).resolve().is_relative_to(
    Path(sys.prefix).resolve()
)

result = validate_xml_against_local_schema_bundle("<Faktura/>")
assert result.is_valid is False
assert result.error
"""


def main() -> None:
    """Install one wheel in isolation and verify required package resources."""

    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    wheel = parser.parse_args().wheel.resolve(strict=True)

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        root = Path(tmp_dir_name)
        venv = root / "venv"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(venv)],
            check=True,
        )
        python = venv / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)
        env["PYTHONNOUSERSITE"] = "1"
        subprocess.run(
            [str(python), "-c", _SMOKE_PROGRAM],
            cwd=root,
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
