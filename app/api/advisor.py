from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.advise_service import QUERIES, QUERIES_DETAILS, QUERIES_STANDALONE, QueryType, get_advice

from loguru import logger

router = APIRouter(prefix="/advisor", tags=["advisor"])


class AdvisorRequest(BaseModel):
    card_name: str = Field(..., description="카드 이름 (예: '현대카드 M')", examples=["현대카드 T3 Edition2"])
    query_type: QueryType = Field(
        ..., description="질문 유형", examples=["reviews", "credit_fees", "installment_fees"]
    )


class AdvisorResponse(BaseModel):
    answer: str
    query_used: str  # 실제 LLM으로 전송된 쿼리 (디버깅 및 UI 표시용)


@router.post("/ask", response_model=AdvisorResponse)
async def ask(payload: AdvisorRequest) -> AdvisorResponse:
    """
    특정 신용카드에 대한 상세 정보(수수료, 할부, 후기 등)를 전문 상담원처럼 답변합니다.
    
    - **card_name**: 마크다운 파일 검색에 사용되는 카드 전체 명칭 (예: 'KB 국민 굿데이 카드')
    - **query_type**: 버튼 기반 질문 유형 (reviews, credit_fees, installment_fees 등)
    """
    logger.info(f"[AdvisorAPI] POST /ask | card={payload.card_name} | type={payload.query_type}")
    try:
        answer = await get_advice(
            card_name=payload.card_name,
            query_type=payload.query_type,
        )
    except Exception as exc:
        logger.exception(f"[AdvisorAPI] get_advice 처리 중 오류 발생: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return AdvisorResponse(
        answer=answer,
        query_used=QUERIES[payload.query_type],
    )


@router.get("/queries", response_model=dict[str, dict[str, str]])
def list_queries() -> dict[str, dict[str, str]]:
    """버튼 그룹별 query_type 목록 반환 (프론트엔드 버튼 구성용)"""
    return {
        "standalone": QUERIES_STANDALONE,
        "details": QUERIES_DETAILS,
    }
