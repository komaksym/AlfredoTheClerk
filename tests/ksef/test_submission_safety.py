from __future__ import annotations

import httpx
import pytest

from src.ksef.models import KsefFailureStage, KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice
from src.ksef.transport import KsefTransport, KsefTransportError
from tests.ksef.support import FakeKsef, config, original_hash, ready_result


def test_auth_key_rotation_refetches_and_retries_once() -> None:
    fake = FakeKsef()
    fake.auth_rotate_once = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert fake.certificate_calls == 2
    assert fake.auth_init_calls == 2
    assert fake.redeem_calls == 1


def test_session_key_rotation_refetches_and_retries_once() -> None:
    fake = FakeKsef()
    fake.session_rotate_once = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert fake.certificate_calls == 2
    assert fake.session_open_calls == 2
    assert fake.send_calls == 1


def test_auth_poll_respects_retry_after_and_still_redeems_once() -> None:
    fake = FakeKsef()
    fake.auth_rate_limit_once = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert fake.auth_status_calls == 2
    assert fake.redeem_calls == 1


def test_lost_redeem_response_is_not_retried() -> None:
    fake = FakeKsef()
    fake.redeem_timeout = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.FAILED
    assert result.failure_stage is KsefFailureStage.AUTH
    assert result.error_code == "TRANSPORT_ERROR"
    assert fake.redeem_calls == 1


def test_poll_deadline_returns_pending_and_still_closes_session() -> None:
    fake = FakeKsef()
    fake.invoice_pending = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(poll_timeout_seconds=0),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.PENDING
    assert result.failure_stage is KsefFailureStage.POLL
    assert result.error_code == "POLL_TIMEOUT"
    assert fake.close_calls == 1


def test_malformed_invoice_status_is_structured_poll_failure() -> None:
    fake = FakeKsef()
    fake.malformed_invoice_status = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.FAILED
    assert result.failure_stage is KsefFailureStage.POLL
    assert result.error_code == "MALFORMED_STATUS_CODE"
    assert fake.close_calls == 1


def test_unresolved_ambiguous_send_returns_pending_without_resubmission() -> None:
    fake = FakeKsef()
    fake.send_timeout = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(poll_timeout_seconds=0),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.PENDING
    assert result.failure_stage is KsefFailureStage.SUBMIT
    assert result.error_code == "SUBMISSION_UNKNOWN"
    assert result.session_reference == "SESSION"
    assert result.invoice_hash == original_hash()
    assert fake.send_calls == 1
    assert fake.list_calls == 1
    assert fake.close_calls == 1


def test_non_retryable_reconciliation_error_preserves_uncertainty() -> None:
    fake = FakeKsef()
    fake.send_timeout = True
    fake.reconcile_error_status = 401

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.PENDING
    assert result.failure_stage is KsefFailureStage.SUBMIT
    assert result.error_code == "RECONCILIATION_FAILED"
    assert result.session_reference == "SESSION"
    assert result.invoice_hash == original_hash()
    assert "401" in (result.diagnostic or "")
    assert fake.send_calls == 1
    assert fake.list_calls == 1
    assert fake.close_calls == 1


def test_close_failure_preserves_accepted_invoice_truth() -> None:
    fake = FakeKsef()
    fake.close_error = True

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.ksef_number == "KSEF-TEST-1"
    assert result.cleanup_error_code == "CLOSE_FAILED"


def test_remote_error_diagnostics_do_not_echo_ksef_token() -> None:
    fake = FakeKsef()
    fake.auth_error_description = "test-secret-token must never escape"

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=httpx.MockTransport(fake),
    )

    rendered = repr(result)
    assert result.status is KsefSubmissionStatus.FAILED
    assert result.failure_stage is KsefFailureStage.AUTH
    assert "test-secret-token" not in rendered
    assert "test-secret-token" not in (result.diagnostic or "")


def test_transport_exception_does_not_echo_remote_description() -> None:
    secret = "test-secret-token must never escape"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"code": 29999, "description": secret}]},
        )

    transport = KsefTransport(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(KsefTransportError) as raised:
            transport.get_challenge()
    finally:
        transport.close()

    assert secret not in str(raised.value)
    assert raised.value.code == "29999"
    assert raised.value.http_status == 400
