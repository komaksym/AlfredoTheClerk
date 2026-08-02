"""Tests for the persisted agentic-repair benchmark corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCorpusError,
    build_agent_payload,
    build_benchmark_corpus,
    corpus_to_json,
    load_benchmark_corpus,
)
from src.agentic_repair.benchmark_publication import (
    HEADLINE_CORPUS_ID,
    HEADLINE_CORPUS_PATH,
    SANITY_CORPUS_PATH,
    load_headline_corpus,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_IN_HEADLINE_CORPUS_PATH = REPO_ROOT / HEADLINE_CORPUS_PATH
CHECKED_IN_SANITY_CORPUS_PATH = REPO_ROOT / SANITY_CORPUS_PATH


def test_checked_in_headline_corpus_has_curated_distribution() -> None:
    """Headline metrics should use the separately authored hard split."""

    corpus = load_headline_corpus(CHECKED_IN_HEADLINE_CORPUS_PATH)
    counts = Counter(case.category for case in corpus.cases)

    assert corpus.corpus_id == HEADLINE_CORPUS_ID
    assert len(corpus.cases) == 30
    assert counts == {
        "single_repair": 12,
        "multi_repair": 6,
        "mixed": 6,
        "human_only": 3,
        "ambiguous": 3,
    }


def test_generated_sanity_corpus_has_declared_distribution() -> None:
    """The original 200 generated cases remain a tool-contract sanity split."""

    corpus = load_benchmark_corpus(CHECKED_IN_SANITY_CORPUS_PATH)
    counts = Counter(case.category for case in corpus.cases)

    assert len(corpus.cases) == 200
    assert counts == {
        "single_repair": 80,
        "multi_repair": 40,
        "mixed": 40,
        "human_only": 20,
        "ambiguous": 20,
    }


def test_checked_in_sanity_corpus_matches_deterministic_builder() -> None:
    """Regeneration should reproduce only the generated sanity artifact."""

    checked_in = CHECKED_IN_SANITY_CORPUS_PATH.read_text(encoding="utf-8")

    assert checked_in == corpus_to_json(build_benchmark_corpus())


def test_headline_corpus_hides_answer_metadata() -> None:
    """Expected choices must not be exposed through rules or rejection flags."""

    corpus = load_headline_corpus(CHECKED_IN_HEADLINE_CORPUS_PATH)
    candidates = [
        candidate
        for case in corpus.cases
        for field in case.fields
        for candidate in field.candidates
    ]

    assert candidates
    assert all(candidate.rule is None for candidate in candidates)
    assert all(candidate.rejected_by is None for candidate in candidates)


def test_headline_ground_truth_is_not_candidate_position_or_confidence() -> None:
    """The hard split should require context rather than one index or score."""

    corpus = load_headline_corpus(CHECKED_IN_HEADLINE_CORPUS_PATH)
    fields = [
        field
        for case in corpus.cases
        for field in case.fields
        if field.expected_candidate_index is not None
    ]
    expected_indexes = {field.expected_candidate_index for field in fields}
    correct_confidence_ranks = []
    for field in fields:
        expected_index = field.expected_candidate_index
        assert expected_index is not None
        ordered = sorted(
            range(len(field.candidates)),
            key=lambda index: field.candidates[index].confidence,
            reverse=True,
        )
        correct_confidence_ranks.append(ordered.index(expected_index) + 1)

    assert expected_indexes == {0, 1, 2}
    assert set(correct_confidence_ranks) == {1, 2, 3}


def test_build_agent_payload_preserves_complete_candidate_evidence() -> None:
    """The live runner should receive every persisted candidate attribute."""

    corpus = load_headline_corpus(CHECKED_IN_HEADLINE_CORPUS_PATH)
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


def test_loader_rejects_answer_leaking_headline_metadata(
    tmp_path: Path,
) -> None:
    """A headline corpus cannot expose the expected field role as a rule."""

    payload = {
        "schema_version": 1,
        "corpus_id": HEADLINE_CORPUS_ID,
        "cases": [
            {
                "case_id": "case-001",
                "category": "single_repair",
                "human_only_defects": 0,
                "fields": [
                    {
                        "path": "seller.nip",
                        "current_value": "bad",
                        "expected_candidate_index": 0,
                        "candidates": [
                            {
                                "value": "8637940261",
                                "confidence": 0.9,
                                "raw_text": "8637940261",
                                "same_line_text": "Wystawca 8637940261",
                                "rule": "seller_nip_label",
                                "rejected_by": None,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "headline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BenchmarkCorpusError, match="answer-leaking metadata"):
        load_headline_corpus(path)


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
