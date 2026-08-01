"""Run the local Alfredo human-review web application."""

from __future__ import annotations

import uvicorn

from src.agentic_repair.config import build_repair_model
from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession


def main() -> None:
    """Build the repair model once and serve the local app on loopback only."""

    session = ReviewSession(model=build_repair_model())
    uvicorn.run(
        create_app(session=session),
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
