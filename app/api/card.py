import json
from loguru import logger
from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_llm
from app.core.exceptions import LLMUnavailableError, NoCardsFoundError
from app.repositories.card_repo import DatasetCardRepository
from app.repositories.digest_repo import DigestRepository
from app.schemas.recommend import QARequest, QAResponse, RecommendRequest, RecommendResponse
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService

router = APIRouter(prefix="/cards", tags=["cards"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json_v3"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"

# Fallback 텍스트 — LLM이 죽어도 사용자는 카드 목록을 볼 수 있음
_LLM_FALLBACK_EXPLAIN = (
    "AI 설명 생성에 실패했습니다. 아래 카드 목록은 혜택 계산 결과 기준으로 정렬되었습니다."
)


def _safe_build_recommended_cards(ranked: list[dict], explanation: str) -> list[dict]:
    """
    LLM/데이터 누락으로 인해 일부 필드가 없을 때도 응답 스키마가 깨지지 않도록 안전 빌더를 사용합니다.
    """
    cards: list[dict] = []
    for idx, card in enumerate(ranked or []):
        cards.append(
            {
                "card_name": card.get("card_name", ""),
                "card_company": card.get("card_company", ""),
                "card_id": card.get("card_id", ""),
                "annual_fee": card.get("annual_fee", 0),
                "minimum_performance": card.get("minimum_performance", 0),
                "expected_monthly_benefit": card.get("expected_monthly_benefit", 0),
                "category_breakdown": card.get("category_breakdown", []) or [],
                "explanation": explanation if idx == 0 else "",
            }
        )
    return cards


@router.post("/recommend", response_model=RecommendResponse)
# calculate_benefits가 코루틴(async)으로 변경되었으므로 엔드포인트도 async로 선언해야 함.
# FastAPI는 async 라우트 핸들러를 기본적으로 지원하며 이벤트 루프에서 실행됨.
async def recommend_cards(payload: RecommendRequest) -> RecommendResponse:
    # Pydantic 1차 검증 이후의 방어 로직 (강화)
    if payload.total_budget <= 0:
        raise ValueError("total_budget은 0보다 커야 합니다.")
    if not payload.category_spending:
        raise ValueError("category_spending은 비어 있을 수 없습니다.")
    if any(
        (v.get("total", 0) if isinstance(v, dict) else v) <= 0 
        for v in payload.category_spending.values()
    ):
        raise ValueError("category_spending의 각 값은 0보다 커야 합니다.")

    card_repo = DatasetCardRepository(DATASETS_DIR)
    digest_repo = DigestRepository(DIGEST_DIR)
    recommend_service = CardRecommendService(card_repo)

    explain_service: ExplainService | None = None
    try:
        explain_service = ExplainService(get_llm())
    except Exception as e:
        # LLM 자체 장애 → 서비스는 중단하지 않고 fallback 텍스트로 진행
        logger.exception("[LLM init] ExplainService 생성 실패: %s", repr(e))
        explain_service = None

    # 1. 필터링 — 조건에 맞는 카드가 없으면 404 반환
    filtered = recommend_service.filter_cards(payload.total_budget, payload.category_spending)
    if not filtered:
        raise NoCardsFoundError(
            f"월 {payload.total_budget:,}원 예산 및 선택 카테고리 조건에 맞는 카드가 없습니다."
        )

    # 2. 혜택 계산 & 랭킹
    try:
        calc_results = await recommend_service.calculate_benefits(
            filtered, payload.total_budget, payload.category_spending
        )
    except KeyError as e:
        # 필수 데이터 누락 등 → raw 500 방지
        logger.exception("[recommend_cards] calculate_benefits KeyError: %s", repr(e))
        raise ValueError("혜택 계산에 필요한 데이터가 누락되었습니다.") from e
    except ValueError as e:
        logger.exception("[recommend_cards] calculate_benefits ValueError: %s", repr(e))
        raise ValueError(str(e))

    ranked = recommend_service.rank_top(calc_results, top_n=3)

    if not ranked:
        raise NoCardsFoundError("혜택 계산 결과가 없습니다.")

    # 3. LLM 설명 생성 — 실패해도 카드 목록은 반환 (Graceful Degradation)
    digests = []
    try:
        # 모든 카드의 Digest를 시도하여 상세 내역 생성에 대비
        digests = [digest_repo.get_digest(card.get("_card_data", {})) for card in ranked]
        top_digest = digests[0] if digests else ""
    except Exception as e:
        logger.warning("[recommend_cards] digest 로드 실패: %s", repr(e))
        top_digest = ""
        digests = [""] * len(ranked)

    explanation = _LLM_FALLBACK_EXPLAIN
    if explain_service is not None:
        try:
            explanation = await explain_service.explain(
                payload.total_budget, payload.category_spending, ranked, top_digest
            )
            if not explanation or not explanation.strip():
                explanation = _LLM_FALLBACK_EXPLAIN
        except Exception as e:
            logger.warning("[LLM Fallback] explain() 실패, Fallback 텍스트 사용: %s", repr(e))
            explanation = _LLM_FALLBACK_EXPLAIN

    try:
        # 상세 Tracing 기능이 포함된 빌더 호출
        recommended_cards = explain_service.build_recommended_cards(ranked, explanation, digests)
    except Exception as e:
        logger.warning("[recommend_cards] 상세 빌더 실패, 안전 빌더 사용: %s", repr(e))
        recommended_cards = _safe_build_recommended_cards(ranked, explanation)


    return RecommendResponse(recommended_cards=recommended_cards, explanation=explanation)


@router.post("/qa", response_model=QAResponse)
async def answer_qa(payload: QARequest) -> QAResponse:
    """
    추천 결과 데이터(JSON)를 바탕으로 사용자의 자유 질문에 대해 답변합니다.
    
    - **raw_data**: 추천 결과로 반환된 전체 JSON 문자열 (계산 근거가 포함됨)
    - **question**: 사용자가 입력한 자유 질문 (예: '왜 이 카드가 1순위야?')
    """
    # raw_data는 "추천 결과 원본 JSON 문자열"이라서, 최소한 JSON 파싱 가능 여부를 확인합니다.
    try:
        json.loads(payload.raw_data)
    except Exception as e:
        raise ValueError("raw_data는 유효한 JSON 문자열이어야 합니다.") from e

    try:
        explain_service = ExplainService(get_llm())
    except Exception as e:
        logger.exception("[QA] ExplainService 생성 실패: %s", repr(e))
        raise LLMUnavailableError()

    try:
        answer = await explain_service.answer_qa(payload.raw_data, payload.question)
        if not answer or not answer.strip():
            raise LLMUnavailableError()
    except LLMUnavailableError:
        raise
    except KeyError as e:
        # 데이터/포맷 누락 등으로 인한 KeyError라도 raw 500 방지
        logger.exception("[QA] answer_qa KeyError: %s", repr(e))
        raise LLMUnavailableError()
    except Exception as e:
        logger.warning("[LLM Fallback] answer_qa() 실패, Fallback 메시지 반환: %s", repr(e))
        raise LLMUnavailableError()

    return QAResponse(answer=answer)
