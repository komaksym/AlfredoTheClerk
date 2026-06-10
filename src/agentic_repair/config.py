from dotenv import load_dotenv
import os
import getpass


def setup_keys():
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
