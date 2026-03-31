from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.backend.agent.advisor_agent import QUERIES, QUERIES_DETAILS, QUERIES_STANDALONE, QueryType, run_advisor

router = APIRouter(prefix="/advisor", tags=["advisor"])


class AdvisorRequest(BaseModel):
    card_name: str = Field(..., description="카드 이름 (예: '현대카드 M')")
    card_company: str = Field(..., description="카드사 이름 (예: 'Hyundai', 'KB', 'Shinhan')")
    query_type: QueryType = Field(
        ..., description="질문 유형"
    )


class AdvisorResponse(BaseModel):
    answer: str
    query_used: str  # 실제 LLM으로 전송된 쿼리 (디버깅 및 UI 표시용)


@router.post("/ask", response_model=AdvisorResponse)
def ask(payload: AdvisorRequest) -> AdvisorResponse:
    try:
        answer = run_advisor(
            card_name=payload.card_name,
            card_company=payload.card_company,
            query_type=payload.query_type,
        )
    except Exception as exc:
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
