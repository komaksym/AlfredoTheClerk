"""Safety regression tests for KSeF retries, ambiguity, cleanup, and secret handling."""

from __future__ import annotations

import httpx
import pytest

from src.ksef.models import KsefFailureStage, KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice
from src.ksef.transport import KsefTransport, KsefTransportError
from tests.ksef.support import FakeKsef, config, original_hash, ready_result


def _transport_with_invoice_status_error(
    fake: FakeKsef,
    *,
    status_code: int,
    once: bool,
) -> httpx.MockTransport:
    """Wrap the shared fake with a scripted HTTP error on invoice-status reads."""

    error_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the scripted status-read error before delegating other requests."""

        nonlocal error_calls
        path = request.url.path.removeprefix("/v2")
        is_invoice_status = path in {
            "/sessions/SESSION/invoices/INVOICE",
            "/sessions/SESSION/invoices/RECOVERED",
        }
        if is_invoice_status and (not once or error_calls == 0):
            error_calls += 1
            return httpx.Response(status_code, json={"code": status_code})
        return fake(request)

    return httpx.MockTransport(handler)


def test_auth_key_rotation_refetches_and_retries_once() -> None:
    """Refresh the token-encryption certificate once after KSeF reports key rotation."""

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
    """Refresh the session-encryption certificate once before invoice submission."""

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
    """Honor Retry-After during auth polling without redeeming the token twice."""

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
    """Avoid retrying the one-shot token redemption after an ambiguous timeout."""

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
    """Return PENDING at the poll deadline and still attempt session cleanup."""

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


def test_transient_status_5xx_is_retried_without_resubmission() -> None:
    """Retry a transient 5xx status read and preserve the one-shot invoice POST."""

    fake = FakeKsef()

    result = submit_ready_invoice(
        ready_result(),
        config=config(),
        http_transport=_transport_with_invoice_status_error(
            fake,
            status_code=503,
            once=True,
        ),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.invoice_reference == "INVOICE"
    assert fake.send_calls == 1
    assert fake.invoice_status_calls == 1


def test_persistent_status_5xx_returns_pending_at_deadline() -> None:
    """Keep remote truth pending when status GETs remain unavailable through the deadline."""

    fake = FakeKsef()

    result = submit_ready_invoice(
        ready_result(),
        config=config(poll_timeout_seconds=0),
        http_transport=_transport_with_invoice_status_error(
            fake,
            status_code=503,
            once=False,
        ),
    )

    assert result.status is KsefSubmissionStatus.PENDING
    assert result.failure_stage is KsefFailureStage.POLL
    assert result.error_code == "POLL_TIMEOUT"
    assert result.session_reference == "SESSION"
    assert result.invoice_reference == "INVOICE"
    assert fake.send_calls == 1
    assert fake.close_calls == 1


def test_malformed_invoice_status_is_structured_poll_failure() -> None:
    """Convert a malformed invoice status payload into a structured polling failure."""

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
    """Keep unresolved ambiguous invoice submission as PENDING without a second POST."""

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
    """Preserve uncertain remote truth when reconciliation fails non-retryably."""

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
    """Keep an accepted invoice result even when best-effort session close fails."""

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
    """Prevent remote error descriptions from leaking the configured KSeF token."""

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
    """Keep server-provided descriptions out of transport exception messages."""

    secret = "test-secret-token must never escape"

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an error payload containing secret-like remote text for redaction testing."""

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
