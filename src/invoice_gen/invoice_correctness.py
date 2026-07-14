"""Deterministic readiness checks for repaired domestic VAT invoices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ksef_schema.schemat import Faktura

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.domestic_vat_faktura_mapping import (
    FakturaMappingError,
    map_domestic_vat_shell_to_faktura,
)
from src.invoice_gen.domestic_vat_shell_summary import (
    DomesticVatInvoiceSummary,
    summarize_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_shell_validation import (
    ShellValidationResult,
    validate_domestic_vat_shell,
)
from src.invoice_gen.domestic_vat_xml_rendering import render_faktura_to_xml
from src.invoice_gen.fa3_xsd_validation import (
    XsdValidationError,
    XsdValidationResult,
    validate_xml_against_local_schema_bundle,
)


class CorrectnessStatus(Enum):
    """Terminal result of the local invoice correctness boundary."""

    READY_FOR_KSEF = "ready_for_ksef"
    INVALID_SHELL = "invalid_shell"
    TOTALS_MISMATCH = "totals_mismatch"
    FA3_MAPPING_FAILED = "fa3_mapping_failed"
    XML_SERIALIZATION_FAILED = "xml_serialization_failed"
    XSD_VALIDATION_FAILED = "xsd_validation_failed"


@dataclass(frozen=True, kw_only=True)
class TotalsMismatch:
    """One computed-versus-extracted monetary disagreement."""

    path: str
    computed: Decimal | None
    extracted: Decimal | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class CorrectnessResult:
    """Artifacts and diagnostics produced by the correctness boundary."""

    status: CorrectnessStatus
    shell: DomesticVatInvoiceShell
    validation: ShellValidationResult
    computed_summary: DomesticVatInvoiceSummary | None = None
    mismatches: tuple[TotalsMismatch, ...] = ()
    faktura: Faktura | None = None
    xml: str | None = None
    xsd_validation: XsdValidationResult | None = None
    error: str | None = None


def check_invoice_correctness(
    shell: DomesticVatInvoiceShell,
    extracted_summary: DomesticVatInvoiceSummary,
    generated_at: datetime | None = None,
) -> CorrectnessResult:
    """Check whether one canonical invoice is locally KSeF-ready."""

    validation = validate_domestic_vat_shell(shell)
    if not validation.is_valid:
        return CorrectnessResult(
            status=CorrectnessStatus.INVALID_SHELL,
            shell=shell,
            validation=validation,
        )

    computed = summarize_domestic_vat_shell(shell)
    mismatches = _reconcile_totals(computed, extracted_summary)
    if mismatches:
        return CorrectnessResult(
            status=CorrectnessStatus.TOTALS_MISMATCH,
            shell=shell,
            validation=validation,
            computed_summary=computed,
            mismatches=mismatches,
        )

    try:
        faktura = map_domestic_vat_shell_to_faktura(
            shell,
            computed,
            generated_at=generated_at,
        )
    except FakturaMappingError as exc:
        return CorrectnessResult(
            status=CorrectnessStatus.FA3_MAPPING_FAILED,
            shell=shell,
            validation=validation,
            computed_summary=computed,
            error=str(exc),
        )

    try:
        xml = render_faktura_to_xml(faktura)
    except Exception as exc:
        return CorrectnessResult(
            status=CorrectnessStatus.XML_SERIALIZATION_FAILED,
            shell=shell,
            validation=validation,
            computed_summary=computed,
            faktura=faktura,
            error=str(exc),
        )

    try:
        xsd_validation = validate_xml_against_local_schema_bundle(xml)
    except XsdValidationError as exc:
        return CorrectnessResult(
            status=CorrectnessStatus.XSD_VALIDATION_FAILED,
            shell=shell,
            validation=validation,
            computed_summary=computed,
            faktura=faktura,
            xml=xml,
            error=str(exc),
        )

    if not xsd_validation.is_valid:
        return CorrectnessResult(
            status=CorrectnessStatus.XSD_VALIDATION_FAILED,
            shell=shell,
            validation=validation,
            computed_summary=computed,
            faktura=faktura,
            xml=xml,
            xsd_validation=xsd_validation,
            error=xsd_validation.error,
        )

    return CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=shell,
        validation=validation,
        computed_summary=computed,
        faktura=faktura,
        xml=xml,
        xsd_validation=xsd_validation,
    )


def _reconcile_totals(
    computed: DomesticVatInvoiceSummary,
    extracted: DomesticVatInvoiceSummary,
) -> tuple[TotalsMismatch, ...]:
    """Return deterministic monetary disagreements without mutating inputs."""

    mismatches: list[TotalsMismatch] = []
    invoice_fields = (
        "invoice_net_total",
        "invoice_vat_total",
        "invoice_gross_total",
    )
    for field in invoice_fields:
        _compare_value(
            mismatches,
            path=f"summary.{field}",
            computed=getattr(computed, field),
            extracted=getattr(extracted, field),
        )

    rates = sorted(
        computed.bucket_summaries.keys() | extracted.bucket_summaries.keys()
    )
    for rate in rates:
        path = f"summary.bucket_summaries[{format(rate, 'f')}]"
        computed_bucket = computed.bucket_summaries.get(rate)
        extracted_bucket = extracted.bucket_summaries.get(rate)

        if computed_bucket is None:
            mismatches.append(
                TotalsMismatch(
                    path=path,
                    computed=None,
                    extracted=None,
                    reason="unexpected_extracted_bucket",
                )
            )
            continue

        if extracted_bucket is None:
            mismatches.append(
                TotalsMismatch(
                    path=path,
                    computed=None,
                    extracted=None,
                    reason="missing_extracted_bucket",
                )
            )
            continue

        for field in ("net_total", "vat_total", "gross_total"):
            _compare_value(
                mismatches,
                path=f"{path}.{field}",
                computed=getattr(computed_bucket, field),
                extracted=getattr(extracted_bucket, field),
            )

    return tuple(mismatches)


def _compare_value(
    mismatches: list[TotalsMismatch],
    *,
    path: str,
    computed: Decimal,
    extracted: Decimal | None,
) -> None:
    """Append one missing or unequal extracted value."""

    if extracted is None:
        mismatches.append(
            TotalsMismatch(
                path=path,
                computed=computed,
                extracted=None,
                reason="missing_extracted_value",
            )
        )
    elif extracted != computed:
        mismatches.append(
            TotalsMismatch(
                path=path,
                computed=computed,
                extracted=extracted,
                reason="value_mismatch",
            )
        )
