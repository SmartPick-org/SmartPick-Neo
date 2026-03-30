import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


DEFAULT_MODEL = "solar-pro2"
REQUIRED_KEYS: Iterable[str] = (
    "LANGSMITH_API_KEY",
    "UPSTAGE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def init_env(project_root: Path | None = None) -> None:
    root = project_root or Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")

    for key in REQUIRED_KEYS:
        if not os.getenv(key):
            print(f"[WARN] {key}가 환경 변수에 설정되지 않았습니다.")

    os.environ.setdefault("LANGSMITH_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "Smart_Pick_V3")
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0.0):
    init_env()
    return init_chat_model(model=model, temperature=temperature)
