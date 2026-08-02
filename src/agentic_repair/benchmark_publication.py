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
    """Load a corpus after verifying that it is safe for headline reporting.

    First applies the generic persisted-corpus schema validation, then enforces
    the stricter publication boundary for the held-out hard split. Returns the
    validated corpus; any file, schema, corpus-identity, emptiness, or answer-
    leakage violation propagates as BenchmarkCorpusError.
    """

    corpus = load_benchmark_corpus(path)
    validate_headline_corpus(corpus)
    return corpus


def validate_headline_corpus(corpus: BenchmarkCorpus) -> None:
    """Enforce the non-leaking contract for headline benchmark data.

    Requires the dedicated held-out corpus ID, at least one case, and no
    candidate rule or rejected_by metadata anywhere in the corpus. Those fields
    can reveal the expected answer, so their presence makes the corpus
    ineligible and raises BenchmarkCorpusError.
    """

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
