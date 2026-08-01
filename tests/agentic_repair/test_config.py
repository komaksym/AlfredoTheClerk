"""Tests for agentic repair model configuration."""

from __future__ import annotations

import os
from typing import Any

from src.agentic_repair import config


def test_setup_keys_loads_dotenv_and_prompts_only_for_missing_deepseek_key(
    monkeypatch,
) -> None:
    """Normal repair startup must not enable or require LangSmith tracing."""

    prompts: list[str] = []

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_METADATA", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: prompts.append("dotenv"))

    def fake_getpass(prompt: str) -> str:
        """Return one deterministic test key while recording the prompt."""

        prompts.append(prompt)
        return "deepseek-key"

    monkeypatch.setattr(config.getpass, "getpass", fake_getpass)

    config.setup_keys()

    assert prompts == [
        "dotenv",
        "Enter your Deepseek API key: ",
    ]
    assert os.environ["DEEPSEEK_API_KEY"] == "deepseek-key"
    assert "LANGSMITH_API_KEY" not in os.environ
    assert "LANGSMITH_TRACING" not in os.environ
    assert "LANGSMITH_HIDE_INPUTS" not in os.environ
    assert "LANGSMITH_HIDE_OUTPUTS" not in os.environ
    assert "LANGSMITH_HIDE_METADATA" not in os.environ


def test_setup_keys_masks_explicit_langsmith_opt_in(monkeypatch) -> None:
    """Explicit tracing must preserve the opt-in while hiding invoice payloads."""

    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-deepseek-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "existing-langsmith-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_METADATA", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda: None)

    def fail_if_prompted(prompt: str) -> str:
        """Fail because preconfigured repair startup must remain noninteractive."""

        raise AssertionError(f"unexpected prompt: {prompt}")

    monkeypatch.setattr(config.getpass, "getpass", fail_if_prompted)

    config.setup_keys()

    assert os.environ["DEEPSEEK_API_KEY"] == "existing-deepseek-key"
    assert os.environ["LANGSMITH_API_KEY"] == "existing-langsmith-key"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_METADATA"] == "true"


def test_build_repair_model_uses_supported_non_thinking_deepseek_model(
    monkeypatch,
) -> None:
    """Default repair calls must use current V4 Flash without thinking mode."""

    calls: list[tuple[str, dict[str, Any]]] = []
    model = object()

    monkeypatch.setattr(config, "setup_keys", lambda: None)

    def fake_init_chat_model(model_name: str, **kwargs: Any) -> object:
        """Record model initialization without contacting the provider."""

        calls.append((model_name, kwargs))
        return model

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.build_repair_model()

    assert result is model
    assert calls == [
        (
            "deepseek:deepseek-v4-flash",
            {
                "temperature": 0.0,
                "extra_body": {"thinking": {"type": "disabled"}},
            },
        )
    ]


def test_build_repair_model_accepts_model_overrides(monkeypatch) -> None:
    """Allow an explicit supported repair model and temperature override."""

    calls: list[tuple[str, dict[str, Any]]] = []
    model = object()

    monkeypatch.setattr(config, "setup_keys", lambda: None)

    def fake_init_chat_model(model_name: str, **kwargs: Any) -> object:
        """Record the explicit model configuration supplied by the caller."""

        calls.append((model_name, kwargs))
        return model

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.build_repair_model(
        model_name="deepseek:deepseek-v4-pro",
        temperature=0.2,
    )

    assert result is model
    assert calls == [
        (
            "deepseek:deepseek-v4-pro",
            {
                "temperature": 0.2,
                "extra_body": {"thinking": {"type": "disabled"}},
            },
        )
    ]
