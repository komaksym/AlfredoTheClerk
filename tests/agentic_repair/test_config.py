"""Tests for agentic repair model configuration."""

from __future__ import annotations

import os
from typing import Any

from src.agentic_repair import config


def test_setup_keys_loads_dotenv_sets_tracing_and_prompts_missing_keys(
    monkeypatch,
) -> None:
    prompts: list[str] = []

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: prompts.append("dotenv"))

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        if "Deepseek" in prompt:
            return "deepseek-key"
        return "langsmith-key"

    monkeypatch.setattr(config.getpass, "getpass", fake_getpass)

    config.setup_keys()

    assert prompts == [
        "dotenv",
        "Enter your Deepseek API key: ",
        "Enter your Langsmith API key: ",
    ]
    assert os.environ["DEEPSEEK_API_KEY"] == "deepseek-key"
    assert os.environ["LANGSMITH_API_KEY"] == "langsmith-key"
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_setup_keys_does_not_prompt_for_existing_keys(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-deepseek-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "existing-langsmith-key")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    def fail_if_prompted(prompt: str) -> str:
        raise AssertionError(f"unexpected prompt: {prompt}")

    monkeypatch.setattr(config.getpass, "getpass", fail_if_prompted)

    config.setup_keys()

    assert os.environ["DEEPSEEK_API_KEY"] == "existing-deepseek-key"
    assert os.environ["LANGSMITH_API_KEY"] == "existing-langsmith-key"
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_build_repair_model_uses_default_deepseek_model(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    model = object()

    monkeypatch.setattr(config, "setup_keys", lambda: None)

    def fake_init_chat_model(model_name: str, **kwargs: Any) -> object:
        calls.append((model_name, kwargs))
        return model

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.build_repair_model()

    assert result is model
    assert calls == [(config.REPAIR_MODEL_NAME, {"temperature": 0.0})]


def test_build_repair_model_accepts_model_overrides(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    model = object()

    monkeypatch.setattr(config, "setup_keys", lambda: None)

    def fake_init_chat_model(model_name: str, **kwargs: Any) -> object:
        calls.append((model_name, kwargs))
        return model

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.build_repair_model(
        model_name="deepseek:deepseek-reasoner",
        temperature=0.2,
    )

    assert result is model
    assert calls == [("deepseek:deepseek-reasoner", {"temperature": 0.2})]
