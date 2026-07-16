"""Smoke-test FA(3) resources from an isolated installed wheel."""

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
assert Path(src.__file__).resolve().is_relative_to(
    Path(sys.prefix).resolve()
)

result = validate_xml_against_local_schema_bundle("<Faktura/>")
assert result.is_valid is False
assert result.error
"""


def main() -> None:
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
