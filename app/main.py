from loguru import logger

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.card import router as card_router
from app.core.discord import notify_discord
from app.core.exceptions import BusinessException, SystemException


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(card_router)


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
