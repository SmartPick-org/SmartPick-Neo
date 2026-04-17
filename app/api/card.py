import json
from loguru import logger
from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_llm
from app.core.exceptions import LLMUnavailableError, NoCardsFoundError
from app.repositories.card_repo import DatasetCardRepository
from app.repositories.digest_repo import DigestRepository
from app.schemas.cards import CardListItem, CardListResponse
from app.schemas.recommend import (
    QARequest, QAResponse, RecommendRequest, RecommendResponse,
    RecalculateRequest, RecalculateResponse,
    CompareRequest, CompareResponse,
    CategoryComparison,
)
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService
from app.tools.Calc_tool import BenefitCalculator

router = APIRouter(prefix="/cards", tags=["cards"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json_v4"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"

# Fallback 텍스트 — LLM이 죽어도 사용자는 카드 목록을 볼 수 있음
_LLM_FALLBACK_EXPLAIN = (
    "AI 설명 생성에 실패했습니다. 아래 카드 목록은 혜택 계산 결과 기준으로 정렬되었습니다."
)


@router.get(
    "",
    response_model=CardListResponse,
    summary="카드 카탈로그 (목록)",
    description="프론트 Step2 드롭다운을 위한 카드 목록 조회 API입니다.",
)
async def list_cards() -> CardListResponse:
    card_repo = DatasetCardRepository(DATASETS_DIR)
    all_cards = card_repo.list_cards()

    items: list[CardListItem] = []
    for card in all_cards:
        card_meta = card.get("card_meta", {}) or {}
        categories = sorted(list(card.get("_card_categories", set()) or set()))

        # digest_summary는 후순위(비필수) — Step2의 선택 동작을 위해 기본값으로 빈 문자열을 제공합니다.
        items.append(
            CardListItem(
                card_id=str(card_meta.get("card_id", "")),
                card_name=str(card_meta.get("card_name", "")),
                card_company=str(card_meta.get("card_company", "")),
                annual_fee=int(card_meta.get("annual_fee_domestic", 0) or 0),
                minimum_performance=int(card_meta.get("minimum_performance", 0) or 0),
                categories=categories,
                digest_summary="",
            )
        )

    return CardListResponse(cards=items)


def _to_recommend_card(card_result: dict, *, explanation: str = "") -> dict:
    """
    ExplainService 없이도 CompareResponse 스키마를 만족시키기 위한 카드 변환 헬퍼.
    (explanation은 LLM 실패 시 빈 문자열로 내려줄 수 있습니다.)
    """
    return {
        "card_name": card_result.get("card_name", ""),
        "card_company": card_result.get("card_company", ""),
        "card_id": card_result.get("card_id", ""),
        "annual_fee": card_result.get("annual_fee", 0),
        "minimum_performance": card_result.get("minimum_performance", 0),
        "expected_monthly_benefit": card_result.get("expected_monthly_benefit", 0),
        "expected_yearly_benefit": card_result.get("expected_yearly_benefit", 0),
        "category_breakdown": card_result.get("category_breakdown", []) or [],
        "applied_benefits_trace": card_result.get("applied_benefits_trace", []) or [],
        "explanation": explanation,
    }


@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="기존 카드 vs 추천 카드 비교",
    description="프론트 Compare 모드 결과 화면을 위한 비교 API입니다.",
)
async def compare_cards(payload: CompareRequest) -> CompareResponse:
    card_repo = DatasetCardRepository(DATASETS_DIR)
    recommend_service = CardRecommendService(card_repo)

    all_cards = card_repo.list_cards()
    current_card = None
    for card in all_cards:
        card_meta = card.get("card_meta", {}) or {}
        if str(card_meta.get("card_id", "")) == payload.current_card_id:
            current_card = card
            break

    if current_card is None:
        raise NoCardsFoundError("비교할 카드가 데이터셋에서 발견되지 않았습니다.")

    try:
        current_results = await recommend_service.calculate_benefits(
            [current_card], payload.total_budget, payload.category_spending
        )
    except KeyError as e:
        logger.exception("[compare] calculate_benefits current KeyError: %s", repr(e))
        raise ValueError("혜택 계산에 필요한 데이터가 누락되었습니다.") from e
    except ValueError as e:
        logger.exception("[compare] calculate_benefits current ValueError: %s", repr(e))
        raise ValueError(str(e))

    if not current_results:
        raise NoCardsFoundError("기존 카드 혜택 계산 결과가 없습니다.")

    current_card_result = current_results[0]

    # 추천 후보는 기존 추천 로직의 필터를 그대로 재사용합니다.
    filtered = recommend_service.filter_cards(payload.total_budget, payload.category_spending)
    if not filtered:
        raise NoCardsFoundError(
            f"월 {payload.total_budget:,}원 예산 및 선택 카테고리 조건에 맞는 카드가 없습니다."
        )

    try:
        calc_results = await recommend_service.calculate_benefits(
            filtered, payload.total_budget, payload.category_spending
        )
    except KeyError as e:
        logger.exception("[compare] calculate_benefits KeyError: %s", repr(e))
        raise ValueError("혜택 계산에 필요한 데이터가 누락되었습니다.") from e
    except ValueError as e:
        logger.exception("[compare] calculate_benefits ValueError: %s", repr(e))
        raise ValueError(str(e))

    ranked = recommend_service.rank_top(calc_results, top_n=3)
    if not ranked:
        raise NoCardsFoundError("혜택 계산 결과가 없습니다.")

    recommended_cards_results = ranked
    recommended_card_result = recommended_cards_results[0]

    # LLM 설명은 후순위(옵션) — 카드 비교 결과 자체는 항상 반환하도록 구성합니다.
    explain_service: ExplainService | None = None
    try:
        explain_service = ExplainService(get_llm())
    except Exception as e:
        logger.exception("[compare] ExplainService init failed: %s", repr(e))
        explain_service = None

    compare_explanation = ""
    if explain_service is not None:
        try:
            compare_explanation = await explain_service.compare(
                payload.total_budget,
                payload.category_spending,
                current_card_result,
                recommended_card_result,
            )
        except Exception as e:
            logger.exception("[compare] explain_service.compare failed: %s", repr(e))
            compare_explanation = ""

    if explain_service is not None:
        current_card_obj = explain_service.build_recommended_cards(
            [current_card_result], explanation="", digests=None
        )[0]
        recommended_cards_obj = explain_service.build_recommended_cards(
            recommended_cards_results, explanation="", digests=None
        )
    else:
        current_card_obj = _to_recommend_card(current_card_result, explanation="")
        recommended_cards_obj = [
            _to_recommend_card(c, explanation="") for c in recommended_cards_results
        ]

    recommended_card_obj = recommended_cards_obj[0]

    monthly_diff = int(
        recommended_card_result.get("expected_monthly_benefit", 0)
        - current_card_result.get("expected_monthly_benefit", 0)
    )
    yearly_diff = int(
        recommended_card_result.get("expected_yearly_benefit", recommended_card_result.get("expected_monthly_benefit", 0) * 12)
        - current_card_result.get("expected_yearly_benefit", current_card_result.get("expected_monthly_benefit", 0) * 12)
    )

    current_map = {
        cb.get("category", ""): cb.get("monthly_discount_krw", 0) or 0
        for cb in (current_card_result.get("category_breakdown", []) or [])
    }
    recommended_map = {
        cb.get("category", ""): cb.get("monthly_discount_krw", 0) or 0
        for cb in (recommended_card_result.get("category_breakdown", []) or [])
    }

    categories = sorted(
        set(current_map.keys()) | set(recommended_map.keys()),
        key=lambda c: recommended_map.get(c, 0) - current_map.get(c, 0),
        reverse=True,
    )

    category_comparison = [
        CategoryComparison(
            category=cat,
            current_benefit=int(current_map.get(cat, 0) or 0),
            recommended_benefit=int(recommended_map.get(cat, 0) or 0),
            diff=int((recommended_map.get(cat, 0) or 0) - (current_map.get(cat, 0) or 0)),
        )
        for cat in categories
    ]

    return CompareResponse(
        current_card=current_card_obj,
        recommended_cards=recommended_cards_obj,
        recommended_card=recommended_card_obj,
        monthly_diff=monthly_diff,
        yearly_diff=yearly_diff,
        category_comparison=category_comparison,
        explanation=compare_explanation,
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
                "expected_yearly_benefit": card.get("expected_yearly_benefit", 0),
                "category_breakdown": card.get("category_breakdown", []) or [],
                "applied_benefits_trace": card.get("applied_benefits_trace", []) or [],
                "explanation": explanation if idx == 0 else "",
            }
        )
    return cards


