"""Publication boundary for the held-out agentic-repair benchmark."""

from __future__ import annotations

from pathlib import Path

from src.agentic_repair.benchmark_corpus import (
    BenchmarkCorpus,
    BenchmarkCorpusError,
    load_benchmark_corpus,
)
from src.input_processing.invoice_text_field_extraction import (
    validate_nip_checksum,
    validate_pl_iban_checksum,
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
    validated corpus; any file, schema, corpus-identity, emptiness, answer-
    leakage, or production-domain violation propagates as BenchmarkCorpusError.
    """

    corpus = load_benchmark_corpus(path)
    validate_headline_corpus(corpus)
    return corpus


def validate_headline_corpus(corpus: BenchmarkCorpus) -> None:
    """Enforce the non-leaking and domain-valid headline-data contract.

    Requires the dedicated held-out corpus ID, at least one case, no candidate
    rule or rejected_by metadata, and production-valid values for every NIP and
    PL-IBAN candidate. Headline candidates cannot be marked rejected, so values
    the production evidence pipeline would discard are ineligible here too.
    """

    if corpus.corpus_id != HEADLINE_CORPUS_ID:
        raise BenchmarkCorpusError(
            "headline benchmark requires the held-out hard corpus"
        )
    if not corpus.cases:
        raise BenchmarkCorpusError("headline corpus must contain cases")

    for case in corpus.cases:
        for field in case.fields:
            for candidate_index, candidate in enumerate(field.candidates):
                if candidate.rule is not None or candidate.rejected_by is not None:
                    raise BenchmarkCorpusError(
                        "headline corpus contains answer-leaking metadata"
                    )

                value = candidate.value
                location = (
                    f"{case.case_id} {field.path} candidate {candidate_index}"
                )
                if field.path in {"seller.nip", "buyer.nip"} and (
                    not isinstance(value, str)
                    or not validate_nip_checksum(value)
                ):
                    raise BenchmarkCorpusError(
                        f"{location} fails production NIP validation"
                    )
                if field.path == "seller.bank_account" and (
                    not isinstance(value, str)
                    or not validate_pl_iban_checksum(value)
                ):
                    raise BenchmarkCorpusError(
                        f"{location} fails production PL IBAN validation"
                    )
