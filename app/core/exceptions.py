"""
SmartPick 커스텀 예외 계층

비즈니스 예외 (BusinessException)
  → 예측 가능한 상황. 사용자에게 친절한 메시지 반환 (4xx)
  → NoCardsFoundError, LLMUnavailableError, InvalidInputError

시스템 예외 (SystemException)
  → 예기치 않은 심각한 오류. 개발자 즉시 알림 필요 (500)
  → DatabaseError, InternalCalculationError
"""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 에러 응답 스키마
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    error_code: str
    message: str
    fallback: bool = False  # True = Fallback 텍스트가 포함된 응답임을 클라이언트에 알림


# ---------------------------------------------------------------------------
# 기반 클래스
# ---------------------------------------------------------------------------

class SmartPickException(Exception):
    """모든 SmartPick 예외의 기반 클래스."""
    http_status: int = 500
    error_code: str = "SMARTPICK_ERROR"
    fallback: bool = False

    def __init__(self, message: str = "알 수 없는 오류가 발생했습니다."):
        super().__init__(message)
        self.message = message

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error_code=self.error_code,
            message=self.message,
            fallback=self.fallback,
        )


# ---------------------------------------------------------------------------
# 비즈니스 예외 (4xx) — Fallback 응답 가능
# ---------------------------------------------------------------------------

class BusinessException(SmartPickException):
    """예측 가능한 비즈니스 흐름 예외. 사용자에게 안내 메시지 반환."""
    http_status = 422
    error_code = "BUSINESS_ERROR"


class NoCardsFoundError(BusinessException):
    """조건에 맞는 카드가 없을 때."""
    http_status = 404
    error_code = "NO_CARDS_FOUND"

    def __init__(self, message: str = "입력하신 조건에 맞는 카드를 찾지 못했습니다."):
        super().__init__(message)


class LLMUnavailableError(BusinessException):
    """LLM 호출이 실패하거나 빈 응답이 반환될 때."""
    http_status = 503
    error_code = "LLM_UNAVAILABLE"
    fallback = True  # 클라이언트가 Fallback 텍스트임을 인지할 수 있도록

    def __init__(self, message: str = "AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해 주세요."):
        super().__init__(message)


class InvalidInputError(BusinessException):
    """요청 파라미터가 비어 있거나 유효하지 않을 때."""
    http_status = 400
    error_code = "INVALID_INPUT"

    def __init__(self, message: str = "요청 데이터가 올바르지 않습니다."):
        super().__init__(message)


# ---------------------------------------------------------------------------
# 시스템 예외 (500) — 개발자 즉시 알림 필요
# ---------------------------------------------------------------------------

class SystemException(SmartPickException):
    """예기치 않은 시스템 레벨 오류. logger.critical + 향후 Slack 알림 지점."""
    http_status = 500
    error_code = "SYSTEM_ERROR"


class DatabaseError(SystemException):
    """Supabase DB 연결 또는 쿼리 실패."""
    error_code = "DATABASE_ERROR"

    def __init__(self, message: str = "데이터베이스 오류가 발생했습니다."):
        super().__init__(message)


class InternalCalculationError(SystemException):
    """BenefitCalculator 내 예측 불가능한 계산 오류."""
    error_code = "CALCULATION_ERROR"

    def __init__(self, message: str = "혜택 계산 중 내부 오류가 발생했습니다."):
        super().__init__(message)
