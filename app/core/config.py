import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from functools import lru_cache
from langchain.chat_models import init_chat_model
from langchain_upstage import ChatUpstage

# .env를 모듈 로드 시점에 즉시 반영 (LOGTAIL_SOURCE_TOKEN 등 상수가 올바르게 읽히도록)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_MODEL = "solar-pro2"
REQUIRED_KEYS: Iterable[str] = (
    "LANGSMITH_API_KEY",
    "UPSTAGE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
)

# --- LLM Resilience Settings ---
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30.0"))
LLM_TOTAL_TIMEOUT = float(os.getenv("LLM_TOTAL_TIMEOUT", "65.0")) # Total time including all retries
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2")) # Number of extra attempts (0 = no retries)
LLM_CB_FAILURE_THRESHOLD = int(os.getenv("LLM_CB_FAILURE_THRESHOLD", "5"))
LLM_CB_RECOVERY_TIMEOUT = int(os.getenv("LLM_CB_RECOVERY_TIMEOUT", "60"))

LOGTAIL_SOURCE_TOKEN: str | None = os.getenv("LOGTAIL_SOURCE_TOKEN")
LOGTAIL_HOST: str | None = os.getenv("LOGTAIL_HOST")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"
MANUALS_DIR = PROJECT_ROOT / "datasets" / "manuals"
TERMS_DIR = PROJECT_ROOT / "datasets" / "terms"



def init_env(project_root: Path | None = None) -> None:
    root = project_root or Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")

    for key in REQUIRED_KEYS:
        if not os.getenv(key):
            if os.getenv("ENV") == "production":
                raise RuntimeError(f"Missing required environment variable: {key}")
            else:
                print(f"[WARN] {key}가 환경 변수에 설정되지 않았습니다.")

    os.environ.setdefault("LANGSMITH_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "Smart_Pick_V3")
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")


@lru_cache()
def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0.0):
    init_env()
    # solar 모델의 경우 ChatUpstage를 직접 사용
    if "solar" in model.lower():
        return ChatUpstage(model=model, 
            temperature=temperature,
            request_timeout=LLM_TIMEOUT
            )
    return init_chat_model(
        model=model, 
        temperature=temperature,
        request_timeout=LLM_TIMEOUT
    )
