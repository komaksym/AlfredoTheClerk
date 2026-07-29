"""End-to-end proof that one locally ready invoice can be accepted by KSeF TEST."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import replace
from typing import Any

import httpx

from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.ksef.config import KsefTestConfig
from src.ksef.crypto import (
    encrypt_invoice,
    encrypt_symmetric_key,
    encrypt_token,
    load_rsa_public_key,
    select_certificate,
)
from src.ksef.models import (
    KsefFailureStage,
    KsefKeyUsage,
    KsefPublicCertificate,
    KsefSubmissionResult,
    KsefSubmissionStatus,
)
from src.ksef.transport import KsefTransport, KsefTransportError

_KEY_ROTATED = "21470"


def submit_ready_invoice(
    correctness: CorrectnessResult,
    *,
    config: KsefTestConfig,
    http_transport: httpx.BaseTransport | None = None,
) -> KsefSubmissionResult:
    """Submit one complete locally validated FA(3) invoice to KSeF TEST."""

    precondition = _validate_preconditions(correctness, config)
    if precondition is not None:
        return precondition

    transport = KsefTransport(transport=http_transport)
    access_token: str | None = None
    session_reference: str | None = None
    result: KsefSubmissionResult | None = None
    try:
        try:
            certificates = transport.get_public_certificates()
            access_token = _authenticate(transport, config, certificates)
        except KsefTransportError as exc:
            return _failed(KsefFailureStage.AUTH, exc)
        except ValueError as exc:
            return _failed(
                KsefFailureStage.KEY_DISCOVERY,
                code="NO_VALID_KEY",
                diagnostic=str(exc),
            )

        key = os.urandom(32)
        iv = os.urandom(16)
        encrypted = encrypt_invoice(correctness.xml or "", key, iv)
        invoice_number = correctness.shell.invoice_number or ""

        try:
            session_reference = _open_session(
                transport,
                access_token=access_token,
                key=key,
                iv=iv,
                certificates=certificates,
            )
        except KsefTransportError as exc:
            return _failed(KsefFailureStage.SESSION_OPEN, exc)
        except ValueError as exc:
            return _failed(
                KsefFailureStage.KEY_DISCOVERY,
                code="NO_VALID_KEY",
                diagnostic=str(exc),
            )

        invoice_reference: str | None
        try:
            invoice_reference = transport.send_invoice(
                access_token=access_token,
                session_reference=session_reference,
                invoice_hash=encrypted.original_hash_b64,
                invoice_size=encrypted.original_size,
                encrypted_hash=encrypted.encrypted_hash_b64,
                encrypted_size=encrypted.encrypted_size,
                encrypted_content=encrypted.content_b64,
            )
        except KsefTransportError as exc:
            if exc.code != "TRANSPORT_ERROR":
                result = _failed(
                    KsefFailureStage.SUBMIT,
                    exc,
                    session_reference=session_reference,
                    invoice_hash=encrypted.original_hash_b64,
                    invoice_number=invoice_number,
                )
            else:
                invoice_reference = _reconcile_submission(
                    transport,
                    config=config,
                    access_token=access_token,
                    session_reference=session_reference,
                    invoice_hash=encrypted.original_hash_b64,
                    invoice_number=invoice_number,
                )
                if invoice_reference is None:
                    result = KsefSubmissionResult(
                        status=KsefSubmissionStatus.PENDING,
                        session_reference=session_reference,
                        invoice_hash=encrypted.original_hash_b64,
                        invoice_number=invoice_number,
                        failure_stage=KsefFailureStage.SUBMIT,
                        error_code="SUBMISSION_UNKNOWN",
                        diagnostic="invoice submission outcome could not be reconciled",
                    )

        if result is None:
            assert invoice_reference is not None
            result = _poll_invoice(
                transport,
                config=config,
                access_token=access_token,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
                invoice_hash=encrypted.original_hash_b64,
                invoice_number=invoice_number,
            )
        return result
    finally:
        cleanup_code: str | None = None
        if access_token and session_reference:
            try:
                transport.close_online_session(access_token, session_reference)
            except KsefTransportError as exc:
                cleanup_code = exc.code
        transport.close()
        if cleanup_code and result is not None:
            result = replace(result, cleanup_error_code=cleanup_code)


def _validate_preconditions(
    correctness: CorrectnessResult,
    config: KsefTestConfig,
) -> KsefSubmissionResult | None:
    if correctness.status is not CorrectnessStatus.READY_FOR_KSEF:
        return _failed(KsefFailureStage.PRECONDITION, code="NOT_READY_FOR_KSEF")
    if not correctness.xml:
        return _failed(KsefFailureStage.PRECONDITION, code="XML_REQUIRED")
    if correctness.xsd_validation is None or not correctness.xsd_validation.is_valid:
        return _failed(KsefFailureStage.PRECONDITION, code="XSD_VALIDATION_REQUIRED")
    if not config.token:
        return _failed(KsefFailureStage.PRECONDITION, code="KSEF_TEST_TOKEN_REQUIRED")
    if not config.context_nip:
        return _failed(KsefFailureStage.PRECONDITION, code="KSEF_TEST_CONTEXT_NIP_REQUIRED")
    if correctness.shell.seller.nip != config.context_nip:
        return _failed(KsefFailureStage.PRECONDITION, code="SELLER_CONTEXT_MISMATCH")
    return None


def _authenticate(
    transport: KsefTransport,
    config: KsefTestConfig,
    certificates: tuple[KsefPublicCertificate, ...],
) -> str:
    challenge = transport.get_challenge()
    current = certificates
    for attempt in range(2):
        cert = select_certificate(current, KsefKeyUsage.TOKEN)
        encrypted = encrypt_token(
            config.token,
            challenge.timestamp_ms,
            load_rsa_public_key(cert.certificate),
        )
        try:
            init = transport.start_token_auth(
                challenge=challenge.challenge,
                context_nip=config.context_nip,
                encrypted_token=encrypted,
                public_key_id=cert.public_key_id,
            )
            break
        except KsefTransportError as exc:
            if exc.code != _KEY_ROTATED or attempt:
                raise
            current = transport.get_public_certificates()
    else:  # pragma: no cover
        raise KsefTransportError("AUTH_INIT_FAILED")

    _poll_auth(transport, config, init.reference_number, init.authentication_token)
    return transport.redeem(init.authentication_token).access_token


def _poll_auth(
    transport: KsefTransport,
    config: KsefTestConfig,
    reference: str,
    auth_token: str,
) -> None:
    deadline = time.monotonic() + config.poll_timeout_seconds
    while True:
        payload = transport.get_auth_status(reference, auth_token)
        code, description = _status(payload)
        if code == 200:
            return
        if code >= 400:
            raise KsefTransportError(
                "AUTH_REJECTED",
                description=description or f"status {code}",
            )
        if time.monotonic() >= deadline:
            raise KsefTransportError("AUTH_TIMEOUT")
        _sleep(config.poll_interval_seconds)


def _open_session(
    transport: KsefTransport,
    *,
    access_token: str,
    key: bytes,
    iv: bytes,
    certificates: tuple[KsefPublicCertificate, ...],
) -> str:
    current = certificates
    for attempt in range(2):
        cert = select_certificate(current, KsefKeyUsage.SYMMETRIC)
        encrypted_key = encrypt_symmetric_key(
            key,
            load_rsa_public_key(cert.certificate),
        )
        try:
            return transport.open_online_session(
                access_token=access_token,
                encrypted_key=encrypted_key,
                iv_b64=base64.b64encode(iv).decode(),
                public_key_id=cert.public_key_id,
            )
        except KsefTransportError as exc:
            if exc.code != _KEY_ROTATED or attempt:
                raise
            current = transport.get_public_certificates()
    raise KsefTransportError("SESSION_OPEN_FAILED")  # pragma: no cover


def _poll_invoice(
    transport: KsefTransport,
    *,
    config: KsefTestConfig,
    access_token: str,
    session_reference: str,
    invoice_reference: str,
    invoice_hash: str,
    invoice_number: str,
) -> KsefSubmissionResult:
    deadline = time.monotonic() + config.poll_timeout_seconds
    while True:
        try:
            payload = transport.get_invoice_status(
                access_token=access_token,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
            )
        except KsefTransportError as exc:
            return _failed(
                KsefFailureStage.POLL,
                exc,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
                invoice_hash=invoice_hash,
                invoice_number=invoice_number,
            )
        code, description = _status(payload)
        if code == 200:
            ksef_number = payload.get("ksefNumber")
            if not isinstance(ksef_number, str) or not ksef_number:
                return _failed(
                    KsefFailureStage.POLL,
                    code="KSEF_NUMBER_REQUIRED",
                    session_reference=session_reference,
                    invoice_reference=invoice_reference,
                    invoice_hash=invoice_hash,
                    invoice_number=invoice_number,
                )
            return KsefSubmissionResult(
                status=KsefSubmissionStatus.ACCEPTED,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
                invoice_hash=invoice_hash,
                invoice_number=invoice_number,
                ksef_number=ksef_number,
                remote_status_code=code,
                remote_status_description=description,
            )
        if code >= 400:
            return KsefSubmissionResult(
                status=KsefSubmissionStatus.REJECTED,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
                invoice_hash=invoice_hash,
                invoice_number=invoice_number,
                remote_status_code=code,
                remote_status_description=description,
            )
        if time.monotonic() >= deadline:
            return KsefSubmissionResult(
                status=KsefSubmissionStatus.PENDING,
                session_reference=session_reference,
                invoice_reference=invoice_reference,
                invoice_hash=invoice_hash,
                invoice_number=invoice_number,
                remote_status_code=code,
                remote_status_description=description,
                failure_stage=KsefFailureStage.POLL,
                error_code="POLL_TIMEOUT",
            )
        _sleep(config.poll_interval_seconds)


def _reconcile_submission(
    transport: KsefTransport,
    *,
    config: KsefTestConfig,
    access_token: str,
    session_reference: str,
    invoice_hash: str,
    invoice_number: str,
) -> str | None:
    deadline = time.monotonic() + config.poll_timeout_seconds
    while True:
        try:
            invoices = transport.list_session_invoices(
                access_token=access_token,
                session_reference=session_reference,
            )
        except KsefTransportError:
            invoices = ()
        matches = [
            item
            for item in invoices
            if item.get("invoiceHash") == invoice_hash
            and item.get("invoiceNumber") == invoice_number
            and isinstance(item.get("referenceNumber"), str)
        ]
        if len(matches) == 1:
            return str(matches[0]["referenceNumber"])
        if time.monotonic() >= deadline:
            return None
        _sleep(config.poll_interval_seconds)


def _status(payload: dict[str, Any]) -> tuple[int, str | None]:
    raw = payload.get("status")
    if not isinstance(raw, dict):
        raise KsefTransportError("MALFORMED_STATUS")
    code = raw.get("code")
    description = raw.get("description")
    if not isinstance(code, int) or isinstance(code, bool):
        raise KsefTransportError("MALFORMED_STATUS_CODE")
    return code, str(description) if description is not None else None


def _failed(
    stage: KsefFailureStage,
    error: KsefTransportError | None = None,
    *,
    code: str | None = None,
    diagnostic: str | None = None,
    session_reference: str | None = None,
    invoice_reference: str | None = None,
    invoice_hash: str | None = None,
    invoice_number: str | None = None,
) -> KsefSubmissionResult:
    return KsefSubmissionResult(
        status=KsefSubmissionStatus.FAILED,
        session_reference=session_reference,
        invoice_reference=invoice_reference,
        invoice_hash=invoice_hash,
        invoice_number=invoice_number,
        failure_stage=stage,
        error_code=code or (error.code if error else "KSEF_FAILURE"),
        diagnostic=diagnostic or (str(error) if error else None),
    )


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
