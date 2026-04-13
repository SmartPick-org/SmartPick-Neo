import os
import sys
from loguru import logger
from logtail import LogtailHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.card import router as card_router
from app.api.advisor import router as advisor_router
from app.core.discord import notify_discord
from app.core.exceptions import BusinessException, SystemException
from app.core.config import LOGTAIL_SOURCE_TOKEN

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

# Better Stack (Logtail) 로깅
_logtail_token = os.environ.get("LOGTAIL_SOURCE_TOKEN", "")
if _logtail_token:
    from logtail import LogtailHandler
    _logtail_handler = LogtailHandler(source_token=_logtail_token)
    logger.add(_logtail_handler, level="INFO", diagnose=False, backtrace=False)
else:
    logger.warning("LOGTAIL_SOURCE_TOKEN not set — Better Stack logging disabled")

app = FastAPI(
    title="SmartPick API",
    version="1.0.0",
    description="신용카드 추천 및 어드바이저 서비스 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(card_router, prefix="/api/v1")
app.include_router(advisor_router, prefix="/api/v1")


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
