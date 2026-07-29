from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from src.invoice_gen.domain_shell import build_domestic_vat_shell
from src.invoice_gen.domestic_vat_shell_validation import ShellValidationResult
from src.invoice_gen.fa3_xsd_validation import XsdValidationResult
from src.invoice_gen.invoice_correctness import CorrectnessResult, CorrectnessStatus
from src.ksef.config import KsefTestConfig


def ready_result(nip: str = "5265877635") -> CorrectnessResult:
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
