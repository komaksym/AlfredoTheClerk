from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from src.ksef.config import KsefTestConfig
from src.ksef.crypto import (
    encrypt_invoice,
    encrypt_token,
    load_rsa_public_key,
    select_certificate,
)
from src.ksef.models import (
    KsefKeyUsage,
    KsefPublicCertificate,
    KsefSubmissionResult,
    KsefSubmissionStatus,
)


def _certificate(*, valid_from: datetime, usage: tuple[str, ...]):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_from + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    model = KsefPublicCertificate(
        certificate=base64.b64encode(cert.public_bytes(Encoding.DER)).decode(),
        public_key_id=f"id-{valid_from.timestamp()}",
        valid_from=valid_from,
        valid_to=valid_from + timedelta(days=30),
        usage=usage,
    )
    return model, key


def test_select_certificate_uses_latest_valid_matching_usage():
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    older, _ = _certificate(
        valid_from=now - timedelta(days=10),
        usage=(KsefKeyUsage.TOKEN.value,),
    )
    newer, _ = _certificate(
        valid_from=now - timedelta(days=2),
        usage=(KsefKeyUsage.TOKEN.value,),
    )
    wrong, _ = _certificate(
        valid_from=now - timedelta(days=1),
        usage=(KsefKeyUsage.SYMMETRIC.value,),
    )

    selected = select_certificate((older, newer, wrong), KsefKeyUsage.TOKEN, now=now)

    assert selected is newer


def test_encrypt_token_uses_exact_token_timestamp_plaintext():
    now = datetime.now(timezone.utc) - timedelta(days=1)
    cert, private_key = _certificate(
        valid_from=now,
        usage=(KsefKeyUsage.TOKEN.value,),
    )
    encrypted = base64.b64decode(
        encrypt_token("secret-token", 1234567890, load_rsa_public_key(cert.certificate))
    )

    plaintext = private_key.decrypt(
        encrypted,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    assert plaintext == b"secret-token|1234567890"


def test_encrypt_invoice_round_trips_and_reports_hashes():
    xml = "<Faktura>zażółć</Faktura>"
    key = bytes(range(32))
    iv = bytes(range(16))

    result = encrypt_invoice(xml, key, iv)
    encrypted = base64.b64decode(result.content_b64)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    padding_length = padded[-1]

    assert padded[:-padding_length] == xml.encode("utf-8")
    assert result.original_size == len(xml.encode("utf-8"))
    assert result.encrypted_size == len(encrypted)
    assert result.original_hash_b64
    assert result.encrypted_hash_b64


def test_accepted_result_requires_remote_references():
    with pytest.raises(ValueError):
        KsefSubmissionResult(status=KsefSubmissionStatus.ACCEPTED)


def test_config_repr_redacts_token():
    config = KsefTestConfig(token="super-secret", context_nip="1234567890")

    assert "super-secret" not in repr(config)
    assert "<redacted>" in repr(config)
