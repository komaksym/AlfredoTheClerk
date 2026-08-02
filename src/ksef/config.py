"""TEST-only KSeF runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

KSEF_TEST_BASE_URL = "https://api-test.ksef.mf.gov.pl/v2"


@dataclass(frozen=True, kw_only=True)
class KsefTestConfig:
    """Credentials and polling policy for one KSeF TEST submission run."""

    token: str = ""
    context_nip: str = ""
    poll_interval_seconds: float = 0.25
    poll_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "KsefTestConfig":
        """Load only the TEST credentials allowed by this slice."""

        return cls(
            token=os.getenv("KSEF_TEST_TOKEN", "").strip(),
            context_nip=os.getenv("KSEF_TEST_CONTEXT_NIP", "").strip(),
        )

    def require_credentials(self) -> None:
        """Raise a clear error unless both strict TEST credentials exist."""

        missing = []
        if not self.token:
            missing.append("KSEF_TEST_TOKEN")
        if not self.context_nip:
            missing.append("KSEF_TEST_CONTEXT_NIP")
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Missing required KSeF TEST credentials: {names}")

    def __repr__(self) -> str:
        """Return a representation that redacts the KSeF token."""

        return (
            "KsefTestConfig(token=<redacted>, "
            f"context_nip={self.context_nip!r}, "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, "
            f"poll_timeout_seconds={self.poll_timeout_seconds!r})"
        )
