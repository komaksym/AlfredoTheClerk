"""Strict CI integration test proving one synthetic invoice reaches KSeF TEST."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from src.invoice_gen.domestic_vat_seed import build_domestic_vat_seed
from src.invoice_gen.domestic_vat_seed_mapping import map_domestic_vat_seed_to_shell
from src.invoice_gen.domestic_vat_shell_summary import summarize_domestic_vat_shell
from src.invoice_gen.invoice_correctness import CorrectnessStatus, check_invoice_correctness
from src.ksef.config import KsefTestConfig
from src.ksef.models import KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice


@pytest.mark.ksef_live
def test_synthetic_invoice_is_accepted_by_ksef_test() -> None:
    """Submit one unique locally valid synthetic FA(3) invoice to real KSeF TEST."""

    config = KsefTestConfig.from_env()
    config.require_credentials()

    shell = map_domestic_vat_seed_to_shell(build_domestic_vat_seed(42))
    shell.seller.nip = config.context_nip
    shell.invoice_number = f"ALFREDO-TEST-{date.today():%Y%m%d}-{uuid4().hex[:10]}"
    shell.issue_date = min(shell.issue_date or date.today(), date.today())
    shell.sale_date = min(shell.sale_date or shell.issue_date, shell.issue_date)
    extracted = summarize_domestic_vat_shell(shell)

    correctness = check_invoice_correctness(
        shell,
        extracted,
        generated_at=datetime.now(timezone.utc),
    )

    assert correctness.status is CorrectnessStatus.READY_FOR_KSEF
    assert correctness.xml
    assert correctness.xsd_validation is not None
    assert correctness.xsd_validation.is_valid

    result = submit_ready_invoice(correctness, config=config)

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.session_reference
    assert result.invoice_reference
    assert result.ksef_number
