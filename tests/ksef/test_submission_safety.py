from __future__ import annotations

import json

import httpx

from src.ksef.models import KsefFailureStage, KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice
from tests.ksef.support import certificate_payload, config, ready_result


class FakeKsef:
    def __init__(self) -> None:
        self.certificate_calls = 0
        self.auth_init_calls = 0
        self.auth_status_calls = 0
        self.redeem_calls = 0
        self.session_open_calls = 0
        self.send_calls = 0
        self.invoice_status_calls = 0
        self.list_calls = 0
        self.close_calls = 0
        self.auth_rotate_once = False
        self.session_rotate_once = False
        self.auth_rate_limit_once = False
        self.redeem_timeout = False
        self.send_timeout = False
        self.reconcile_match = False
        self.reconcile_error_status: int | None = None
        self.invoice_pending = False
        self.malformed_invoice_status = False
        self.close_error = False
        self.auth_error_description: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        if path == "/security/public-key-certificates":
            self.certificate_calls += 1
            return httpx.Response(
                200,
                json=certificate_payload(
                    public_key_id=f"key-{self.certificate_calls}"
                ),
            )
        if path == "/auth/challenge":
            return httpx.Response(
                200,
                json={"challenge": "challenge", "timestampMs": 1234},
            )
        if path == "/auth/ksef-token":
            self.auth_init_calls += 1
            if self.auth_error_description is not None:
                return httpx.Response(
                    400,
                    json={
                        "errors": [
                            {
                                "code": 29999,
                                "description": self.auth_error_description,
                            }
                        ]
                    },
                )
            if self.auth_rotate_once and self.auth_init_calls == 1:
                return httpx.Response(
                    400,
                    json={
                        "errors": [
                            {"code": 21470, "description": "key rotated"}
                        ]
                    },
                )
            body = json.loads(request.content)
            expected_key = "key-2" if self.auth_rotate_once else "key-1"
            assert body["publicKeyId"] == expected_key
            return httpx.Response(
                202,
                json={
                    "referenceNumber": "AUTH",
                    "authenticationToken": {"token": "auth-secret"},
                },
            )
        if path == "/auth/AUTH":
            self.auth_status_calls += 1
            if self.auth_rate_limit_once and self.auth_status_calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"code": 429, "detail": "slow down"},
                )
            return httpx.Response(200, json={"status": {"code": 200}})
        if path == "/auth/token/redeem":
            self.redeem_calls += 1
            if self.redeem_timeout:
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(
                200,
                json={
                    "accessToken": {"token": "access-secret"},
                    "refreshToken": {"token": "refresh-secret"},
                },
            )
        if path == "/sessions/online":
            self.session_open_calls += 1
            if self.session_rotate_once and self.session_open_calls == 1:
                return httpx.Response(
                    400,
                    json={"errors": [{"code": 21470, "description": "rotated"}]},
                )
            body = json.loads(request.content)
            expected_key = "key-2" if self.session_rotate_once else "key-1"
            assert body["encryption"]["publicKeyId"] == expected_key
            return httpx.Response(201, json={"referenceNumber": "SESSION"})
        if path == "/sessions/online/SESSION/invoices":
            self.send_calls += 1
            if self.send_timeout:
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(202, json={"referenceNumber": "INVOICE"})
        if path == "/sessions/SESSION/invoices":
            self.list_calls += 1
            if self.reconcile_error_status is not None:
                return httpx.Response(
                    self.reconcile_error_status,
                    json={
                        "title": "Unauthorized",
                        "status": self.reconcile_error_status,
                        "detail": "session list unavailable",
                    },
                )
            invoices: list[dict[str, str]] = []
            if self.reconcile_match:
                request_hash = _original_hash()
                invoices.append(
                    {
                        "invoiceNumber": "TEST/2026/0001",
                        "invoiceHash": request_hash,
                        "referenceNumber": "RECOVERED",
                    }
                )
            return httpx.Response(200, json={"invoices": invoices})
        if path in {
            "/sessions/SESSION/invoices/INVOICE",
            "/sessions/SESSION/invoices/RECOVERED",
        }:
            self.invoice_status_calls += 1
            if self.malformed_invoice_status:
                return httpx.Response(200, json={"status": {"description": "bad"}})
            if self.invoice_pending:
                return httpx.Response(
                    200,
                    json={"status": {"code": 150, "description": "processing"}},
                )
            return httpx.Response(
                200,
                json={
                    "status": {"code": 200, "description": "accepted"},
                    "ksefNumber": "KSEF-TEST-1",
                },
            )
        if path == "/sessions/online/SESSION/close":
            self.close_calls += 1
            if self.close_error:
                return httpx.Response(500, json={"code": "CLOSE_FAILED"})
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {path}")


def _original_hash() -> str:
    import base64
    import hashlib

    return base64.b64encode(
        hashlib.sha256(b"<Faktura>synthetic</Faktura>").digest()
    ).decode()


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
    assert result.invoice_hash == _original_hash()
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
    assert result.invoice_hash == _original_hash()
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