import getpass
import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

REPAIR_MODEL_NAME = "deepseek:deepseek-chat"
REPAIR_MODEL_TEMPERATURE = 0.0


def setup_keys() -> None:
    """Load environment keys required for repair agent runs."""

    load_dotenv()

    if not os.getenv("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = getpass.getpass(
            "Enter your Deepseek API key: "
        )

    os.environ["LANGSMITH_TRACING"] = "true"
    if not os.getenv("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_API_KEY"] = getpass.getpass(
            "Enter your Langsmith API key: "
        )


def build_repair_model(
    *,
    model_name: str = REPAIR_MODEL_NAME,
    temperature: float = REPAIR_MODEL_TEMPERATURE,
) -> BaseChatModel:
    """Build the chat model used by the agentic repair workflow."""

    setup_keys()

    return (init_chat_model(model_name, temperature=temperature),)
