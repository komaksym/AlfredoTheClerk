"""Publication boundary for the held-out agentic-repair benchmark."""

from __future__ import annotations

from pathlib import Path

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCorpus,
    BenchmarkCorpusError,
    load_benchmark_corpus,
)


HEADLINE_CORPUS_ID = "agentic-repair-hard-v1"
HEADLINE_CORPUS_PATH = Path(
    "data/benchmark_cases/agentic_repair_hard_v1.json"
)
SANITY_CORPUS_PATH = Path(
    "data/benchmark_cases/agentic_repair_v1.json"
)


def load_headline_corpus(path: Path) -> BenchmarkCorpus:
    """Load and validate a corpus eligible for headline metrics."""

    corpus = load_benchmark_corpus(path)
    validate_headline_corpus(corpus)
    return corpus


def validate_headline_corpus(corpus: BenchmarkCorpus) -> None:
    """Reject generated or answer-leaking data from headline evaluation."""

    if corpus.corpus_id != HEADLINE_CORPUS_ID:
        raise BenchmarkCorpusError(
            "headline benchmark requires the held-out hard corpus"
        )
    if not corpus.cases:
        raise BenchmarkCorpusError("headline corpus must contain cases")

    for case in corpus.cases:
        for field in case.fields:
            for candidate in field.candidates:
                if candidate.rule is not None or candidate.rejected_by is not None:
                    raise BenchmarkCorpusError(
                        "headline corpus contains answer-leaking metadata"
                    )
