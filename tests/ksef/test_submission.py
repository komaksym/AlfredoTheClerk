from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.fa3_xsd_validation import XsdValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.ksef.config import KSEF_TEST_BASE_URL, KsefTestConfig
from src.ksef.models import KsefFailureStage, KsefSubmissionStatus
from src.ksef.submission import submit_ready_invoice


def _ready_result(nip: str = "5265877635") -> CorrectnessResult:
    shell = build_domestic_vat_shell()
    shell.seller.nip = nip
    shell.invoice_number = "TEST/2026/0001"
    return CorrectnessResult(
        status=CorrectnessStatus.READY_FOR_KSEF,
        shell=shell,
        validation=ShellValidationResult(),
        xml="<Faktura>synthetic</Faktura>",
        xsd_validation=XsdValidationResult(is_valid=True),
    )


def _certificate_payload() -> list[dict[str, object]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KSeF test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return [
        {
            "certificate": base64.b64encode(cert.public_bytes(Encoding.DER)).decode(),
            "certificateId": "cert-id",
            "publicKeyId": "public-key-id",
            "validFrom": (now - timedelta(days=1)).isoformat(),
            "validTo": (now + timedelta(days=30)).isoformat(),
            "usage": ["KsefTokenEncryption", "SymmetricKeyEncryption"],
        }
    ]


def _config(**changes: object) -> KsefTestConfig:
    values = {
        "token": "test-secret-token",
        "context_nip": "5265877635",
        "poll_interval_seconds": 0,
        "poll_timeout_seconds": 0.1,
    }
    values.update(changes)
    return KsefTestConfig(**values)


def test_precondition_failure_never_calls_transport() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    result = submit_ready_invoice(
        CorrectnessResult(
            status=CorrectnessStatus.INVALID_SHELL,
            shell=build_domestic_vat_shell(),
            validation=ShellValidationResult(),
        ),
        config=_config(),
        http_transport=httpx.MockTransport(handler),
    )

    assert result.status is KsefSubmissionStatus.FAILED
    assert result.failure_stage is KsefFailureStage.PRECONDITION
    assert calls == 0


def test_happy_path_authenticates_submits_polls_and_closes() -> None:
    auth_polls = 0
    invoice_polls = 0
    close_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_polls, invoice_polls, close_calls
        assert str(request.url).startswith(KSEF_TEST_BASE_URL)
        path = request.url.path.removeprefix("/v2")
        if path == "/security/public-key-certificates":
            return httpx.Response(200, json=_certificate_payload())
        if path == "/auth/challenge":
            return httpx.Response(200, json={"challenge": "challenge", "timestampMs": 1234})
        if path == "/auth/ksef-token":
            body = request.read().decode()
            assert "test-secret-token" not in body
            return httpx.Response(
                202,
                json={
                    "referenceNumber": "AUTH-1",
                    "authenticationToken": {"token": "auth-secret"},
                },
            )
        if path == "/auth/AUTH-1":
            auth_polls += 1
            code = 100 if auth_polls == 1 else 200
            return httpx.Response(200, json={"status": {"code": code, "description": "auth"}})
        if path == "/auth/token/redeem":
            assert request.headers["Authorization"] == "Bearer auth-secret"
            return httpx.Response(
                200,
                json={
                    "accessToken": {"token": "access-secret"},
                    "refreshToken": {"token": "refresh-secret"},
                },
            )
        if path == "/sessions/online":
            assert request.headers["Authorization"] == "Bearer access-secret"
            return httpx.Response(201, json={"referenceNumber": "SESSION-1"})
        if path == "/sessions/online/SESSION-1/invoices":
            return httpx.Response(202, json={"referenceNumber": "INV-1"})
        if path == "/sessions/SESSION-1/invoices/INV-1":
            invoice_polls += 1
            if invoice_polls == 1:
                return httpx.Response(200, json={"status": {"code": 150, "description": "processing"}})
            return httpx.Response(
                200,
                json={
                    "referenceNumber": "INV-1",
                    "ksefNumber": "5265877635-20260729-ABC-01",
                    "status": {"code": 200, "description": "accepted"},
                },
            )
        if path == "/sessions/online/SESSION-1/close":
            close_calls += 1
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {path}")

    result = submit_ready_invoice(
        _ready_result(),
        config=_config(),
        http_transport=httpx.MockTransport(handler),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.session_reference == "SESSION-1"
    assert result.invoice_reference == "INV-1"
    assert result.ksef_number == "5265877635-20260729-ABC-01"
    assert auth_polls == 2
    assert invoice_polls == 2
    assert close_calls == 1


def test_terminal_invoice_rejection_is_not_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        if path == "/security/public-key-certificates":
            return httpx.Response(200, json=_certificate_payload())
        if path == "/auth/challenge":
            return httpx.Response(200, json={"challenge": "c", "timestampMs": 1})
        if path == "/auth/ksef-token":
            return httpx.Response(202, json={"referenceNumber": "A", "authenticationToken": {"token": "a"}})
        if path == "/auth/A":
            return httpx.Response(200, json={"status": {"code": 200}})
        if path == "/auth/token/redeem":
            return httpx.Response(200, json={"accessToken": {"token": "x"}, "refreshToken": {"token": "r"}})
        if path == "/sessions/online":
            return httpx.Response(201, json={"referenceNumber": "S"})
        if path == "/sessions/online/S/invoices":
            return httpx.Response(202, json={"referenceNumber": "I"})
        if path == "/sessions/S/invoices/I":
            return httpx.Response(200, json={"status": {"code": 440, "description": "duplicate"}})
        if path == "/sessions/online/S/close":
            return httpx.Response(204)
        raise AssertionError(path)

    result = submit_ready_invoice(
        _ready_result(),
        config=_config(),
        http_transport=httpx.MockTransport(handler),
    )

    assert result.status is KsefSubmissionStatus.REJECTED
    assert result.remote_status_code == 440


def test_ambiguous_send_reconciles_without_second_post() -> None:
    send_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_calls
        path = request.url.path.removeprefix("/v2")
        if path == "/security/public-key-certificates":
            return httpx.Response(200, json=_certificate_payload())
        if path == "/auth/challenge":
            return httpx.Response(200, json={"challenge": "c", "timestampMs": 1})
        if path == "/auth/ksef-token":
            return httpx.Response(202, json={"referenceNumber": "A", "authenticationToken": {"token": "a"}})
        if path == "/auth/A":
            return httpx.Response(200, json={"status": {"code": 200}})
        if path == "/auth/token/redeem":
            return httpx.Response(200, json={"accessToken": {"token": "x"}, "refreshToken": {"token": "r"}})
        if path == "/sessions/online":
            return httpx.Response(201, json={"referenceNumber": "S"})
        if path == "/sessions/online/S/invoices":
            send_calls += 1
            raise httpx.ReadTimeout("lost response", request=request)
        if path == "/sessions/S/invoices":
            return httpx.Response(
                200,
                json={
                    "invoices": [
                        {
                            "invoiceNumber": "TEST/2026/0001",
                            "invoiceHash": expected_hash,
                            "referenceNumber": "RECOVERED",
                        }
                    ]
                },
            )
        if path == "/sessions/S/invoices/RECOVERED":
            return httpx.Response(200, json={"status": {"code": 200}, "ksefNumber": "KSEF-1"})
        if path == "/sessions/online/S/close":
            return httpx.Response(204)
        raise AssertionError(path)

    # SHA-256 for the exact XML in _ready_result(). This makes reconciliation
    # assert the protocol identity rather than merely finding one session item.
    import hashlib

    expected_hash = base64.b64encode(
        hashlib.sha256(b"<Faktura>synthetic</Faktura>").digest()
    ).decode()

    result = submit_ready_invoice(
        _ready_result(),
        config=_config(),
        http_transport=httpx.MockTransport(handler),
    )

    assert result.status is KsefSubmissionStatus.ACCEPTED
    assert result.invoice_reference == "RECOVERED"
    assert send_calls == 1
