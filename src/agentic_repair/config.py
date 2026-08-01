"""Configuration and model construction for agentic invoice repair."""

import getpass
import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

REPAIR_MODEL_NAME = "deepseek:deepseek-v4-flash"
REPAIR_MODEL_TEMPERATURE = 0.0
REPAIR_MODEL_EXTRA_BODY = {"thinking": {"type": "disabled"}}
_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def setup_keys() -> None:
    """Load local environment and require only the DeepSeek repair key."""

    load_dotenv()

    if not os.getenv("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = getpass.getpass(
            "Enter your Deepseek API key: "
        )

    if _langsmith_tracing_enabled():
        os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_METADATA"] = "true"


def _langsmith_tracing_enabled() -> bool:
    """Return whether the operator explicitly enabled LangSmith tracing."""

    value = os.getenv("LANGSMITH_TRACING", "")
    return value.strip().lower() in _TRUTHY_ENV_VALUES


def build_repair_model(
    *,
    model_name: str = REPAIR_MODEL_NAME,
    temperature: float = REPAIR_MODEL_TEMPERATURE,
) -> BaseChatModel:
    """Build the non-thinking chat model used by the repair workflow."""

    setup_keys()

    return init_chat_model(
        model_name,
        temperature=temperature,
        extra_body=REPAIR_MODEL_EXTRA_BODY,
    )
