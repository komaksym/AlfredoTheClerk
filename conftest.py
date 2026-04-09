"""Repo-root pytest conftest.

Only purpose right now: work around the macOS DYLD/SIP interaction that
prevents WeasyPrint from finding its native ``pango``/``cairo``/
``glib`` libraries when pytest is launched via ``uv run``.

The problem
-----------

WeasyPrint uses ``cffi`` to ``dlopen`` ``libgobject-2.0``,
``libpango`` and friends *by name*. On macOS those libraries live under
``/opt/homebrew/lib`` (Homebrew default), which dyld will only search
when ``DYLD_FALLBACK_LIBRARY_PATH`` includes it. macOS's System
Integrity Protection strips ``DYLD_*`` environment variables from
SIP-protected launchers; ``uv run`` sits in front of the venv python
through such a launcher, so the env var never reaches the python
process and the WeasyPrint import explodes.

Setting ``os.environ["DYLD_FALLBACK_LIBRARY_PATH"]`` from inside Python
does not help — dyld reads the variable once at process start, not at
``dlopen`` time. The only reliable fix is to launch a fresh
``.venv/bin/python`` (which is *not* SIP-protected) with the env var
already in place.

Why ``subprocess.run`` and not ``os.execv``: in-place ``execv`` reuses
the inherited stdout file descriptor from ``uv run``'s pipe, and
pytest's per-test capture dance leaves that descriptor in a state the
parent ``uv run`` cannot read at session end — output disappears.
``subprocess.run(...)`` spawns a real child whose stdout is piped
through cleanly, so the wrapper sees the same output it would see
running pytest directly.

This file does nothing on Linux/CI: there, weasyprint's libraries are
discoverable through the standard linker search and ``DYLD_*`` is a
macOS-only concept.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _ensure_macos_homebrew_libs_visible() -> None:
    """Re-launch pytest with ``DYLD_FALLBACK_LIBRARY_PATH`` on macOS."""

    if sys.platform != "darwin":
        return
    homebrew_lib = Path("/opt/homebrew/lib")
    if not homebrew_lib.is_dir():
        return
    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if str(homebrew_lib) in current.split(os.pathsep):
        return

    child_env = os.environ.copy()
    child_env["DYLD_FALLBACK_LIBRARY_PATH"] = (
        f"{homebrew_lib}{os.pathsep}{current}" if current else str(homebrew_lib)
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        env=child_env,
        check=False,
    )
    sys.exit(completed.returncode)


_ensure_macos_homebrew_libs_visible()
