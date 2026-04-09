import os
import sys
from loguru import logger

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.card import router as card_router
from app.api.advisor import router as advisor_router
from app.core.discord import notify_discord
from app.core.exceptions import BusinessException, SystemException

# ---------------------------------------------------------------------------
# 전역 로깅 설정 (민감 정보 보호 및 파일 저장)
# ---------------------------------------------------------------------------
logger.remove()  # 기본 핸들러 제거
logger.add(
    sys.stdout, 
    diagnose=False,  # 운영 필수: 예외 발생 시 로컬 변수 평문 노출 차단
    backtrace=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# 파일 로깅 (로컬 및 단일 서버용)
os.makedirs("logs", exist_ok=True)
logger.add(
    "logs/smartpick_{time}.log", 
    rotation="10 MB", 
    retention="10 days", 
    diagnose=False,  # 여기도 동일하게 지역 변수 가리기 적용
    backtrace=True,
    level="INFO"
)

_DESCRIPTION = """
## SmartPick-Neo API

신용카드 혜택 계산 및 추천 서비스 백엔드 API입니다.

### 주요 기능
- **카드 추천** (`POST /cards/recommend`): 유저의 카테고리별 소비 패턴을 기반으로 최적 카드 Top 3를 추천합니다.
- **영수증(Receipt) 조회**: 추천 응답의 `applied_benefits_trace` 배열에서 어떤 혜택이 얼마의 예산을 소모해 얼마를 할인했는지 확인할 수 있습니다.
- **체크박스 재계산** (`POST /cards/recalculate`): 유저가 특정 혜택을 "현실적으로 쓸 일 없음"으로 체크 해제하면, 해당 혜택을 제외한 갱신된 합산과 순위를 즉각 반환합니다.
- **카드 Q&A** (`POST /cards/qa`): 추천 결과 JSON을 바탕으로 자유 질문에 답변합니다.
- **어드바이저** (`POST /advisor/ask`): 특정 카드의 수수료, 후기, 신청방법 등 상세 정보를 제공합니다.

### 영수증 필드 안내 (`applied_benefits_trace`)
| 필드 | 타입 | 설명 |
|---|---|---|
| `benefit_id` | string | 혜택 고유 ID — 체크박스 토글 키 |
| `content` | string | 혜택 설명 (예: "DAY 음식점 10%") |
| `applied_budget` | int | 이 혜택에 배정된 예산 (원) |
| `yielded_discount` | int | 산출된 할인 금액 (원) |
| `user_choice` | bool | 유저 포함 여부 (기본 `true`) |
"""

_TAGS = [
    {
        "name": "cards",
        "description": "카드 추천, 영수증 조회, 체크박스 재계산, Q&A 엔드포인트",
    },
    {
        "name": "advisor",
        "description": "특정 카드의 수수료·후기·신청방법 등 상세 상담 엔드포인트",
    },
]

app = FastAPI(
    title="SmartPick-Neo API",
    description=_DESCRIPTION,
    version="1.3.0",
    openapi_tags=_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(card_router)
app.include_router(advisor_router)


# ---------------------------------------------------------------------------
# 전역 예외 핸들러
# ---------------------------------------------------------------------------
_GENERIC_500_MESSAGE = "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


def _error_payload(
    *,
    error_code: str,
    message: str,
    fallback: bool,
    detail: str | None = None,
) -> dict:
    payload: dict = {"error_code": str(error_code), "message": str(message), "fallback": bool(fallback)}
    if detail is not None:
        payload["detail"] = detail
    return payload


async def _notify_error_channels(exc: Exception, *, context: str) -> None:
    """
    향후 Slack 연동 가능하도록 "채널 알림" 단일 진입점을 둡니다.
    현재는 Discord만 사용합니다.
    """
    await notify_discord(exc, context=context)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.exception(
        "[ValueError] {} {} → {}: {}",
        request.method,
        request.url.path,
        "INVALID_INPUT",
        repr(exc),
    )
    return JSONResponse(
        status_code=400,
        content=_error_payload(
            error_code="INVALID_INPUT",
            message="요청 데이터가 올바르지 않습니다.",
            detail=str(exc) if str(exc) else repr(exc),
            fallback=False,
        ),
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
    logger.exception(
        "[KeyError] {} {} → {}: {}",
        request.method,
        request.url.path,
        "INVALID_INPUT",
        repr(exc),
    )
    return JSONResponse(
        status_code=400,
        content=_error_payload(
            error_code="INVALID_INPUT",
            message="필수 데이터가 누락되었습니다.",
            detail=str(exc) if str(exc) else repr(exc),
            fallback=False,
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning("[RequestValidationError] {} {} → INVALID_INPUT", request.method, request.url.path)
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            error_code="INVALID_INPUT",
            message="요청 데이터가 올바르지 않습니다.",
            detail=str(exc.errors()),
            fallback=False,
        ),
    )


@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    """예측 가능한 비즈니스 예외 — 사용자 친화적 메시지 반환."""
    logger.warning(
        "[Business Error] {} {} → {}: {}",
        request.method, request.url.path,
        exc.error_code, exc.message,
    )
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            error_code=str(exc.error_code),
            message=exc.message,
            detail=None,
            fallback=bool(getattr(exc, "fallback", False)),
        ),
    )


@app.exception_handler(SystemException)
async def system_exception_handler(request: Request, exc: SystemException) -> JSONResponse:
    """시스템 레벨 예외 — critical 로그 기록 후 응답은 generic 500으로 통일."""
    logger.exception(
        "[SYSTEM ERROR] {} {} → {}: {}",
        request.method, request.url.path,
        exc.error_code, exc.message,
    )
    await _notify_error_channels(exc, context=f"{request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            error_code=str(exc.error_code),
            message=_GENERIC_500_MESSAGE,
            detail=None,
            fallback=False,
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """미분류 예외 — 절대 조용히 묻히면 안 됨. critical 레벨로 전체 traceback 기록."""
    logger.exception(
        "[UNHANDLED ERROR] {} {} → {}",
        request.method, request.url.path, repr(exc),
    )
    await _notify_error_channels(exc, context=f"{request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            error_code="INTERNAL_SERVER_ERROR",
            message=_GENERIC_500_MESSAGE,
            detail=None,
            fallback=False,
        ),
    )


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok"}
