"""Regression tests enforcing module and function docstrings across the KSeF slice."""

from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_KSEF_MODULE_DIRS = (_REPO_ROOT / "src" / "ksef", _REPO_ROOT / "tests" / "ksef")


def _python_modules() -> tuple[Path, ...]:
    """Return every Python module in the KSeF source and test directories."""

    modules = [path for directory in _KSEF_MODULE_DIRS for path in directory.glob("*.py")]
    return tuple(sorted(modules))


def _parse_module(path: Path) -> tuple[str, ast.Module]:
    """Read and parse one Python module for docstring validation."""

    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


def test_every_ksef_module_has_line_one_docstring() -> None:
    """Require every KSeF source and test module to start with a module docstring."""

    missing: list[str] = []
    for path in _python_modules():
        source, tree = _parse_module(path)
        starts_with_docstring = source.startswith('"""') or source.startswith("'''")
        if not starts_with_docstring or ast.get_docstring(tree, clean=False) is None:
            missing.append(str(path.relative_to(_REPO_ROOT)))

    assert not missing, "modules missing line-one docstrings: " + ", ".join(missing)


def test_every_ksef_function_has_docstring() -> None:
    """Require docstrings on every function, method, nested function, and async function."""

    missing: list[str] = []
    for path in _python_modules():
        _, tree = _parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(
                node, clean=False
            ) is None:
                relative = path.relative_to(_REPO_ROOT)
                missing.append(f"{relative}:{node.lineno}:{node.name}")

    assert not missing, "functions missing docstrings: " + ", ".join(missing)
