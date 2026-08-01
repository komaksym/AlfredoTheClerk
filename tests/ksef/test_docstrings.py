"""Regression tests enforcing module and function docstrings across active slices."""

from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDITED_MODULE_DIRS = (
    _REPO_ROOT / "src" / "ksef",
    _REPO_ROOT / "tests" / "ksef",
    _REPO_ROOT / "src" / "agentic_repair",
    _REPO_ROOT / "tests" / "agentic_repair",
    _REPO_ROOT / "src" / "review_ui",
    _REPO_ROOT / "tests" / "review_ui",
)


def _python_modules() -> tuple[Path, ...]:
    """Return every Python module recursively under the audited source trees."""

    modules = [
        path
        for directory in _AUDITED_MODULE_DIRS
        for path in directory.rglob("*.py")
    ]
    return tuple(sorted(modules))


def _parse_module(path: Path) -> tuple[str, ast.Module]:
    """Read and parse one Python module for docstring validation."""

    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


def test_every_audited_module_has_line_one_docstring() -> None:
    """Require every active-slice module to start with a module docstring."""

    missing: list[str] = []
    for path in _python_modules():
        source, tree = _parse_module(path)
        starts_with_docstring = source.startswith('"""') or source.startswith("'''")
        if not starts_with_docstring or ast.get_docstring(tree, clean=False) is None:
            missing.append(str(path.relative_to(_REPO_ROOT)))

    assert not missing, "modules missing line-one docstrings: " + ", ".join(missing)


def test_every_audited_function_has_docstring() -> None:
    """Require docstrings on functions, methods, nested and async functions."""

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
