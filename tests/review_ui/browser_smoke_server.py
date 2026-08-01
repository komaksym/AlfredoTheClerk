"""Serve the real no-candidate human-review browser smoke flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn

from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_PDF = (
    _REPO_ROOT
    / "data/synthetic_data/BROKEN_human_missing_buyer_nip.pdf"
)


class _AgentMustNotRun:
    """Fail if a blocking no-candidate fixture reaches the agent boundary."""

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> None:
        """Reject any attempt to bind tools for a manual-only fixture."""

        raise AssertionError("manual-only browser fixture must bypass the agent")


def main() -> None:
    """Start the loopback server after processing the missing-buyer-NIP PDF."""

    session = ReviewSession(model=_AgentMustNotRun())
    session.process_upload("browser-smoke.pdf", _SAMPLE_PDF.read_bytes())
    assert session.agent_warning is None
    assert session.case is not None
    assert [field.path for field in session.case.fields] == ["buyer.nip"]

    uvicorn.run(
        create_app(session=session),
        host="127.0.0.1",
        port=8001,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
