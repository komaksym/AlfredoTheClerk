"""macOS DYLD relaunch helpers for WeasyPrint entrypoints.

On macOS, ``uv run`` can launch Python through a SIP-protected wrapper
that strips ``DYLD_*`` environment variables before the real Python
process starts. WeasyPrint's native dependencies (pango/glib/cairo)
need ``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`` when installed
via Homebrew, so CLI entrypoints that eventually import WeasyPrint must
sometimes relaunch themselves under ``.venv/bin/python`` with that env
var already present.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


_HOMEBREW_LIB = Path("/opt/homebrew/lib")


def relaunch_module_with_homebrew_dyld_if_needed(module: str) -> None:
    """Re-launch ``python -m <module>`` with Homebrew libs visible on macOS.

    No-op on non-macOS hosts, when Homebrew's library directory is
    absent, or when ``DYLD_FALLBACK_LIBRARY_PATH`` already includes
    ``/opt/homebrew/lib``.
    """

    if sys.platform != "darwin":
        return
    if not _HOMEBREW_LIB.is_dir():
        return

    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if str(_HOMEBREW_LIB) in current.split(os.pathsep):
        return

    child_env = os.environ.copy()
    child_env["DYLD_FALLBACK_LIBRARY_PATH"] = (
        f"{_HOMEBREW_LIB}{os.pathsep}{current}"
        if current
        else str(_HOMEBREW_LIB)
    )
    completed = subprocess.run(
        [sys.executable, "-m", module, *sys.argv[1:]],
        env=child_env,
        check=False,
    )
    _exit(completed.returncode)


def _exit(code: int) -> NoReturn:
    """Exit the current process after a relaunch."""

    raise SystemExit(code)
