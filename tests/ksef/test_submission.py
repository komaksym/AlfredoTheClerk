"""End-to-end mocked tests for KSeF submission orchestration behavior."""

from __future__ import annotations

import httpx

from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.ksef.models import KsefFailureStage, KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice
from tests.ksef.support import FakeKsef, config, ready_result


def test_precondition_failure_never_calls_transport() -> None:
    """Reject locally invalid invoices before any KSeF HTTP request is attempted."""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail the test if a precondition rejection reaches the network boundary."""

        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    result = submit_ready_invoice(
        CorrectnessResult(
            status=CorrectnessStatus.INVALID_SHELL,
            shell=build_domestic_vat_shell(),
            validation=ShellValidationResult(),
        ),
        config=config(),
        http_transport=httpx.MockTransport(handler),
    )

    assert result.status is KsefSubmissionStatus.FAILED
    assert result.failure_stage is KsefFailureStage.PRECONDITION
    assert calls == 0


def test_happy_path_authenticates_submits_polls_and_closes() -> None:
    """Complete auth, submission, polling, and session close on the happy path."""

    fake = FakeKsef()
    fake.auth_pending_once = True
    fake.invoice_pending_once = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.session_reference == "SESSION"
    assert result.invoice_reference == "INVOICE"
    assert result.ksef_number == "KSEF-TEST-1"
    assert fake.auth_status_calls == 2
    assert fake.invoice_status_calls == 2
    assert fake.redeem_calls == 1
    assert fake.close_calls == 1


def test_terminal_invoice_rejection_is_not_failed() -> None:
    """Represent a terminal remote invoice rejection as REJECTED rather than FAILED."""

    fake = FakeKsef()
    fake.invoice_rejection_code = 440

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.REJECTED
    assert result.remote_status_code == 440


def test_ambiguous_send_reconciles_without_second_post() -> None:
    """Recover an ambiguous invoice POST by listing the session without resubmitting."""

    fake = FakeKsef()
    fake.send_timeout = True
    fake.reconcile_match = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.invoice_reference == "RECOVERED"
    assert fake.send_calls == 1
    assert fake.list_calls == 1
