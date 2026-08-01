"""Regression tests for the two intentionally broken manual-review PDFs."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from src.agentic_repair.repair_routing import RepairRouteStatus, route_repair_context
from src.input_processing.extraction_comparison import run_full_extraction
from src.input_processing.parse_pdf import parse_data


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_FIXTURE = (
    REPO_ROOT
    / "data/synthetic_data/BROKEN_agent_ambiguous_seller_nip.pdf"
)
HUMAN_FIXTURE = REPO_ROOT / "data/synthetic_data/BROKEN_human_missing_buyer_nip.pdf"


def _extract_fixture(path: Path):
    """Run the real parser and production extraction pipeline for one fixture."""

    with pdfplumber.open(path) as pdf:
        return run_full_extraction(parse_data(pdf))


def test_agent_fixture_routes_only_seller_nip_to_agent() -> None:
    """The ambiguous seller NIP fixture must give the agent two legal choices."""

    context = _extract_fixture(AGENT_FIXTURE)
    route = route_repair_context(context)

    assert route.status is RepairRouteStatus.AGENT_REPAIR_AVAILABLE
    assert [field.path for field in route.repairable_fields] == ["seller.nip"]
    assert route.blocking_fields == ()

    evidence = context.evidence["seller.nip"]
    assert evidence.value is None
    assert evidence.candidates is not None
    assert {candidate.value for candidate in evidence.candidates} == {
        "8637940261",
        "5423511615",
    }


def test_human_fixture_routes_only_missing_buyer_nip_to_human() -> None:
    """A blank buyer NIP must leave no legal candidate for the repair agent."""

    context = _extract_fixture(HUMAN_FIXTURE)
    route = route_repair_context(context)

    assert route.status is RepairRouteStatus.MANUAL_REVIEW_REQUIRED
    assert route.repairable_fields == ()
    assert [field.path for field in route.blocking_fields] == ["buyer.nip"]
    assert route.blocking_fields[0].reason == "no_candidates"

    evidence = context.evidence["buyer.nip"]
    assert evidence.value is None
    assert not evidence.candidates
