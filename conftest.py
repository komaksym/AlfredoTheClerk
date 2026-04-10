"""Repo-root pytest conftest.

Only purpose right now: make ``uv run pytest`` on macOS inherit the
Homebrew DYLD fallback path before any test imports WeasyPrint.
"""

from __future__ import annotations

from src.invoice_gen.macos_dyld import (
    relaunch_module_with_homebrew_dyld_if_needed,
)

relaunch_module_with_homebrew_dyld_if_needed("pytest")