@router.post("/recommend", response_model=RecommendResponse, summary="카드 추천 및 혜택 예측", description="""
사용자의 월간 소비 패턴을 분석하여 가장 높은 혜택을 주는 카드를 최대 3장 추천합니다.
V4 엔진을 사용하여 통합 한도, 전월 실적 미달 시 0원 처리, 혜택 제외 업종 등을 정밀하게 시뮬레이션합니다.
""")
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

    ranked = recommend_service.rank_top(calc_results, top_n=payload.top_n)

    if not ranked:
        raise NoCardsFoundError("혜택 계산 결과가 없습니다.")

    # 3. LLM 설명 생성 — 실패해도 카드 목록은 반환 (Graceful Degradation)
    digests = []
    import asyncio
    try:
        # 모든 카드의 Digest를 시도하여 상세 내역 생성에 대비
        coros = [digest_repo.get_digest(card.get("_card_data", {})) for card in ranked]
        digests = await asyncio.gather(*coros)
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
            import traceback
            err_msg = traceback.format_exc()
            logger.warning("[LLM Fallback] explain() 실패, Fallback 텍스트 사용: %s", err_msg)
            explanation = f"ERROR IN EXPLAIN: {err_msg}"

    try:
        # 상세 Tracing 기능이 포함된 빌더 호출
        recommended_cards = explain_service.build_recommended_cards(ranked, explanation, digests)
    except Exception as e:
        logger.warning("[recommend_cards] 상세 빌더 실패, 안전 빌더 사용: %s", repr(e))
        recommended_cards = _safe_build_recommended_cards(ranked, explanation)


    return RecommendResponse(recommended_cards=recommended_cards, explanation=explanation)


