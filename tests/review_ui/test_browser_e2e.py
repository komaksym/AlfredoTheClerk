"""Real-browser coverage for the complete local human-review workflow."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import os
import socket
from threading import Thread
from time import monotonic, sleep
from typing import Any

import httpx
from playwright.sync_api import Page, expect
import pytest
import uvicorn

from src.review_ui.app import create_app
from src.review_ui.session import ReviewSession


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = (
    _REPO_ROOT
    / "data/synthetic_data/BROKEN_human_missing_buyer_nip.pdf"
)
_BUYER_NIP = "5423511615"


class _AgentMustNotRun:
    """Reject model use for the manual-only browser fixture."""

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> None:
        """Fail if the no-candidate fixture reaches the agent boundary."""

        raise AssertionError("manual-only browser fixture must bypass the agent")


def _unused_port() -> int:
    """Reserve and release one loopback port for the test server."""

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, object]:
    """Use a system Chromium override only when the environment supplies one."""

    executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if executable:
        return {"executable_path": executable, "args": ["--no-sandbox"]}
    return {}


@pytest.fixture(scope="module")
def review_server_url() -> Iterator[str]:
    """Serve one empty real FastAPI review app for browser interaction."""

    port = _unused_port()
    session = ReviewSession(model=_AgentMustNotRun())
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(session=session),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = monotonic() + 15
    while monotonic() < deadline:
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("browser E2E server did not start")

    yield url

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


@pytest.mark.browser_e2e
def test_browser_completes_manual_review_and_toolbar_actions(
    page: Page,
    review_server_url: str,
    tmp_path: Path,
) -> None:
    """Upload, correct, download, fullscreen, and finish through real JS."""

    page.goto(review_server_url)
    page.locator("#invoice").set_input_files(_FIXTURE)
    page.get_by_role("button", name="Process invoice").click()
    page.wait_for_url(f"{review_server_url}/review")

    manual = page.locator('[data-manual-input="buyer.nip"]')
    manual.focus()
    manual.fill(_BUYER_NIP)
    mode = page.locator(
        'input[name="mode::buyer.nip"][value="manual"]'
    )
    expect(mode).to_be_checked()

    pdf_download_path = tmp_path / "invoice.pdf"
    with page.expect_download() as pdf_download_info:
        page.get_by_label("Download original PDF").click()
    pdf_download = pdf_download_info.value
    pdf_download.save_as(pdf_download_path)
    assert pdf_download_path.read_bytes().startswith(b"%PDF")

    page.evaluate(
        """
        () => {
          const card = document.querySelector("[data-document-card]");
          window.__fullscreenCalls = [];
          window.__fakeFullscreenElement = null;
          Object.defineProperty(document, "fullscreenElement", {
            configurable: true,
            get: () => window.__fakeFullscreenElement,
          });
          card.requestFullscreen = async () => {
            window.__fullscreenCalls.push("enter");
            window.__fakeFullscreenElement = card;
            document.dispatchEvent(new Event("fullscreenchange"));
          };
          document.exitFullscreen = async () => {
            window.__fullscreenCalls.push("exit");
            window.__fakeFullscreenElement = null;
            document.dispatchEvent(new Event("fullscreenchange"));
          };
        }
        """
    )
    fullscreen = page.get_by_role("button", name="Enter fullscreen")
    fullscreen.click()
    page.wait_for_function("window.__fullscreenCalls.length === 1")
    expect(page.get_by_role("button", name="Exit fullscreen")).to_be_visible()
    page.get_by_role("button", name="Exit fullscreen").click()
    page.wait_for_function("window.__fullscreenCalls.length === 2")
    assert page.evaluate("window.__fullscreenCalls") == ["enter", "exit"]

    page.locator('input[name="reviewer_id"]').fill("Browser E2E")
    page.get_by_role("button", name="Confirm & continue").click()
    page.wait_for_url(f"{review_server_url}/result")
    expect(page.get_by_role("heading", name="READY_FOR_KSEF")).to_be_visible()

    xml_path = tmp_path / "invoice-fa3.xml"
    with page.expect_download() as xml_download_info:
        page.get_by_role("link", name="Download FA(3) XML").click()
    xml_download_info.value.save_as(xml_path)
    xml = xml_path.read_text(encoding="utf-8")
    assert _BUYER_NIP in xml
