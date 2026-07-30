"""Strict HTTP transport for the KSeF TEST API."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from src.ksef.config import KSEF_TEST_BASE_URL
from src.ksef.models import KsefAuthInit, KsefChallenge, KsefPublicCertificate


class KsefTransportError(RuntimeError):
    """Safe expected transport/protocol error without credential material."""

    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        description: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store safe transport metadata while intentionally discarding remote text."""

        self.code = code
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(self._message())

    def _message(self) -> str:
        """Build the secret-safe exception message from code and HTTP status only."""

        parts = [self.code]
        if self.http_status is not None:
            parts.append(f"http={self.http_status}")
        return ": ".join(parts)


class KsefTransport:
    """Typed calls against the fixed KSeF TEST origin."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        """Create an HTTP client fixed to the KSeF TEST origin."""

        self._client = httpx.Client(
            base_url=KSEF_TEST_BASE_URL,
            transport=transport,
            timeout=timeout_seconds,
            headers={"X-Error-Format": "problem-details"},
        )

    def close(self) -> None:
        """Close the underlying HTTP client and release its resources."""

        self._client.close()

    def get_public_certificates(self) -> tuple[KsefPublicCertificate, ...]:
        """Fetch and parse the public encryption certificates published by KSeF."""

        payload = self._json("GET", "/security/public-key-certificates", expected=200)
        if not isinstance(payload, list):
            raise KsefTransportError("MALFORMED_CERTIFICATES")
        items: list[KsefPublicCertificate] = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise KsefTransportError("MALFORMED_CERTIFICATE")
            items.append(
                KsefPublicCertificate(
                    certificate=_required_str(raw, "certificate"),
                    public_key_id=_required_str(raw, "publicKeyId"),
                    valid_from=_parse_datetime(_required_str(raw, "validFrom")),
                    valid_to=_parse_datetime(_required_str(raw, "validTo")),
                    usage=_required_str_tuple(raw, "usage"),
                )
            )
        return tuple(items)

    def get_challenge(self) -> KsefChallenge:
        """Request a fresh KSeF authentication challenge and timestamp."""

        payload = self._json("POST", "/auth/challenge", expected=200)
        return KsefChallenge(
            challenge=_required_str(payload, "challenge"),
            timestamp_ms=_required_int(payload, "timestampMs"),
        )

    def start_token_auth(
        self,
        *,
        challenge: str,
        context_nip: str,
        encrypted_token: str,
        public_key_id: str,
    ) -> KsefAuthInit:
        """Start token authentication for one NIP context using encrypted credentials."""

        payload = self._json(
            "POST",
            "/auth/ksef-token",
            expected=202,
            json={
                "challenge": challenge,
                "contextIdentifier": {"type": "Nip", "value": context_nip},
                "encryptedToken": encrypted_token,
                "publicKeyId": public_key_id,
            },
        )
        token = _required_dict(payload, "authenticationToken")
        return KsefAuthInit(
            reference_number=_required_str(payload, "referenceNumber"),
            authentication_token=_required_str(token, "token"),
        )

    def get_auth_status(self, reference: str, auth_token: str) -> dict[str, Any]:
        """Fetch the current status of an asynchronous authentication request."""

        return self._json(
            "GET",
            f"/auth/{reference}",
            expected=200,
            bearer=auth_token,
        )

    def redeem(self, auth_token: str) -> str:
        """Redeem a temporary authentication token once and return its access token."""

        payload = self._json(
            "POST",
            "/auth/token/redeem",
            expected=200,
            bearer=auth_token,
        )
        access = _required_dict(payload, "accessToken")
        return _required_str(access, "token")

    def open_online_session(
        self,
        *,
        access_token: str,
        encrypted_key: str,
        iv_b64: str,
        public_key_id: str,
    ) -> str:
        """Open an encrypted online FA(3) session and return its reference number."""

        payload = self._json(
            "POST",
            "/sessions/online",
            expected=201,
            bearer=access_token,
            json={
                "formCode": {
                    "systemCode": "FA (3)",
                    "schemaVersion": "1-0E",
                    "value": "FA",
                },
                "encryption": {
                    "encryptedSymmetricKey": encrypted_key,
                    "initializationVector": iv_b64,
                    "publicKeyId": public_key_id,
                },
            },
        )
        return _required_str(payload, "referenceNumber")

    def send_invoice(
        self,
        *,
        access_token: str,
        session_reference: str,
        invoice_hash: str,
        invoice_size: int,
        encrypted_hash: str,
        encrypted_size: int,
        encrypted_content: str,
    ) -> str:
        """Submit one encrypted invoice to an online session and return its reference."""

        payload = self._json(
            "POST",
            f"/sessions/online/{session_reference}/invoices",
            expected=202,
            bearer=access_token,
            json={
                "invoiceHash": invoice_hash,
                "invoiceSize": invoice_size,
                "encryptedInvoiceHash": encrypted_hash,
                "encryptedInvoiceSize": encrypted_size,
                "encryptedInvoiceContent": encrypted_content,
                "offlineMode": False,
            },
        )
        return _required_str(payload, "referenceNumber")

    def get_invoice_status(
        self,
        *,
        access_token: str,
        session_reference: str,
        invoice_reference: str,
    ) -> dict[str, Any]:
        """Fetch the remote processing status for one submitted invoice."""

        return self._json(
            "GET",
            f"/sessions/{session_reference}/invoices/{invoice_reference}",
            expected=200,
            bearer=access_token,
        )

    def list_session_invoices(
        self,
        *,
        access_token: str,
        session_reference: str,
    ) -> tuple[dict[str, Any], ...]:
        """List invoices in a session for ambiguity-safe submission reconciliation."""

        payload = self._json(
            "GET",
            f"/sessions/{session_reference}/invoices",
            expected=200,
            bearer=access_token,
            params={"pageSize": 1000},
        )
        raw = payload.get("invoices") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise KsefTransportError("MALFORMED_SESSION_INVOICES")
        if not all(isinstance(item, dict) for item in raw):
            raise KsefTransportError("MALFORMED_SESSION_INVOICE")
        return tuple(raw)

    def close_online_session(self, access_token: str, session_reference: str) -> None:
        """Best-effort close one KSeF online session after submission processing."""

        self._request(
            "POST",
            f"/sessions/online/{session_reference}/close",
            expected=204,
            bearer=access_token,
        )

    def _json(self, method: str, path: str, *, expected: int, **kwargs: Any) -> Any:
        """Execute one request and decode its response body as JSON."""

        response = self._request(method, path, expected=expected, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise KsefTransportError(
                "MALFORMED_JSON",
                http_status=response.status_code,
            ) from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected: int,
        bearer: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send one HTTP request and normalize transport or protocol failures."""

        headers = dict(kwargs.pop("headers", {}))
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise KsefTransportError("TRANSPORT_ERROR") from exc
        if response.status_code != expected:
            raise KsefTransportError(
                _error_code(response),
                http_status=response.status_code,
                retry_after=_retry_after(response),
            )
        return response


