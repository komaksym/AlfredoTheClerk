"""Benchmark case directory format for the domestic VAT pipeline.

A :class:`BenchmarkCase` bundles one canonical shell, its derived
summary, the deterministic FA(3) target XML rendered with a frozen
``generated_at``, the local XSD validation result, the comparison
policy, and per-template visibility manifests. The case can be written
to a directory and loaded back losslessly, so benchmark fixtures become
reviewable on disk and no longer need to be regenerated from seeds.

On-disk layout (ROADMAP.md section 3):

* ``case.json``                 metadata, frozen ``generated_at``, versions
* ``shell.json``                from ``domestic_vat_json.shell_to_json``
* ``summary.json``              from ``domestic_vat_json.summary_to_json``
* ``target.xml``                deterministic FA(3) XML
* ``xsd_validation.json``       local XSD validation result
* ``comparison_policy.json``    scoring contract
* ``manifests/<template>.json`` render-visibility contract

Any breaking change to the case or xsd_validation encoding must bump the
relevant ``*_SCHEMA_VERSION`` constant.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.invoice_gen.comparison import (
    COMPARISON_POLICY_SCHEMA_VERSION,
    ComparisonError,
    ComparisonPolicy,
    build_default_comparison_policy,
    policy_from_json,
    policy_to_json,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_faktura_mapping import (
    map_domestic_vat_shell_to_faktura,
)
from src.invoice_gen.domestic_vat_json import (
    SHELL_JSON_SCHEMA_VERSION,
    SUMMARY_JSON_SCHEMA_VERSION,
    shell_from_json,
    shell_to_json,
    summary_from_json,
    summary_to_json,
)
from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import (
    map_domestic_vat_seed_to_shell,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_xml_rendering import render_faktura_to_xml
from src.invoice_gen.template_registry import TEMPLATE_REGISTRY
from src.invoice_gen.template_visibility import (
    NO_PDF_TEMPLATE_ID,
    TemplateVisibilityError,
    TemplateVisibilityManifest,
    build_no_pdf_visibility_manifest,
    manifest_from_json,
    manifest_to_json,
)


CASE_SCHEMA_VERSION = 1
XSD_VALIDATION_SCHEMA_VERSION = 1


_CASE_FILENAME = "case.json"
_SHELL_FILENAME = "shell.json"
_SUMMARY_FILENAME = "summary.json"
_TARGET_XML_FILENAME = "target.xml"
_XSD_VALIDATION_FILENAME = "xsd_validation.json"
_COMPARISON_POLICY_FILENAME = "comparison_policy.json"
_MANIFESTS_DIRECTORY = "manifests"


_CASE_KEYS = frozenset(
    {
        "schema_version",
        "case_id",
        "generated_at",
        "shell_schema_version",
        "summary_schema_version",
        "comparison_policy_schema_version",
    }
)
_XSD_VALIDATION_KEYS = frozenset(
    {
        "schema_version",
        "is_valid",
        "error",
    }
)


class BenchmarkCaseError(Exception):
    """One error raised while building, saving, or loading a case."""


@dataclass(frozen=True, kw_only=True)
class XsdValidationResult:
    """Outcome of running local XSD validation on ``target.xml``."""

    is_valid: bool
    error: str | None = None


@dataclass(frozen=True, kw_only=True)
class BenchmarkCase:
    """One persisted benchmark case for the domestic VAT pipeline."""

    case_id: str
    generated_at: datetime
    shell: DomesticVatInvoiceShell
    summary: DomesticVatInvoiceSummary
    target_xml: str
    xsd_validation: XsdValidationResult
    policy: ComparisonPolicy
    manifests: Mapping[str, TemplateVisibilityManifest]


XsdValidator = Callable[[str], XsdValidationResult]


# --- Public API ----------------------------------------------------------


def build_benchmark_case(
    *,
    case_id: str,
    seed: int,
    generated_at: datetime,
    xsd_validator: XsdValidator,
    policy: ComparisonPolicy | None = None,
) -> BenchmarkCase:
    """Run the full pipeline and return one deterministic benchmark case.

    ``generated_at`` must be timezone-aware so the resulting FA(3) XML is
    stable across runs and machines. ``xsd_validator`` is called with the
    rendered XML and its result is persisted alongside the case. If
    ``policy`` is omitted, the M1 default from
    :func:`build_default_comparison_policy` is used.
    """

    _require_aware_datetime(generated_at, "generated_at")

    invoice_seed = build_domestic_vat_seed(seed)
    shell = map_domestic_vat_seed_to_shell(invoice_seed)
    return build_benchmark_case_from_shell(
        case_id=case_id,
        shell=shell,
        generated_at=generated_at,
        xsd_validator=xsd_validator,
        policy=policy,
    )


def build_benchmark_case_from_shell(
    *,
    case_id: str,
    shell: DomesticVatInvoiceShell,
    generated_at: datetime,
    xsd_validator: XsdValidator,
    policy: ComparisonPolicy | None = None,
    manifests: Mapping[str, TemplateVisibilityManifest] | None = None,
) -> BenchmarkCase:
    """Build one deterministic benchmark case from explicit shell truth.

    This is the curated-case entrypoint for M4: callers provide the
    canonical shell directly, and the case builder derives the summary,
    target FA(3) XML, persisted XSD result, and default manifests.
    """

    _require_aware_datetime(generated_at, "generated_at")

    summary = summarize_domestic_vat_shell(shell)
    faktura = map_domestic_vat_shell_to_faktura(
        shell, summary, generated_at=generated_at
    )
    target_xml = render_faktura_to_xml(faktura)
    xsd_validation = xsd_validator(target_xml)
    resolved_policy = (
        policy if policy is not None else build_default_comparison_policy()
    )
    if manifests is not None:
        resolved_manifests = dict(manifests)
    else:
        resolved_manifests = {
            NO_PDF_TEMPLATE_ID: build_no_pdf_visibility_manifest(
                resolved_policy.fields.keys()
            ),
        }
        for template_id, spec in TEMPLATE_REGISTRY.items():
            resolved_manifests[template_id] = spec.visibility_builder()

    return BenchmarkCase(
        case_id=case_id,
        generated_at=generated_at,
        shell=shell,
        summary=summary,
        target_xml=target_xml,
        xsd_validation=xsd_validation,
        policy=resolved_policy,
        manifests=resolved_manifests,
    )


def save_benchmark_case(case: BenchmarkCase, directory: Path) -> None:
    """Persist one benchmark case under ``directory``.

    The directory is created if missing. Existing files with the same
    names are overwritten so re-saving a case is idempotent.
    """

    directory.mkdir(parents=True, exist_ok=True)

    (directory / _CASE_FILENAME).write_text(
        _case_metadata_to_json(case), encoding="utf-8"
    )
    (directory / _SHELL_FILENAME).write_text(
        shell_to_json(case.shell), encoding="utf-8"
    )
    (directory / _SUMMARY_FILENAME).write_text(
        summary_to_json(case.summary), encoding="utf-8"
    )
    (directory / _TARGET_XML_FILENAME).write_text(
        case.target_xml, encoding="utf-8"
    )
    (directory / _XSD_VALIDATION_FILENAME).write_text(
        _xsd_validation_to_json(case.xsd_validation), encoding="utf-8"
    )
    (directory / _COMPARISON_POLICY_FILENAME).write_text(
        policy_to_json(case.policy), encoding="utf-8"
    )
    manifests_dir = directory / _MANIFESTS_DIRECTORY
    manifests_dir.mkdir(parents=True, exist_ok=True)
    for template_id, manifest in sorted(case.manifests.items()):
        if manifest.template_id != template_id:
            raise BenchmarkCaseError(
                "manifest mapping key must match manifest.template_id: "
                f"{template_id!r} != {manifest.template_id!r}"
            )
        (manifests_dir / f"{template_id}.json").write_text(
            manifest_to_json(manifest), encoding="utf-8"
        )


def load_benchmark_case(directory: Path) -> BenchmarkCase:
    """Load one benchmark case from ``directory``.

    Raises :class:`BenchmarkCaseError` if any expected file is missing or
    carries an unknown schema version.
    """

    _require_file(directory, _CASE_FILENAME)
    _require_file(directory, _SHELL_FILENAME)
    _require_file(directory, _SUMMARY_FILENAME)
    _require_file(directory, _TARGET_XML_FILENAME)
    _require_file(directory, _XSD_VALIDATION_FILENAME)
    _require_file(directory, _COMPARISON_POLICY_FILENAME)
    manifests = _load_manifests(directory)

    metadata = _case_metadata_from_json(
        (directory / _CASE_FILENAME).read_text(encoding="utf-8")
    )
    shell = shell_from_json(
        (directory / _SHELL_FILENAME).read_text(encoding="utf-8")
    )
    summary = summary_from_json(
        (directory / _SUMMARY_FILENAME).read_text(encoding="utf-8")
    )
    target_xml = (directory / _TARGET_XML_FILENAME).read_text(encoding="utf-8")
    xsd_validation = _xsd_validation_from_json(
        (directory / _XSD_VALIDATION_FILENAME).read_text(encoding="utf-8")
    )
    try:
        policy = policy_from_json(
            (directory / _COMPARISON_POLICY_FILENAME).read_text(
                encoding="utf-8"
            )
        )
    except ComparisonError as exc:
        raise BenchmarkCaseError(
            f"failed to load comparison_policy.json: {exc}"
        ) from exc

    return BenchmarkCase(
        case_id=metadata["case_id"],
        generated_at=metadata["generated_at"],
        shell=shell,
        summary=summary,
        target_xml=target_xml,
        xsd_validation=xsd_validation,
        policy=policy,
        manifests=manifests,
    )


# --- case.json encoding --------------------------------------------------


def _case_metadata_to_json(case: BenchmarkCase) -> str:
    """Encode the case metadata block as a deterministic JSON string."""

    payload: dict[str, Any] = {
        "schema_version": CASE_SCHEMA_VERSION,
        "case_id": case.case_id,
        "generated_at": case.generated_at.isoformat(),
        "shell_schema_version": SHELL_JSON_SCHEMA_VERSION,
        "summary_schema_version": SUMMARY_JSON_SCHEMA_VERSION,
        "comparison_policy_schema_version": (COMPARISON_POLICY_SCHEMA_VERSION),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _case_metadata_from_json(text: str) -> dict[str, Any]:
    """Decode ``case.json`` into the fields needed to build a case."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BenchmarkCaseError(f"invalid case.json: {exc}") from exc

    _require_object(data, "case")
    _reject_unknown_keys(data, _CASE_KEYS, "case")
    _require_keys(data, _CASE_KEYS, "case")

    schema_version = data["schema_version"]
    if schema_version != CASE_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            f"unsupported case.schema_version: {schema_version!r}"
        )

    shell_version = data["shell_schema_version"]
    if shell_version != SHELL_JSON_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            f"unsupported case.shell_schema_version: {shell_version!r}"
        )

    summary_version = data["summary_schema_version"]
    if summary_version != SUMMARY_JSON_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            f"unsupported case.summary_schema_version: {summary_version!r}"
        )

    policy_version = data["comparison_policy_schema_version"]
    if policy_version != COMPARISON_POLICY_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            "unsupported case.comparison_policy_schema_version: "
            f"{policy_version!r}"
        )

    case_id = data["case_id"]
    if not isinstance(case_id, str) or not case_id:
        raise BenchmarkCaseError("case.case_id must be a non-empty string")

    generated_at_raw = data["generated_at"]
    if not isinstance(generated_at_raw, str):
        raise BenchmarkCaseError("case.generated_at must be an ISO-8601 string")
    try:
        generated_at = datetime.fromisoformat(generated_at_raw)
    except ValueError as exc:
        raise BenchmarkCaseError(
            f"case.generated_at is not a valid ISO-8601 datetime: {exc}"
        ) from exc
    _require_aware_datetime(generated_at, "case.generated_at")

    return {
        "case_id": case_id,
        "generated_at": generated_at,
    }


