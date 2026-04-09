"""Tests for the BenchmarkCase directory format."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.invoice_gen.benchmark_case import (
    CASE_SCHEMA_VERSION,
    XSD_VALIDATION_SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkCaseError,
    XsdValidationResult,
    build_benchmark_case,
    load_benchmark_case,
    save_benchmark_case,
)


_FIXED_GENERATED_AT = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)
_SEED = 42
_CASE_ID = "case-0042"


def _stub_validator_valid(_xml: str) -> XsdValidationResult:
    """Return a fixed valid XSD result, independent of xmllint."""

    return XsdValidationResult(is_valid=True, error=None)


def _stub_validator_invalid(_xml: str) -> XsdValidationResult:
    """Return a fixed invalid XSD result with a deterministic message."""

    return XsdValidationResult(
        is_valid=False, error="stub: element 'foo' is unexpected"
    )


# --- build ---------------------------------------------------------------


def test_build_benchmark_case_is_deterministic_for_fixed_inputs() -> None:
    """Same seed + generated_at must produce byte-identical XML and data."""

    case_a = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    case_b = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    assert case_a.target_xml == case_b.target_xml
    assert case_a.shell == case_b.shell
    assert case_a.summary == case_b.summary
    assert case_a.xsd_validation == case_b.xsd_validation


def test_build_benchmark_case_rejects_naive_generated_at() -> None:
    """A naive ``generated_at`` must be rejected at build time."""

    with pytest.raises(BenchmarkCaseError, match="timezone-aware"):
        build_benchmark_case(
            case_id=_CASE_ID,
            seed=_SEED,
            generated_at=datetime(2026, 4, 7, 12, 0, 0),
            xsd_validator=_stub_validator_valid,
        )


def test_build_benchmark_case_persists_validator_failure() -> None:
    """An invalid XSD result must survive onto the BenchmarkCase object."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_invalid,
    )

    assert case.xsd_validation.is_valid is False
    assert case.xsd_validation.error is not None
    assert "stub" in case.xsd_validation.error


# --- save + load round-trip ---------------------------------------------


def test_save_then_load_benchmark_case_is_lossless(tmp_path: Path) -> None:
    """``save_benchmark_case`` followed by ``load_benchmark_case`` must
    return a case equal to the original across every field."""

    original = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    case_dir = tmp_path / _CASE_ID
    save_benchmark_case(original, case_dir)
    loaded = load_benchmark_case(case_dir)

    assert loaded == original


def test_save_writes_expected_files(tmp_path: Path) -> None:
    """The on-disk layout must match ROADMAP section 3 exactly."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    case_dir = tmp_path / _CASE_ID
    save_benchmark_case(case, case_dir)

    expected = {
        "case.json",
        "shell.json",
        "summary.json",
        "target.xml",
        "xsd_validation.json",
        "comparison_policy.json",
    }
    assert {p.name for p in case_dir.iterdir()} == expected


def test_save_is_idempotent_for_same_case(tmp_path: Path) -> None:
    """Saving the same case twice must yield byte-identical files."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    save_benchmark_case(case, dir_a)
    save_benchmark_case(case, dir_b)

    for filename in (
        "case.json",
        "shell.json",
        "summary.json",
        "target.xml",
        "xsd_validation.json",
        "comparison_policy.json",
    ):
        assert (dir_a / filename).read_bytes() == (
            dir_b / filename
        ).read_bytes()


def test_save_preserves_non_utc_but_aware_generated_at(
    tmp_path: Path,
) -> None:
    """A non-UTC but aware ``generated_at`` must round-trip losslessly."""

    warsaw = timezone(timedelta(hours=2))
    aware = datetime(2026, 4, 7, 14, 0, 0, tzinfo=warsaw)

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=aware,
        xsd_validator=_stub_validator_valid,
    )

    case_dir = tmp_path / _CASE_ID
    save_benchmark_case(case, case_dir)
    loaded = load_benchmark_case(case_dir)

    assert loaded.generated_at == aware


# --- load error paths ----------------------------------------------------


def _write_round_trippable_case(tmp_path: Path) -> Path:
    """Build and save one valid case, returning its directory."""

    case = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    case_dir = tmp_path / _CASE_ID
    save_benchmark_case(case, case_dir)
    return case_dir


def test_load_rejects_unknown_case_schema_version(tmp_path: Path) -> None:
    """Bumping the case schema version on disk must raise on load."""

    case_dir = _write_round_trippable_case(tmp_path)
    case_path = case_dir / "case.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["schema_version"] = CASE_SCHEMA_VERSION + 1
    case_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(BenchmarkCaseError, match="case.schema_version"):
        load_benchmark_case(case_dir)


def test_load_rejects_unknown_xsd_validation_schema_version(
    tmp_path: Path,
) -> None:
    """Bumping the xsd_validation schema version on disk must raise."""

    case_dir = _write_round_trippable_case(tmp_path)
    xsd_path = case_dir / "xsd_validation.json"
    payload = json.loads(xsd_path.read_text(encoding="utf-8"))
    payload["schema_version"] = XSD_VALIDATION_SCHEMA_VERSION + 1
    xsd_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(
        BenchmarkCaseError, match="xsd_validation.schema_version"
    ):
        load_benchmark_case(case_dir)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    """Removing any expected file must raise on load."""

    case_dir = _write_round_trippable_case(tmp_path)
    (case_dir / "summary.json").unlink()

    with pytest.raises(BenchmarkCaseError, match="missing summary.json"):
        load_benchmark_case(case_dir)


def test_load_rejects_unknown_keys_in_case_json(tmp_path: Path) -> None:
    """Injecting an unexpected key in case.json must raise on load."""

    case_dir = _write_round_trippable_case(tmp_path)
    case_path = case_dir / "case.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["unexpected"] = "nope"
    case_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(BenchmarkCaseError, match="unknown keys"):
        load_benchmark_case(case_dir)


# --- BenchmarkCase is a value object -------------------------------------


def test_benchmark_case_equality_is_value_based(tmp_path: Path) -> None:
    """Two independently built cases with identical inputs must be equal."""

    case_a = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )
    case_b = build_benchmark_case(
        case_id=_CASE_ID,
        seed=_SEED,
        generated_at=_FIXED_GENERATED_AT,
        xsd_validator=_stub_validator_valid,
    )

    assert case_a == case_b
    assert isinstance(case_a, BenchmarkCase)