@router.post("/qa", response_model=QAResponse, summary="카드 혜택 정밀 Q&A", description="""
추천된 카드들의 계산 근거(Trace)를 기반으로 LLM이 사용자의 질문에 답변합니다.
'왜 이 카드가 1순위인가요?', '이 카드는 어디서 할인이 안 되나요?' 등의 질문이 가능합니다.
""")
async def answer_qa(payload: QARequest) -> QAResponse:
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


@router.post("/recalculate", response_model=RecalculateResponse, summary="체크박스 토글 기반 재계산", description="""
유저가 영수증 항목에서 특정 혜택을 제외(체크 해제)했을 때의 결과를 반영합니다. 
(Shallow Recalculation: 한도 재분배 없음)

유저가 '이 돈을 쓰지 않겠다'고 결정한 상황을 가정하여, 해당 항목의 할인 금액을 단순히 제외합니다. 
다른 혜택이 남은 한도를 재사용하지 않으므로 사용자의 실제 소비 규모 축소 의지를 정확히 반영합니다.
""")
async def recalculate_benefits(payload: RecalculateRequest) -> RecalculateResponse:
    """
    유저 체크박스 상태를 반영하여 expected_monthly_benefit만 합산 변경합니다.
    """
    excluded = set(payload.excluded_benefit_ids)
    updated_cards = []

    for card in payload.recommended_cards:
        new_total = 0
        updated_trace = []
        for t in card.applied_benefits_trace:
            is_active = t.benefit_id not in excluded
            # 상태값만 업데이트하고 금액은 기존 계산값 유지 (재분배 없음)
            updated_trace.append(t.model_copy(update={"user_choice": is_active}))
            if is_active:
                new_total += t.yielded_discount

        # trace의 category 필드로 카테고리별 합산 후 breakdown 갱신
        cat_totals: dict[str, int] = {}
        for t in updated_trace:
            if t.user_choice:
                cat_totals[t.category] = cat_totals.get(t.category, 0) + t.yielded_discount

        new_breakdown = [
            cb.model_copy(update={"monthly_discount_krw": cat_totals.get(cb.category, 0)})
            for cb in card.category_breakdown
        ]

        updated_card = card.model_copy(update={
            "applied_benefits_trace": updated_trace,
            "expected_monthly_benefit": new_total,
            # Recalculate is "shallow": annual total tracks updated monthly total.
            "expected_yearly_benefit": new_total * 12,
            "category_breakdown": new_breakdown,
        })
        updated_cards.append(updated_card)

    # 순위 재조정 (할인액이 줄어들어 순위가 바뀔 수 있음)
    updated_cards.sort(key=lambda c: c.expected_monthly_benefit, reverse=True)

    return RecalculateResponse(recommended_cards=updated_cards)
