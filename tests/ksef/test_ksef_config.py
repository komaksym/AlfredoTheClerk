"""Tests for strict KSeF TEST runtime configuration."""

from __future__ import annotations

import pytest

from src.ksef.config import KsefTestConfig


def test_require_credentials_accepts_complete_test_configuration() -> None:
    """Strict live CI may proceed only when both credentials are present."""

    KsefTestConfig(token="token", context_nip="1234567890").require_credentials()


@pytest.mark.parametrize(
    ("config", "missing_names"),
    [
        (KsefTestConfig(), ("KSEF_TEST_TOKEN", "KSEF_TEST_CONTEXT_NIP")),
        (KsefTestConfig(context_nip="1234567890"), ("KSEF_TEST_TOKEN",)),
        (KsefTestConfig(token="token"), ("KSEF_TEST_CONTEXT_NIP",)),
    ],
)
def test_require_credentials_names_every_missing_secret(
    config: KsefTestConfig,
    missing_names: tuple[str, ...],
) -> None:
    """Credential failures must be actionable without exposing secret values."""

    with pytest.raises(ValueError) as raised:
        config.require_credentials()

    message = str(raised.value)
    for name in missing_names:
        assert name in message
    assert "token=<redacted>" not in message
