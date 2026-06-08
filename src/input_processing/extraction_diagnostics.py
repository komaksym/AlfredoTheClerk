"""Post-extraction diagnostics classifying evidence into field statuses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .invoice_text_field_extraction import FieldEvidence


class FieldStatus(Enum):
    """Machine status assigned to a field after deterministic extraction.

    PRESENT means the field resolved to a usable value or an observed blank.
    MISSING means no candidate was found. AMBIGUOUS means candidates or a
    location were found but no winner could be selected. NORMALIZED means the
    stored value differs from raw PDF text after parser cleanup.
    """

    PRESENT = "present"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    NORMALIZED = "normalized"


@dataclass(frozen=True, kw_only=True)
class FieldDiagnostic:
    """Status, raw text, and explanation for one extracted field path."""

    path: str
    status: FieldStatus
    raw_text: str | None
    message: str | None


@dataclass(kw_only=True)
class ExtractionDiagnostics:
    """Per-field extraction statuses used to route repair work.

    This object describes whether each extracted field is present, missing,
    ambiguous, or normalized. It does not validate business rules; validation
    lives in ``ShellValidationResult``.
    """

    fields: dict[str, FieldDiagnostic] = field(default_factory=dict)

    @property
    def missing_paths(self) -> list[str]:
        """Sorted paths of fields with no extraction candidate."""

        return sorted(
            p for p, d in self.fields.items() if d.status is FieldStatus.MISSING
        )

    @property
    def ambiguous_paths(self) -> list[str]:
        """Sorted paths of fields with unresolvable candidates."""

        return sorted(
            p
            for p, d in self.fields.items()
            if d.status is FieldStatus.AMBIGUOUS
        )

    @property
    def normalized_paths(self) -> list[str]:
        """Sorted paths of fields whose values were transformed."""

        return sorted(
            p
            for p, d in self.fields.items()
            if d.status is FieldStatus.NORMALIZED
        )


def build_extraction_diagnostics(
    evidence: dict[str, FieldEvidence],
) -> ExtractionDiagnostics:
    """Classify each evidence entry into a field diagnostic."""

    fields: dict[str, FieldDiagnostic] = {}

    for path, ev in evidence.items():
        fields[path] = _classify_field(path, ev)

    return ExtractionDiagnostics(fields=fields)


def _classify_field(path: str, ev: FieldEvidence) -> FieldDiagnostic:
    """Determine the diagnostic status for one evidence entry."""

    if ev.source == "unresolved" and ev.value is None:
        # Optional blank fields can be confidently observed as intentionally empty.
        if ev.confidence >= 1.0:
            return FieldDiagnostic(
                path=path,
                status=FieldStatus.PRESENT,
                raw_text=ev.raw_text,
                message=None,
            )

        if ev.bbox is not None:
            return FieldDiagnostic(
                path=path,
                status=FieldStatus.AMBIGUOUS,
                raw_text=ev.raw_text,
                message="candidates found but could not be resolved",
            )

        return FieldDiagnostic(
            path=path,
            status=FieldStatus.MISSING,
            raw_text=None,
            message="no extraction candidate found",
        )

    if (
        ev.raw_text is not None
        and ev.value is not None
        and str(ev.value) != ev.raw_text
    ):
        return FieldDiagnostic(
            path=path,
            status=FieldStatus.NORMALIZED,
            raw_text=ev.raw_text,
            message="value was normalized from raw extraction",
        )

    return FieldDiagnostic(
        path=path,
        status=FieldStatus.PRESENT,
        raw_text=ev.raw_text,
        message=None,
    )
