"""Tests for the persisted agentic-repair benchmark corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.agentic_repair.benchmark_corpus import (
    AGENTIC_REPAIR_CORPUS_PATH,
    BenchmarkCorpusError,
    build_agent_payload,
    build_benchmark_corpus,
    corpus_to_json,
    load_benchmark_corpus,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / AGENTIC_REPAIR_CORPUS_PATH


def test_checked_in_corpus_has_declared_distribution() -> None:
    """The public benchmark should contain the approved 200-case mix."""

    corpus = load_benchmark_corpus(CORPUS_PATH)

    counts = Counter(case.category for case in corpus.cases)

    assert len(corpus.cases) == 200
    assert counts == {
        "single_repair": 80,
        "multi_repair": 40,
        "mixed": 40,
        "human_only": 20,
        "ambiguous": 20,
    }


def test_checked_in_corpus_matches_deterministic_builder() -> None:
    """Regeneration should reproduce the reviewed artifact byte for byte."""

    checked_in = CORPUS_PATH.read_text(encoding="utf-8")

    assert checked_in == corpus_to_json(build_benchmark_corpus())


def test_expected_candidate_positions_are_not_fixed() -> None:
    """Ground truth should not be learnable from one candidate position."""

    corpus = load_benchmark_corpus(CORPUS_PATH)
    expected_indexes = {
        field.expected_candidate_index
        for case in corpus.cases
        for field in case.fields
        if field.expected_candidate_index is not None
    }

    assert expected_indexes == {0, 1, 2}


def test_build_agent_payload_preserves_complete_candidate_evidence() -> None:
    """The live runner should receive every persisted candidate attribute."""

    corpus = load_benchmark_corpus(CORPUS_PATH)
    case = next(case for case in corpus.cases if case.fields)

    payload = build_agent_payload(case)

    assert len(payload.payload) == len(case.fields)
    for payload_field, benchmark_field in zip(
        payload.payload,
        case.fields,
        strict=True,
    ):
        assert payload_field.path == benchmark_field.path
        assert payload_field.current_value == benchmark_field.current_value
        assert [candidate.value for candidate in payload_field.candidates] == [
            candidate.value for candidate in benchmark_field.candidates
        ]
        assert [candidate.same_line_text for candidate in payload_field.candidates] == [
            candidate.same_line_text for candidate in benchmark_field.candidates
        ]


def test_loader_rejects_expected_index_outside_candidates(
    tmp_path: Path,
) -> None:
    """A malformed ground-truth index must fail before benchmark execution."""

    payload = {
        "schema_version": 1,
        "corpus_id": "broken",
        "cases": [
            {
                "case_id": "case-001",
                "category": "single_repair",
                "human_only_defects": 0,
                "fields": [
                    {
                        "path": "seller.nip",
                        "current_value": "bad",
                        "expected_candidate_index": 2,
                        "candidates": [
                            {
                                "value": "8637940261",
                                "confidence": 0.9,
                                "raw_text": "8637940261",
                                "same_line_text": "Sprzedawca NIP 8637940261",
                                "rule": "seller_label",
                                "rejected_by": None,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        BenchmarkCorpusError,
        match="expected_candidate_index",
    ):
        load_benchmark_corpus(path)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    """Case IDs are stable report keys and therefore must be unique."""

    case = {
        "case_id": "duplicate",
        "category": "human_only",
        "human_only_defects": 1,
        "fields": [],
    }
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "broken",
                "cases": [case, case],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkCorpusError, match="duplicate case_id"):
        load_benchmark_corpus(path)
