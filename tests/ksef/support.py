"""Shared fixtures and scripted HTTP fake used by KSeF integration tests."""

from __future__ import annotations

import base64
import hashlib
import json
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


def ready_result(nip: str = "5265877635") -> CorrectnessResult:
    """Build a minimal locally ready correctness result for submission tests."""

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


def config(**changes: object) -> KsefTestConfig:
    """Build deterministic TEST configuration with optional field overrides."""

    values = {
        "token": "test-secret-token",
        "context_nip": "5265877635",
        "poll_interval_seconds": 0,
        "poll_timeout_seconds": 0.1,
    }
    values.update(changes)
    return KsefTestConfig(**values)


def certificate_payload(
    *,
    public_key_id: str = "public-key-id",
    usage: tuple[str, ...] = (
        "KsefTokenEncryption",
        "SymmetricKeyEncryption",
    ),
) -> list[dict[str, object]]:
    """Create one valid synthetic KSeF certificate response payload."""

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "KSeF test")]
    )
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
            "certificate": base64.b64encode(
                cert.public_bytes(Encoding.DER)
            ).decode(),
            "certificateId": f"cert-{public_key_id}",
            "publicKeyId": public_key_id,
            "validFrom": (now - timedelta(days=1)).isoformat(),
            "validTo": (now + timedelta(days=30)).isoformat(),
            "usage": list(usage),
        }
    ]


def original_hash() -> str:
    """Return the Base64 SHA-256 hash of the shared synthetic XML fixture."""

    return base64.b64encode(
        hashlib.sha256(b"<Faktura>synthetic</Faktura>").digest()
    ).decode()


class FakeKsef:
    """Scriptable HTTP fake shared by orchestration tests."""

    def __init__(self) -> None:
        """Initialize call counters and behavior switches for the fake API."""

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
        self.auth_pending_once = False
        self.redeem_timeout = False
        self.send_timeout = False
        self.reconcile_match = False
        self.reconcile_error_status: int | None = None
        self.invoice_pending_once = False
        self.invoice_pending = False
        self.invoice_rejection_code: int | None = None
        self.malformed_invoice_status = False
        self.close_error = False
        self.auth_error_description: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Route one mocked HTTP request to the matching scripted KSeF behavior."""

        assert str(request.url).startswith(KSEF_TEST_BASE_URL)
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
            return self._start_auth(request)
        if path == "/auth/AUTH":
            return self._auth_status()
        if path == "/auth/token/redeem":
            self.redeem_calls += 1
            if self.redeem_timeout:
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(
                200,
                json={"accessToken": {"token": "access-secret"}},
            )
        if path == "/sessions/online":
            return self._open_session(request)
        if path == "/sessions/online/SESSION/invoices":
            self.send_calls += 1
            if self.send_timeout:
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(202, json={"referenceNumber": "INVOICE"})
        if path == "/sessions/SESSION/invoices":
            return self._list_invoices()
        if path in {
            "/sessions/SESSION/invoices/INVOICE",
            "/sessions/SESSION/invoices/RECOVERED",
        }:
            return self._invoice_status()
        if path == "/sessions/online/SESSION/close":
            self.close_calls += 1
            if self.close_error:
                return httpx.Response(500, json={"code": "CLOSE_FAILED"})
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {path}")

    def _start_auth(self, request: httpx.Request) -> httpx.Response:
        """Handle token-auth initialization including optional key rotation or errors."""

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
        assert "test-secret-token" not in request.content.decode()
        return httpx.Response(
            202,
            json={
                "referenceNumber": "AUTH",
                "authenticationToken": {"token": "auth-secret"},
            },
        )

    def _auth_status(self) -> httpx.Response:
        """Return the scripted asynchronous authentication status response."""

        self.auth_status_calls += 1
        if self.auth_rate_limit_once and self.auth_status_calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"code": 429, "detail": "slow down"},
            )
        code = 100 if self.auth_pending_once and self.auth_status_calls == 1 else 200
        return httpx.Response(200, json={"status": {"code": code}})

    def _open_session(self, request: httpx.Request) -> httpx.Response:
        """Handle encrypted online-session creation and optional key rotation."""

        self.session_open_calls += 1
        if self.session_rotate_once and self.session_open_calls == 1:
            return httpx.Response(
                400,
                json={"errors": [{"code": 21470, "description": "rotated"}]},
            )
        body = json.loads(request.content)
        expected_key = "key-2" if self.session_rotate_once else "key-1"
        assert body["encryption"]["publicKeyId"] == expected_key
        assert request.headers["Authorization"] == "Bearer access-secret"
        return httpx.Response(201, json={"referenceNumber": "SESSION"})

    def _list_invoices(self) -> httpx.Response:
        """Return scripted session invoice listings for ambiguity reconciliation."""

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
            invoices.append(
                {
                    "invoiceNumber": "TEST/2026/0001",
                    "invoiceHash": original_hash(),
                    "referenceNumber": "RECOVERED",
                }
            )
        return httpx.Response(200, json={"invoices": invoices})

    def _invoice_status(self) -> httpx.Response:
        """Return the scripted processing, rejection, malformed, or acceptance status."""

        self.invoice_status_calls += 1
        if self.malformed_invoice_status:
            return httpx.Response(200, json={"status": {"description": "bad"}})
        if self.invoice_pending or (
            self.invoice_pending_once and self.invoice_status_calls == 1
        ):
            return httpx.Response(
                200,
                json={"status": {"code": 150, "description": "processing"}},
            )
        if self.invoice_rejection_code is not None:
            return httpx.Response(
                200,
                json={
                    "status": {
                        "code": self.invoice_rejection_code,
                        "description": "rejected",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "status": {"code": 200, "description": "accepted"},
                "ksefNumber": "KSEF-TEST-1",
            },
        )
