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
from app.core.config import LOGTAIL_SOURCE_TOKEN, LOGTAIL_HOST

# ---------------------------------------------------------------------------
# 전역 로깅 설정 (민감 정보 보호 및 파일 저장)
# ---------------------------------------------------------------------------
from app.core.logger import init_logger
from app.core.middleware import logging_middleware

init_logger()

# Better Stack (Logtail) 로깅
# LogtailHandler는 표준 logging.Handler이므로 loguru 레코드를 LogRecord로 변환하는 브릿지 필요
if LOGTAIL_SOURCE_TOKEN:
    import logging
    _logtail_handler = LogtailHandler(source_token=LOGTAIL_SOURCE_TOKEN, host=LOGTAIL_HOST) if LOGTAIL_HOST else LogtailHandler(source_token=LOGTAIL_SOURCE_TOKEN)

    def _logtail_sink(message):
        record = message.record
        log_record = logging.LogRecord(
            name=record["name"],
            level=getattr(logging, record["level"].name, logging.INFO),
            pathname=str(record["file"].path),
            lineno=record["line"],
            msg=record["message"],
            args=(),
            exc_info=record["exception"],
        )
        _logtail_handler.emit(log_record)

    logger.add(_logtail_sink, level="INFO")
else:
    logger.warning("LOGTAIL_SOURCE_TOKEN not set — Better Stack logging disabled")

app = FastAPI(
    title="SmartPick API",
    version="1.0.0",
    description="신용카드 추천 및 어드바이저 서비스 API",
)

app.middleware("http")(logging_middleware)

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
    """
    KeyError는 정상적인 사용자 입력 경로에서는 나올 수 없습니다 (Pydantic이 사전 검증).
    여기까지 올라왔다면 내부 로직/데이터 버그 → 500 + Discord 알림.
    """
    logger.exception(
        "[KeyError → SERVER BUG] {} {} → {}: {}",
        request.method,
        request.url.path,
        "INTERNAL_SERVER_ERROR",
        repr(exc),
    )
    await _notify_error_channels(
        exc,
        context=f"{request.method} {request.url.path} (unhandled KeyError)",
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            error_code="INTERNAL_SERVER_ERROR",
            message=_GENERIC_500_MESSAGE,
            detail=None,
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