# --- xsd_validation.json encoding ---------------------------------------


def _xsd_validation_to_json(result: XsdValidationResult) -> str:
    """Encode one XSD validation result as a deterministic JSON string."""

    payload: dict[str, Any] = {
        "schema_version": XSD_VALIDATION_SCHEMA_VERSION,
        "is_valid": result.is_valid,
        "error": result.error,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _xsd_validation_from_json(text: str) -> XsdValidationResult:
    """Decode one XSD validation result from its JSON form."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BenchmarkCaseError(f"invalid xsd_validation.json: {exc}") from exc

    _require_object(data, "xsd_validation")
    _reject_unknown_keys(data, _XSD_VALIDATION_KEYS, "xsd_validation")
    _require_keys(data, _XSD_VALIDATION_KEYS, "xsd_validation")

    schema_version = data["schema_version"]
    if schema_version != XSD_VALIDATION_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            f"unsupported xsd_validation.schema_version: {schema_version!r}"
        )

    is_valid = data["is_valid"]
    if not isinstance(is_valid, bool):
        raise BenchmarkCaseError("xsd_validation.is_valid must be a boolean")

    error = data["error"]
    if error is not None and not isinstance(error, str):
        raise BenchmarkCaseError(
            "xsd_validation.error must be a string or null"
        )

    return XsdValidationResult(is_valid=is_valid, error=error)


# --- manifests -----------------------------------------------------------


def _load_manifests(
    directory: Path,
) -> dict[str, TemplateVisibilityManifest]:
    """Load every manifest under ``directory/manifests``."""

    manifests_dir = directory / _MANIFESTS_DIRECTORY
    if not manifests_dir.is_dir():
        raise BenchmarkCaseError(
            f"missing {_MANIFESTS_DIRECTORY} in benchmark case {directory}"
        )

    manifests: dict[str, TemplateVisibilityManifest] = {}
    for path in sorted(manifests_dir.glob("*.json")):
        try:
            manifest = manifest_from_json(path.read_text(encoding="utf-8"))
        except TemplateVisibilityError as exc:
            raise BenchmarkCaseError(
                f"failed to load {path.name}: {exc}"
            ) from exc
        if manifest.template_id != path.stem:
            raise BenchmarkCaseError(
                "manifest filename must match template_id: "
                f"{path.name!r} != {manifest.template_id!r}"
            )
        manifests[manifest.template_id] = manifest

    if NO_PDF_TEMPLATE_ID not in manifests:
        raise BenchmarkCaseError(
            f"missing {NO_PDF_TEMPLATE_ID}.json in benchmark case {manifests_dir}"
        )
    return manifests


# --- helpers -------------------------------------------------------------


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    """Raise unless ``value`` carries a concrete UTC offset."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise BenchmarkCaseError(f"{field_name} must be timezone-aware")


def _require_file(directory: Path, filename: str) -> None:
    """Raise if ``directory/filename`` is missing."""

    if not (directory / filename).is_file():
        raise BenchmarkCaseError(
            f"missing {filename} in benchmark case {directory}"
        )


def _require_object(data: Any, path: str) -> None:
    """Raise unless ``data`` is a JSON object (``dict``)."""

    if not isinstance(data, dict):
        raise BenchmarkCaseError(f"{path} payload must be a JSON object")


def _reject_unknown_keys(
    data: dict[str, Any],
    allowed: frozenset[str],
    path: str,
) -> None:
    """Raise if ``data`` carries any key outside ``allowed``."""

    extra = sorted(key for key in data if key not in allowed)
    if extra:
        raise BenchmarkCaseError(f"{path} payload has unknown keys: {extra}")


def _require_keys(
    data: dict[str, Any],
    required: frozenset[str],
    path: str,
) -> None:
    """Raise if any ``required`` key is absent from ``data``."""

    missing = sorted(required - data.keys())
    if missing:
        raise BenchmarkCaseError(
            f"{path} payload is missing required keys: {missing}"
        )
