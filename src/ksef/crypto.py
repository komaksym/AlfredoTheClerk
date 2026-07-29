"""Cryptographic helpers required by KSeF TEST submission."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from src.ksef.models import KsefKeyUsage, KsefPublicCertificate


@dataclass(frozen=True, kw_only=True)
class EncryptedInvoice:
    """Encrypted invoice bytes and KSeF-required integrity metadata."""

    content_b64: str
    original_hash_b64: str
    original_size: int
    encrypted_hash_b64: str
    encrypted_size: int


def select_certificate(
    certificates: tuple[KsefPublicCertificate, ...],
    usage: KsefKeyUsage,
    *,
    now: datetime | None = None,
) -> KsefPublicCertificate:
    """Select the newest currently valid certificate for one KSeF purpose."""

    current = now or datetime.now(timezone.utc)
    eligible = [
        item
        for item in certificates
        if usage.value in item.usage
        and item.valid_from <= current <= item.valid_to
    ]
    if not eligible:
        raise ValueError(f"no valid KSeF certificate for {usage.value}")
    return max(eligible, key=lambda item: item.valid_from)


def load_rsa_public_key(certificate_b64: str) -> rsa.RSAPublicKey:
    """Decode one KSeF DER certificate and return its RSA public key."""

    cert = x509.load_der_x509_certificate(base64.b64decode(certificate_b64))
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("KSeF encryption certificate does not contain an RSA key")
    return key


def rsa_oaep_sha256_encrypt(public_key: rsa.RSAPublicKey, value: bytes) -> bytes:
    """Encrypt bytes with the RSA-OAEP profile required by KSeF."""

    return public_key.encrypt(
        value,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def encrypt_token(token: str, timestamp_ms: int, public_key: rsa.RSAPublicKey) -> str:
    """Encrypt `token|timestampMs` and encode it for the auth request."""

    plaintext = f"{token}|{timestamp_ms}".encode()
    return base64.b64encode(rsa_oaep_sha256_encrypt(public_key, plaintext)).decode()


def encrypt_symmetric_key(key: bytes, public_key: rsa.RSAPublicKey) -> str:
    """Encrypt one AES session key for KSeF."""

    return base64.b64encode(rsa_oaep_sha256_encrypt(public_key, key)).decode()


def encrypt_invoice(xml: str, key: bytes, iv: bytes) -> EncryptedInvoice:
    """Encrypt exact UTF-8 FA(3) bytes with AES-256-CBC and PKCS#7 padding."""

    if len(key) != 32:
        raise ValueError("AES key must be 256 bits")
    if len(iv) != 16:
        raise ValueError("AES IV must be 128 bits")

    original = xml.encode("utf-8")
    padder = sym_padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(original) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()

    return EncryptedInvoice(
        content_b64=base64.b64encode(encrypted).decode(),
        original_hash_b64=_sha256_b64(original),
        original_size=len(original),
        encrypted_hash_b64=_sha256_b64(encrypted),
        encrypted_size=len(encrypted),
    )


def _sha256_b64(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode()
