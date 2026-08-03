"""Tests for headline benchmark publication invariants."""

from __future__ import annotations

import pytest

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCandidate,
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkCorpusError,
    BenchmarkField,
)
from src.agentic_repair.benchmark_publication import (
    HEADLINE_CORPUS_ID,
    validate_headline_corpus,
)


@pytest.mark.parametrize(
    ("path", "value", "expected_message"),
    [
        ("seller.nip", "1234567890", "NIP validation"),
        (
            "seller.bank_account",
            "PL22222222222222222222222222",
            "PL IBAN validation",
        ),
    ],
)
def test_headline_corpus_rejects_domain_invalid_candidates(
    path: str,
    value: str,
    expected_message: str,
) -> None:
    """Reject NIP and IBAN candidates production extraction would discard."""

    corpus = BenchmarkCorpus(
        schema_version=1,
        corpus_id=HEADLINE_CORPUS_ID,
        cases=(
            BenchmarkCase(
                case_id="invalid-domain-value",
                category="single_repair",
                human_only_defects=0,
                fields=(
                    BenchmarkField(
                        path=path,
                        current_value="invalid",
                        expected_candidate_index=0,
                        candidates=(
                            BenchmarkCandidate(
                                value=value,
                                confidence=0.9,
                                raw_text=value,
                                same_line_text=value,
                                rule=None,
                                rejected_by=None,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(BenchmarkCorpusError, match=expected_message):
        validate_headline_corpus(corpus)
