"""Serve a real extraction-to-agent-failure browser smoke flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn

from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_PDF = (
    _REPO_ROOT
    / "data/synthetic_data/BROKEN_agent_ambiguous_seller_nip.pdf"
)


class _FailingRepairModel:
    """Minimal model boundary that fails only when the real agent invokes it."""

    def bind_tools(
        self,
        tools: list[Any],
        *,
        tool_choice: object = None,
    ) -> _FailingRepairModel:
        """Accept and verify the production single-tool binding contract."""

        assert tools
        assert tool_choice == {
            "type": "function",
            "function": {"name": "apply_repair_plan"},
        }
        return self

    def invoke(self, messages: list[Any]) -> object:
        """Prove the agent reached the model boundary, then simulate an outage."""

        assert messages
        raise RuntimeError("browser smoke agent failure")


def main() -> None:
    """Start the loopback server after processing the real ambiguous-NIP PDF."""

    session = ReviewSession(model=_FailingRepairModel())
    session.process_upload("browser-smoke.pdf", _SAMPLE_PDF.read_bytes())
    assert session.agent_warning is not None
    assert session.case is not None
    assert [field.path for field in session.case.fields] == ["seller.nip"]

    uvicorn.run(
        create_app(session=session),
        host="127.0.0.1",
        port=8001,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
