"""Structured KSeF protocol and submission result models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class KsefSubmissionStatus(Enum):
    """Remote truth known for one submitted invoice."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"
    FAILED = "failed"


class KsefFailureStage(Enum):
    """Boundary where a KSeF proof failed or became uncertain."""

    PRECONDITION = "precondition"
    KEY_DISCOVERY = "key_discovery"
    AUTH = "auth"
    SESSION_OPEN = "session_open"
    SUBMIT = "submit"
    POLL = "poll"
    SESSION_CLOSE = "session_close"


class KsefKeyUsage(Enum):
    """Public certificate purposes published by KSeF."""

    TOKEN = "KsefTokenEncryption"
    SYMMETRIC = "SymmetricKeyEncryption"


@dataclass(frozen=True, kw_only=True)
class KsefPublicCertificate:
    """One KSeF-published encryption certificate."""

    certificate: str
    public_key_id: str
    valid_from: datetime
    valid_to: datetime
    usage: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class KsefChallenge:
    """Authentication challenge and server timestamp returned by KSeF."""

    challenge: str
    timestamp_ms: int


@dataclass(frozen=True, kw_only=True)
class KsefAuthInit:
    """Reference and one-shot temporary token for an authentication attempt."""

    reference_number: str
    authentication_token: str

    def __repr__(self) -> str:
        return (
            "KsefAuthInit(reference_number="
            f"{self.reference_number!r}, authentication_token=<redacted>)"
        )


@dataclass(frozen=True, kw_only=True)
class KsefSubmissionResult:
    """Safe structured result for one TEST invoice submission attempt."""

    status: KsefSubmissionStatus
    session_reference: str | None = None
    invoice_reference: str | None = None
    invoice_hash: str | None = None
    invoice_number: str | None = None
    ksef_number: str | None = None
    remote_status_code: int | None = None
    remote_status_description: str | None = None
    failure_stage: KsefFailureStage | None = None
    error_code: str | None = None
    diagnostic: str | None = None
    cleanup_error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is KsefSubmissionStatus.ACCEPTED:
            required = (
                self.session_reference,
                self.invoice_reference,
                self.ksef_number,
            )
            if not all(required):
                raise ValueError(
                    "accepted KSeF result requires session, invoice, and KSeF references"
                )
