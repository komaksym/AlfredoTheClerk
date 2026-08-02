"""Persisted synthetic scenarios for the agentic-repair benchmark."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from src.agentic_repair.repair_payload import (
    AgentRepairCandidate,
    AgentRepairField,
    AgentRepairPayload,
)
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationError


CORPUS_SCHEMA_VERSION = 1
CORPUS_ID = "agentic-repair-v1"
AGENTIC_REPAIR_CORPUS_PATH = Path(
    "data/benchmark_cases/agentic_repair_v1.json"
)

_CATEGORY_COUNTS = {
    "single_repair": 80,
    "multi_repair": 40,
    "mixed": 40,
    "human_only": 20,
    "ambiguous": 20,
}
_FIELD_PATHS = (
    "seller.nip",
    "buyer.nip",
    "invoice_number",
    "issue_date",
    "sale_date",
    "payment_due_date",
    "seller.bank_account",
)
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)

_CORPUS_KEYS = frozenset({"schema_version", "corpus_id", "cases"})
_CASE_KEYS = frozenset(
    {"case_id", "category", "human_only_defects", "fields"}
)
_FIELD_KEYS = frozenset(
    {
        "path",
        "current_value",
        "expected_candidate_index",
        "candidates",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "value",
        "confidence",
        "raw_text",
        "same_line_text",
        "rule",
        "rejected_by",
    }
)


class BenchmarkCorpusError(ValueError):
    """Raised when a persisted benchmark corpus violates its contract."""


@dataclass(frozen=True, kw_only=True)
class BenchmarkCandidate:
    """One agent-visible repair candidate."""

    value: object
    confidence: float
    raw_text: str | None
    same_line_text: str | None
    rule: str | None
    rejected_by: str | None


@dataclass(frozen=True, kw_only=True)
class BenchmarkField:
    """One corrupted field and its deterministic expected action."""

    path: str
    current_value: object
    expected_candidate_index: int | None
    candidates: tuple[BenchmarkCandidate, ...]


@dataclass(frozen=True, kw_only=True)
class BenchmarkCase:
    """One persisted repair decision scenario."""

    case_id: str
    category: str
    human_only_defects: int
    fields: tuple[BenchmarkField, ...]


@dataclass(frozen=True, kw_only=True)
class BenchmarkCorpus:
    """Versioned collection of agentic-repair scenarios."""

    schema_version: int
    corpus_id: str
    cases: tuple[BenchmarkCase, ...]


def load_benchmark_corpus(path: Path) -> BenchmarkCorpus:
    """Load and strictly validate one persisted benchmark corpus."""

    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkCorpusError(f"cannot read corpus: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkCorpusError(f"invalid corpus JSON: {exc}") from exc

    _require_object(raw_payload, "corpus")
    payload = cast(dict[str, Any], raw_payload)
    _require_exact_keys(payload, _CORPUS_KEYS, "corpus")

    schema_version = payload["schema_version"]
    if schema_version != CORPUS_SCHEMA_VERSION:
        raise BenchmarkCorpusError(
            f"unsupported corpus.schema_version: {schema_version!r}"
        )

    corpus_id = payload["corpus_id"]
    if not isinstance(corpus_id, str) or not corpus_id:
        raise BenchmarkCorpusError("corpus.corpus_id must be non-empty")

    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list):
        raise BenchmarkCorpusError("corpus.cases must be a list")

    cases = tuple(
        _case_from_mapping(item, index=index)
        for index, item in enumerate(raw_cases)
    )
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkCorpusError("duplicate case_id in corpus")

    return BenchmarkCorpus(
        schema_version=schema_version,
        corpus_id=corpus_id,
        cases=cases,
    )


def corpus_to_json(corpus: BenchmarkCorpus) -> str:
    """Serialize a benchmark corpus deterministically."""

    payload = {
        "schema_version": corpus.schema_version,
        "corpus_id": corpus.corpus_id,
        "cases": [_case_to_mapping(case) for case in corpus.cases],
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def build_agent_payload(case: BenchmarkCase) -> AgentRepairPayload:
    """Project one persisted case into the production agent payload."""

    fields: list[AgentRepairField] = []
    for field in case.fields:
        candidates = tuple(
            AgentRepairCandidate(
                index=index,
                value=candidate.value,
                confidence=candidate.confidence,
                raw_text=candidate.raw_text,
                same_line_text=candidate.same_line_text,
                rule=candidate.rule,
                rejected_by=candidate.rejected_by,
            )
            for index, candidate in enumerate(field.candidates)
        )
        fields.append(
            AgentRepairField(
                path=field.path,
                current_value=field.current_value,
                diagnostic_status=None,
                validation_errors=(
                    ShellValidationError(
                        path=field.path,
                        code="synthetic_corruption",
                        message=f"{field.path} requires repair",
                    ),
                ),
                candidates=candidates,
            )
        )
    return AgentRepairPayload(payload=tuple(fields))


def build_benchmark_corpus() -> BenchmarkCorpus:
    """Build the deterministic v1 corpus for intentional regeneration."""

    rng = random.Random(20260802)
    cases: list[BenchmarkCase] = []
    serial = 1

    for index in range(_CATEGORY_COUNTS["single_repair"]):
        path = _FIELD_PATHS[index % len(_FIELD_PATHS)]
        cases.append(
            BenchmarkCase(
                case_id=f"single-{index + 1:03d}",
                category="single_repair",
                human_only_defects=0,
                fields=(
                    _build_field(
                        path=path,
                        serial=serial,
                        rng=rng,
                    ),
                ),
            )
        )
        serial += 1

    for index in range(_CATEGORY_COUNTS["multi_repair"]):
        field_count = 3 if index % 4 == 0 else 2
        fields: list[BenchmarkField] = []
        for path in _pick_paths(index, field_count):
            fields.append(
                _build_field(
                    path=path,
                    serial=serial,
                    rng=rng,
                )
            )
            serial += 1
        cases.append(
            BenchmarkCase(
                case_id=f"multi-{index + 1:03d}",
                category="multi_repair",
                human_only_defects=0,
                fields=tuple(fields),
            )
        )

    for index in range(_CATEGORY_COUNTS["mixed"]):
        field_count = 2 if index % 3 == 0 else 1
        fields = []
        for path in _pick_paths(index + 2, field_count):
            fields.append(
                _build_field(
                    path=path,
                    serial=serial,
                    rng=rng,
                )
            )
            serial += 1
        cases.append(
            BenchmarkCase(
                case_id=f"mixed-{index + 1:03d}",
                category="mixed",
                human_only_defects=1 + (index % 2),
                fields=tuple(fields),
            )
        )

    for index in range(_CATEGORY_COUNTS["human_only"]):
        cases.append(
            BenchmarkCase(
                case_id=f"human-{index + 1:03d}",
                category="human_only",
                human_only_defects=1 + (index % 3),
                fields=(),
            )
        )

    for index in range(_CATEGORY_COUNTS["ambiguous"]):
        path = _FIELD_PATHS[(index + 4) % len(_FIELD_PATHS)]
        cases.append(
            BenchmarkCase(
                case_id=f"ambiguous-{index + 1:03d}",
                category="ambiguous",
                human_only_defects=0,
                fields=(
                    _build_field(
                        path=path,
                        serial=serial,
                        rng=rng,
                        ambiguous=True,
                    ),
                ),
            )
        )
        serial += 1

    return BenchmarkCorpus(
        schema_version=CORPUS_SCHEMA_VERSION,
        corpus_id=CORPUS_ID,
        cases=tuple(cases),
    )


def _case_from_mapping(item: object, *, index: int) -> BenchmarkCase:
    """Decode and validate one case mapping."""

    label = f"corpus.cases[{index}]"
    _require_object(item, label)
    mapping = cast(dict[str, Any], item)
    _require_exact_keys(mapping, _CASE_KEYS, label)

    case_id = mapping["case_id"]
    if not isinstance(case_id, str) or not case_id:
        raise BenchmarkCorpusError(f"{label}.case_id must be non-empty")

    category = mapping["category"]
    if category not in _CATEGORY_COUNTS:
        raise BenchmarkCorpusError(f"{label}.category is unsupported")

    human_only_defects = mapping["human_only_defects"]
    if (
        not isinstance(human_only_defects, int)
        or isinstance(human_only_defects, bool)
        or human_only_defects < 0
    ):
        raise BenchmarkCorpusError(
            f"{label}.human_only_defects must be a non-negative integer"
        )

    raw_fields = mapping["fields"]
    if not isinstance(raw_fields, list):
        raise BenchmarkCorpusError(f"{label}.fields must be a list")
    fields = tuple(
        _field_from_mapping(field, label=f"{label}.fields[{field_index}]")
        for field_index, field in enumerate(raw_fields)
    )

    paths = [field.path for field in fields]
    if len(paths) != len(set(paths)):
        raise BenchmarkCorpusError(f"{label} contains duplicate field paths")

    _validate_category_shape(
        category=category,
        fields=fields,
        human_only_defects=human_only_defects,
        label=label,
    )
    return BenchmarkCase(
        case_id=case_id,
        category=category,
        human_only_defects=human_only_defects,
        fields=fields,
    )


def _field_from_mapping(item: object, *, label: str) -> BenchmarkField:
    """Decode and validate one field mapping."""

    _require_object(item, label)
    mapping = cast(dict[str, Any], item)
    _require_exact_keys(mapping, _FIELD_KEYS, label)

    path = mapping["path"]
    if not isinstance(path, str) or not path:
        raise BenchmarkCorpusError(f"{label}.path must be non-empty")
    current_value = _require_json_scalar(
        mapping["current_value"],
        f"{label}.current_value",
        allow_none=True,
    )

    raw_candidates = mapping["candidates"]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise BenchmarkCorpusError(
            f"{label}.candidates must be a non-empty list"
        )
    candidates = tuple(
        _candidate_from_mapping(
            candidate,
            label=f"{label}.candidates[{candidate_index}]",
        )
        for candidate_index, candidate in enumerate(raw_candidates)
    )

    expected_index = mapping["expected_candidate_index"]
    if expected_index is not None:
        if (
            not isinstance(expected_index, int)
            or isinstance(expected_index, bool)
            or not 0 <= expected_index < len(candidates)
        ):
            raise BenchmarkCorpusError(
                f"{label}.expected_candidate_index is outside candidates"
            )

    return BenchmarkField(
        path=path,
        current_value=current_value,
        expected_candidate_index=expected_index,
        candidates=candidates,
    )


def _candidate_from_mapping(
    item: object,
    *,
    label: str,
) -> BenchmarkCandidate:
    """Decode and validate one candidate mapping."""

    _require_object(item, label)
    mapping = cast(dict[str, Any], item)
    _require_exact_keys(mapping, _CANDIDATE_KEYS, label)

    confidence = mapping["confidence"]
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise BenchmarkCorpusError(
            f"{label}.confidence must be between zero and one"
        )

    return BenchmarkCandidate(
        value=_require_json_scalar(
            mapping["value"],
            f"{label}.value",
            allow_none=False,
        ),
        confidence=float(confidence),
        raw_text=_require_optional_string(
            mapping["raw_text"], label, "raw_text"
        ),
        same_line_text=_require_optional_string(
            mapping["same_line_text"],
            label,
            "same_line_text",
        ),
        rule=_require_optional_string(mapping["rule"], label, "rule"),
        rejected_by=_require_optional_string(
            mapping["rejected_by"],
            label,
            "rejected_by",
        ),
    )


def _validate_category_shape(
    *,
    category: str,
    fields: tuple[BenchmarkField, ...],
    human_only_defects: int,
    label: str,
) -> None:
    """Enforce the declared v1 case-category semantics."""

    expected_indexes = tuple(
        field.expected_candidate_index for field in fields
    )
    if category == "single_repair":
        valid = (
            len(fields) == 1
            and expected_indexes[0] is not None
            and human_only_defects == 0
        )
    elif category == "multi_repair":
        valid = (
            len(fields) >= 2
            and all(index is not None for index in expected_indexes)
            and human_only_defects == 0
        )
    elif category == "mixed":
        valid = (
            bool(fields)
            and all(index is not None for index in expected_indexes)
            and human_only_defects > 0
        )
    elif category == "human_only":
        valid = not fields and human_only_defects > 0
    else:
        valid = (
            bool(fields)
            and all(index is None for index in expected_indexes)
            and human_only_defects == 0
        )

    if not valid:
        raise BenchmarkCorpusError(
            f"{label} does not match category {category!r}"
        )


def _case_to_mapping(case: BenchmarkCase) -> dict[str, Any]:
    """Encode one benchmark case as JSON-compatible data."""

    return {
        "case_id": case.case_id,
        "category": case.category,
        "human_only_defects": case.human_only_defects,
        "fields": [
            {
                "path": field.path,
                "current_value": field.current_value,
                "expected_candidate_index": field.expected_candidate_index,
                "candidates": [
                    {
                        "value": candidate.value,
                        "confidence": candidate.confidence,
                        "raw_text": candidate.raw_text,
                        "same_line_text": candidate.same_line_text,
                        "rule": candidate.rule,
                        "rejected_by": candidate.rejected_by,
                    }
                    for candidate in field.candidates
                ],
            }
            for field in case.fields
        ],
    }


def _build_field(
    *,
    path: str,
    serial: int,
    rng: random.Random,
    ambiguous: bool = False,
) -> BenchmarkField:
    """Build one complete field scenario and randomize candidate order."""

    current, values, labels, rules = _field_semantics(path, serial)
    patterns = (
        (0.82, 0.96, 0.88),
        (0.97, 0.84, 0.91),
        (0.89, 0.93, 0.98),
    )
    confidences = patterns[serial % len(patterns)]
    candidates: list[BenchmarkCandidate] = []

    for index, value in enumerate(values):
        if ambiguous:
            same_line_text = f"Stopka dokumentu | identyfikator: {value}"
            rule = "unanchored_candidate"
            rejected_by = "missing_required_anchor"
        else:
            same_line_text = labels[index].format(value)
            rule = rules[index]
            rejected_by = None
        candidates.append(
            BenchmarkCandidate(
                value=value,
                confidence=confidences[index],
                raw_text=str(value),
                same_line_text=same_line_text,
                rule=rule,
                rejected_by=rejected_by,
            )
        )

    expected_rule = None if ambiguous else rules[0]
    rng.shuffle(candidates)
    expected_index = (
        None
        if expected_rule is None
        else next(
            index
            for index, candidate in enumerate(candidates)
            if candidate.rule == expected_rule
        )
    )
    return BenchmarkField(
        path=path,
        current_value=current,
        expected_candidate_index=expected_index,
        candidates=tuple(candidates),
    )


def _field_semantics(
    path: str,
    serial: int,
) -> tuple[
    object,
    tuple[object, object, object],
    tuple[str, str, str],
    tuple[str, str, str],
]:
    """Return current value and semantic candidate triples for one path."""

    if path == "seller.nip":
        return (
            "0000000000",
            (
                _build_nip(10_000 + serial * 3),
                _build_nip(10_001 + serial * 3),
                _build_nip(10_002 + serial * 3),
            ),
            (
                "Sprzedawca | NIP: {}",
                "Nabywca | NIP: {}",
                "Płatnik | NIP: {}",
            ),
            (
                "seller_nip_label",
                "buyer_nip_label",
                "payer_nip_label",
            ),
        )
    if path == "buyer.nip":
        return (
            "0000000000",
            (
                _build_nip(20_000 + serial * 3),
                _build_nip(20_001 + serial * 3),
                _build_nip(20_002 + serial * 3),
            ),
            (
                "Nabywca | NIP: {}",
                "Sprzedawca | NIP: {}",
                "Płatnik | NIP: {}",
            ),
            (
                "buyer_nip_label",
                "seller_nip_label",
                "payer_nip_label",
            ),
        )
    if path == "invoice_number":
        return (
            "UNKNOWN",
            (
                f"FV/2026/{serial:04d}",
                f"PO/2026/{serial:04d}",
                f"WZ/2026/{serial:04d}",
            ),
            (
                "Faktura VAT nr {}",
                "Zamówienie nr {}",
                "Dokument WZ nr {}",
            ),
            (
                "invoice_number_label",
                "purchase_order_label",
                "delivery_note_label",
            ),
        )
    if path == "issue_date":
        day = (serial % 25) + 1
        return (
            "not-a-date",
            (
                f"2026-06-{day:02d}",
                f"2026-06-{min(day + 1, 28):02d}",
                f"2026-06-{min(day + 14, 28):02d}",
            ),
            (
                "Data wystawienia: {}",
                "Data sprzedaży: {}",
                "Termin płatności: {}",
            ),
            (
                "issue_date_label",
                "sale_date_label",
                "payment_due_date_label",
            ),
        )
    if path == "sale_date":
        day = (serial % 25) + 1
        return (
            "not-a-date",
            (
                f"2026-05-{day:02d}",
                f"2026-05-{min(day + 1, 28):02d}",
                f"2026-05-{min(day + 14, 28):02d}",
            ),
            (
                "Data sprzedaży: {}",
                "Data wystawienia: {}",
                "Termin płatności: {}",
            ),
            (
                "sale_date_label",
                "issue_date_label",
                "payment_due_date_label",
            ),
        )
    if path == "payment_due_date":
        day = (serial % 14) + 1
        return (
            "not-a-date",
            (
                f"2026-07-{day + 14:02d}",
                f"2026-07-{day:02d}",
                f"2026-07-{day + 1:02d}",
            ),
            (
                "Termin płatności: {}",
                "Data wystawienia: {}",
                "Data sprzedaży: {}",
            ),
            (
                "payment_due_date_label",
                "issue_date_label",
                "sale_date_label",
            ),
        )
    if path == "seller.bank_account":
        return (
            "PL00INVALID",
            (
                _build_iban(30_000 + serial * 3),
                _build_iban(30_001 + serial * 3),
                _build_iban(30_002 + serial * 3),
            ),
            (
                "Rachunek sprzedawcy: {}",
                "Rachunek nabywcy: {}",
                "Numer referencyjny: {}",
            ),
            (
                "seller_bank_account_label",
                "buyer_bank_account_label",
                "reference_number_label",
            ),
        )
    raise AssertionError(f"unsupported benchmark field path: {path}")


def _pick_paths(start: int, count: int) -> tuple[str, ...]:
    """Return distinct field paths from a deterministic rotation."""

    return tuple(
        _FIELD_PATHS[(start + offset) % len(_FIELD_PATHS)]
        for offset in range(count)
    )


def _build_nip(seed: int) -> str:
    """Build one checksum-valid Polish NIP candidate."""

    rng = random.Random(seed)
    while True:
        prefix = [str(rng.randint(0, 9)) for _ in range(9)]
        checksum = sum(
            int(digit) * weight
            for digit, weight in zip(prefix, _NIP_WEIGHTS, strict=True)
        ) % 11
        if checksum == 10:
            continue
        nip = "".join(prefix) + str(checksum)
        if nip[0] != "0":
            return nip


def _build_iban(seed: int) -> str:
    """Build one checksum-valid Polish IBAN candidate."""

    rng = random.Random(seed)
    bban = "".join(str(rng.randint(0, 9)) for _ in range(24))
    partial = int(bban + "2521")
    check = (1 - partial * 100) % 97
    return f"PL{check:02d}{bban}"


def _require_object(value: object, label: str) -> None:
    """Raise unless ``value`` is a JSON object."""

    if not isinstance(value, dict):
        raise BenchmarkCorpusError(f"{label} must be an object")


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    """Reject missing and unknown keys in one JSON object."""

    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise BenchmarkCorpusError(
            f"{label} keys mismatch; missing={missing}, unknown={unknown}"
        )


def _require_json_scalar(
    value: object,
    label: str,
    *,
    allow_none: bool,
) -> object:
    """Return one JSON scalar or raise for containers and forbidden nulls."""

    if value is None:
        if allow_none:
            return None
        raise BenchmarkCorpusError(f"{label} must not be null")
    if not isinstance(value, (str, int, float, bool)):
        raise BenchmarkCorpusError(f"{label} must be a JSON scalar")
    return value


def _require_optional_string(
    value: object,
    label: str,
    field_name: str,
) -> str | None:
    """Return a string-or-null candidate metadata field."""

    if value is not None and not isinstance(value, str):
        raise BenchmarkCorpusError(
            f"{label}.{field_name} must be a string or null"
        )
    return value