def _error_code(response: httpx.Response) -> str:
    """Extract a documented KSeF error code with a conservative HTTP fallback."""

    try:
        payload = response.json()
    except ValueError:
        return "HTTP_ERROR"
    if not isinstance(payload, dict):
        return "HTTP_ERROR"

    code = _simple_code(payload.get("reasonCode")) or _simple_code(payload.get("code"))
    errors = payload.get("errors")
    if code is None and isinstance(errors, list) and errors and isinstance(errors[0], dict):
        code = _simple_code(errors[0].get("code"))
    return code or "HTTP_ERROR"


def _simple_code(value: Any) -> str | None:
    """Normalize a scalar error code to text while rejecting booleans."""

    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value)
    return None


def _retry_after(response: httpx.Response) -> float | None:
    """Parse Retry-After as seconds or an HTTP date and return a nonnegative delay."""

    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (retry_at - datetime.now(timezone.utc)).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


def _required_dict(payload: Any, name: str) -> dict[str, Any]:
    """Return one required object-valued field or raise a structured protocol error."""

    if not isinstance(payload, dict) or not isinstance(payload.get(name), dict):
        raise KsefTransportError(f"MISSING_{name.upper()}")
    return payload[name]


def _required_str(payload: Any, name: str) -> str:
    """Return one required nonempty string field or raise a protocol error."""

    if not isinstance(payload, dict):
        raise KsefTransportError(f"MISSING_{name.upper()}")
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise KsefTransportError(f"MISSING_{name.upper()}")
    return value


def _required_int(payload: Any, name: str) -> int:
    """Return one required integer field while rejecting booleans and malformed data."""

    if not isinstance(payload, dict):
        raise KsefTransportError(f"MISSING_{name.upper()}")
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise KsefTransportError(f"MISSING_{name.upper()}")
    return value


def _required_str_tuple(payload: dict[str, Any], name: str) -> tuple[str, ...]:
    """Return one required list-of-strings field as an immutable tuple."""

    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise KsefTransportError(f"MISSING_{name.upper()}")
    return tuple(value)


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 KSeF timestamp into a timezone-aware datetime when supplied."""

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KsefTransportError("MALFORMED_DATETIME") from exc
