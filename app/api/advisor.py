from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.advise_service import QUERIES, QUERIES_DETAILS, QUERIES_STANDALONE, QueryType, get_advice

from loguru import logger

router = APIRouter(prefix="/advisor", tags=["advisor"])


class AdvisorRequest(BaseModel):
    card_name: str = Field(
        ...,
        description="카드 전체 명칭. 마크다운 파일 검색에 그대로 사용됩니다.",
        examples=["현대카드 T3 Edition2"],
    )
    query_type: QueryType = Field(
        ...,
        description=(
            "질문 유형. 버튼 기반으로 고정된 6개 중 하나를 전달합니다. "
            "상단 버튼: `reviews`, `how_to_apply`. "
            "'추가 정보' 하위 버튼: `credit_fees`, `international_fees`, `late_payment`, `revolving`. "
            "정확한 목록은 `GET /advisor/queries` 응답 키를 참고하세요."
        ),
        examples=["reviews"],
    )


class AdvisorResponse(BaseModel):
    answer: str = Field(
        ...,
        description=(
            "LLM이 생성한 자연어 답변. query_type에 따라 포맷이 달라집니다 "
            "(예: `reviews`는 `[전반적 평가]`/`[참고한 후기 목록]`/`[주요 불만 및 페인포인트]` "
            "세 섹션, `credit_fees`는 불릿 포인트 목록)."
        ),
        examples=["[전반적 평가]\n실사용자들은 주유 할인과 단순한 실적 구조에 만족하는 편입니다. ..."],
    )
    query_used: str = Field(
        ...,
        description=(
            "실제 LLM에 전달된 시스템 쿼리 원문. `GET /advisor/queries` 응답에서 해당 "
            "`query_type` 키에 매칭되는 value와 동일한 문자열입니다. 디버깅·UI 표시용."
        ),
        examples=["이 카드의 실사용자 후기를 검색해서 아래 형식으로만 답해줘. ..."],
    )


@router.post("/ask", response_model=AdvisorResponse)
async def ask(payload: AdvisorRequest) -> AdvisorResponse:
    """
    특정 신용카드에 대한 상세 정보(수수료, 할부, 후기 등)를 전문 상담원처럼 답변합니다.

    - **card_name**: 마크다운 파일 검색에 사용되는 카드 전체 명칭 (예: 'KB 국민 굿데이 카드')
    - **query_type**: 버튼 기반 질문 유형. `GET /advisor/queries` 응답의 key와 일치해야 합니다
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
    """
    버튼 그룹별 query_type 목록 반환 (프론트엔드 버튼 구성용).

    응답 구조는 **고정된 두 개의 최상위 키**로 이루어집니다:
    - `standalone`: 최상위 버튼 그룹. key는 `reviews`, `how_to_apply`.
    - `details`: '추가 정보' 하위 버튼 그룹. key는 `credit_fees`, `international_fees`,
      `late_payment`, `revolving`.

    각 value는 `{query_type: 해당 유형의 내부 프롬프트 문자열}` 형태의 dict입니다.
    이 value(프롬프트 문자열)는 `POST /advisor/ask` 응답의 `query_used` 필드와 동일합니다.
    """
    return {
        "standalone": QUERIES_STANDALONE,
        "details": QUERIES_DETAILS,
    }
