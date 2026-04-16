import asyncio
import json
from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_llm
from app.core.dependencies import (
    get_digest_repository,
    get_explain_service,
    get_recommend_service,
)
from app.core.exceptions import (
    InternalCalculationError,
    LLMUnavailableError,
    NoCardsFoundError,
)
from app.repositories.card_repo import FallbackCardRepository
from app.repositories.digest_repo import DigestRepository
from app.schemas.card_catalog import (
    CardCatalogItem,
    CardCatalogResponse,
    CardDetailResponse,
)
from app.schemas.recommend import (
    CategoryComparison,
    CompareRequest,
    CompareResponse,
    QARequest,
    QAResponse,
    RecommendCard,
    RecommendRequest,
    RecommendResponse,
    RecalculateRequest, 
    RecalculateResponse,
)
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService

router = APIRouter(prefix="/cards", tags=["cards"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json_v4"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"

# Fallback 텍스트 — LLM이 죽어도 사용자는 카드 목록을 볼 수 있음
_LLM_FALLBACK_EXPLAIN = (
    "AI 설명 생성에 실패했습니다. 아래 카드 목록은 혜택 계산 결과 기준으로 정렬되었습니다."
)

_LLM_FALLBACK_COMPARE = (
    "AI 비교 설명 생성에 실패했습니다. 혜택 계산 결과를 직접 확인해 주세요."
)

def _get_card_repository():
    return FallbackCardRepository(DATASETS_DIR)


def _to_catalog_item(card: dict) -> CardCatalogItem:
    meta = card.get("card_meta", {}) or {}
    categories = card.get("_card_categories", set()) or set()
    categories_list = sorted([str(c) for c in categories if c])
    return CardCatalogItem(
        card_id=str(meta.get("card_id", "") or ""),
        card_name=str(meta.get("card_name", "") or ""),
        card_company=str(meta.get("card_company", "") or ""),
        annual_fee=int(meta.get("annual_fee", 0) or 0),
        minimum_performance=int(meta.get("minimum_performance", 0) or 0),
        categories=categories_list,
    )


@router.get("", response_model=CardCatalogResponse)
def list_cards(
    q: str | None = Query(default=None, description="카드명/카드사 검색어"),
    company: str | None = Query(default=None, description="카드사 필터"),
    category: list[str] | None = Query(default=None, description="카테고리 필터(다중)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CardCatalogResponse:
    """
    프론트의 '기존 카드 선택' 드롭다운/검색 UI를 실데이터로 채우기 위한 카탈로그 API.
    - GET /cards (router prefix=/cards + path="") 형태로 노출됩니다.
    """
    repo = _get_card_repository()
    all_cards = repo.list_cards()

    q_norm = (q or "").strip().lower()
    company_norm = (company or "").strip().lower()
    categories_norm = {c.strip().lower() for c in (category or []) if c and c.strip()}

    items: list[CardCatalogItem] = []
    for card in all_cards:
        item = _to_catalog_item(card)
        if not item.card_id or not item.card_name:
            continue

        if q_norm:
            hay = f"{item.card_name} {item.card_company}".lower()
            if q_norm not in hay:
                continue
        if company_norm and company_norm not in item.card_company.lower():
            continue
        if categories_norm:
            item_categories = {c.lower() for c in item.categories}
            if not (item_categories & categories_norm):
                continue

        items.append(item)

    total = len(items)
    paged = items[offset : offset + limit]
    return CardCatalogResponse(cards=paged, total=total, offset=offset, limit=limit)


@router.get("/{card_id}", response_model=CardDetailResponse)
def get_card_detail(card_id: str) -> CardDetailResponse:
    repo = _get_card_repository()
    for card in repo.list_cards():
        meta = card.get("card_meta", {}) or {}
        if str(meta.get("card_id", "") or "") == str(card_id):
            item = _to_catalog_item(card)
            return CardDetailResponse(
                card_id=item.card_id,
                card_name=item.card_name,
                card_company=item.card_company,
                annual_fee=item.annual_fee,
                minimum_performance=item.minimum_performance,
                categories=item.categories,
                card_meta=meta,
                benefits=card.get("benefits", []) or [],
                benefit_groups=card.get("benefit_groups", []) or [],
                file_path=card.get("_file_path"),
            )
    raise HTTPException(status_code=404, detail="카드를 찾을 수 없습니다.")


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
                "applied_benefits_trace": card.get("applied_benefits_trace", []) or [],
                "explanation": explanation if idx == 0 else "",
                "benefit_receipt": card.get("benefit_details", []),
            }
        )
    return cards


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_cards(
    payload: RecommendRequest,
    recommend_service: CardRecommendService = Depends(get_recommend_service),
    digest_repo: DigestRepository = Depends(get_digest_repository),
    explain_service: ExplainService = Depends(get_explain_service),
) -> RecommendResponse:
    """
    calculate_benefits가 코루틴(async)으로 변경되었으므로 엔드포인트도 async로 선언해야 함.
    FastAPI는 async 라우트 핸들러를 기본적으로 지원하며 이벤트 루프에서 실행됨.
    """
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

    card_repo = _get_card_repository()
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
            filtered, payload.total_budget, payload.category_spending,
            excluded_benefit_ids=payload.excluded_benefit_ids,
        )
    except KeyError as e:
        # 계산기 내부에서 필수 키 누락 = 데이터/로직 버그 → 500 + Discord 알림
        logger.exception("[recommend_cards] calculate_benefits KeyError: %s", repr(e))
        raise InternalCalculationError(
            "혜택 계산에 필요한 데이터가 누락되었습니다."
        ) from e
    except ValueError as e:
        # 계산기에서 올라오는 ValueError는 대체로 데이터 이상이므로 함께 500 처리
        logger.exception("[recommend_cards] calculate_benefits ValueError: %s", repr(e))
        raise InternalCalculationError(str(e)) from e

    ranked = recommend_service.rank_top(calc_results, top_n=payload.top_n)

    if not ranked:
        raise NoCardsFoundError("혜택 계산 결과가 없습니다.")

    # 3. LLM 설명 생성 — 실패해도 카드 목록은 반환 (Graceful Degradation)
    # 랭킹 완료 후 1위 카드의 digest만 가져옴
    top_digest = ""
    try:
        top_digest = await digest_repo.get_digest(ranked[0].get("_card_data", {}))
    except Exception as e:
        logger.warning("[recommend_cards] digest 로드 실패: %s", repr(e))

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
        recommended_cards = explain_service.build_recommended_cards(ranked, explanation)
    except Exception as e:
        logger.warning("[recommend_cards] 상세 빌더 실패, 안전 빌더 사용: %s", repr(e))
        recommended_cards = _safe_build_recommended_cards(ranked, explanation)

    return RecommendResponse(recommended_cards=recommended_cards, explanation=explanation)


@router.post("/qa", response_model=QAResponse)
async def answer_qa(
    payload: QARequest,
    explain_service: ExplainService = Depends(get_explain_service),
) -> QAResponse:
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


def _build_recommend_card(card_result: dict, explanation: str) -> RecommendCard:
    """calc result dict → RecommendCard 스키마 변환 헬퍼"""
    return RecommendCard(
        card_name=card_result.get("card_name", ""),
        card_company=card_result.get("card_company", ""),
        card_id=card_result.get("card_id", ""),
        annual_fee=card_result.get("annual_fee", 0),
        minimum_performance=card_result.get("minimum_performance", 0),
        expected_monthly_benefit=card_result.get("expected_monthly_benefit", 0),
        category_breakdown=card_result.get("category_breakdown", []),
        applied_benefits_trace=card_result.get("applied_benefits_trace", []),
        benefit_receipt=card_result.get("benefit_details", []),
        explanation=explanation,
    )


@router.post("/recalculate", response_model=RecalculateResponse)
async def recalculate_benefits(payload: RecalculateRequest) -> RecalculateResponse:
    """
    유저 체크박스 상태를 반영하여 expected_monthly_benefit만 재계산합니다.
    BenefitCalculator 재호출 없이 기존 trace 데이터의 합산만 변경합니다. (< 50ms)

    - **recommended_cards**: 기존 추천 결과 (applied_benefits_trace 포함)
    - **excluded_benefit_ids**: 유저가 체크 해제한 benefit_id 목록
    """
    excluded = set(payload.excluded_benefit_ids)
    updated_cards = []

    for card in payload.recommended_cards:
        new_total = 0
        updated_trace = []
        for t in card.applied_benefits_trace:
            is_active = t.benefit_id not in excluded
            updated_trace.append(t.model_copy(update={"user_choice": is_active}))
            if is_active:
                new_total += t.yielded_discount

        updated_card = card.model_copy(update={
            "applied_benefits_trace": updated_trace,
            "expected_monthly_benefit": new_total,
        })
        updated_cards.append(updated_card)

    updated_cards.sort(key=lambda c: c.expected_monthly_benefit, reverse=True)
    logger.info(
        f"[recalculate] excluded={len(excluded)}개 혜택 제외 | "
        f"카드 순위 재조정 완료: {[c.card_name for c in updated_cards]}"
    )
    return RecalculateResponse(recommended_cards=updated_cards)


@router.post("/compare", response_model=CompareResponse)
async def compare_cards(payload: CompareRequest) -> CompareResponse:
    """
    기존 카드 vs 1순위 추천 카드 혜택 비교.

    - **current_card_id**: 유저가 현재 사용 중인 카드 ID (GET /cards 에서 확인 가능)
    - **total_budget / category_spending**: recommend와 동일한 소비 패턴 입력
    """
    from fastapi import HTTPException
    card_repo = _get_card_repository()

    current_card_raw: dict | None = None
    for card in card_repo.list_cards():
        meta = card.get("card_meta", {}) or {}
        if str(meta.get("card_id", "") or "") == payload.current_card_id:
            current_card_raw = card
            break

    if current_card_raw is None:
        raise HTTPException(status_code=404, detail=f"카드 ID '{payload.current_card_id}'를 찾을 수 없습니다.")

    recommend_service = CardRecommendService(card_repo)

    explain_service: ExplainService | None = None
    try:
        explain_service = ExplainService(get_llm())
    except Exception as e:
        logger.exception("[compare_cards] ExplainService 생성 실패: %s", repr(e))
        explain_service = None

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
        logger.exception("[compare_cards] calculate_benefits KeyError: %s", repr(e))
        raise InternalCalculationError(
            "혜택 계산에 필요한 데이터가 누락되었습니다."
        ) from e
    except ValueError as e:
        logger.exception("[compare_cards] calculate_benefits ValueError: %s", repr(e))
        raise InternalCalculationError(str(e)) from e

    ranked = recommend_service.rank_top(calc_results, top_n=len(calc_results))
    if not ranked:
        raise NoCardsFoundError("혜택 계산 결과가 없습니다.")

    recommended_result = ranked[0]

    try:
        current_calc = await recommend_service.calculate_benefits(
            [current_card_raw], payload.total_budget, payload.category_spending
        )
        current_result = current_calc[0] if current_calc else {}
        if current_result and current_result.get("expected_monthly_benefit", 0) == 0:
            if not current_result.get("warnings"):
                current_result["warnings"] = ["전월 실적 미달 등의 사유로 혜택이 0원으로 산출되었습니다."]
    except Exception as e:
        logger.warning("[compare_cards] 기존 카드 혜택 계산 실패: %s", repr(e))
        meta = (current_card_raw.get("card_meta", {}) or {})
        current_result = {
            "card_name": meta.get("card_name", ""),
            "card_company": meta.get("card_company", ""),
            "card_id": payload.current_card_id,
            "annual_fee": meta.get("annual_fee", 0),
            "minimum_performance": meta.get("minimum_performance", 0),
            "expected_monthly_benefit": 0,
            "category_breakdown": [],
        }

    current_monthly = current_result.get("expected_monthly_benefit", 0)
    recommended_monthly = recommended_result.get("expected_monthly_benefit", 0)
    monthly_diff = recommended_monthly - current_monthly
    yearly_diff = monthly_diff * 12

    current_breakdown_map: dict[str, int] = {
        cb["category"]: cb["monthly_discount_krw"]
        for cb in current_result.get("category_breakdown", [])
    }
    recommended_breakdown_map: dict[str, int] = {
        cb["category"]: cb["monthly_discount_krw"]
        for cb in recommended_result.get("category_breakdown", [])
    }

    all_categories = set(current_breakdown_map.keys()) | set(recommended_breakdown_map.keys())
    user_cat_strs = [
        cat.value if hasattr(cat, "value") else str(cat)
        for cat in payload.category_spending.keys()
    ]
    ordered_cats = [c for c in user_cat_strs if c in all_categories] + \
                   [c for c in all_categories if c not in user_cat_strs]

    category_comparison = [
        CategoryComparison(
            category=cat,
            current_benefit=current_breakdown_map.get(cat, 0),
            recommended_benefit=recommended_breakdown_map.get(cat, 0),
            diff=recommended_breakdown_map.get(cat, 0) - current_breakdown_map.get(cat, 0),
        )
        for cat in ordered_cats
    ]

    current_explain = ""
    if current_result.get("expected_monthly_benefit", 0) == 0:
        warnings = current_result.get("warnings", [])
        if warnings:
            current_explain = "⚠️ " + " / ".join(warnings)

    recommended_cards_schema = []
    if explain_service is not None:
        try:
            if not current_explain:
                current_explain = explain_service._format_card_detail(current_result, rank=0)
            for i, r_result in enumerate(ranked):
                r_exp = explain_service._format_card_detail(r_result, rank=i + 1)
                recommended_cards_schema.append(_build_recommend_card(r_result, r_exp))
        except Exception as e:
            logger.warning("[compare_cards] _format_card_detail 실패: %s", repr(e))

    if not recommended_cards_schema:
        recommended_cards_schema = [_build_recommend_card(r, "") for r in ranked]

    recommended_card_schema = recommended_cards_schema[0]

    explanation = _LLM_FALLBACK_COMPARE
    if explain_service is not None:
        try:
            explanation = await explain_service.compare(
                payload.total_budget,
                payload.category_spending,
                current_result,
                recommended_result,
            )
            if not explanation or not explanation.strip():
                explanation = _LLM_FALLBACK_COMPARE
        except Exception as e:
            logger.warning("[compare_cards] compare() 실패, Fallback 텍스트 사용: %s", repr(e))
            explanation = _LLM_FALLBACK_COMPARE

    current_card_schema = _build_recommend_card(current_result, current_explain)

    filtered_recommended_cards = [
        card for card in recommended_cards_schema
        if card.expected_monthly_benefit > 0
        and card.expected_monthly_benefit > current_monthly
    ]

    return CompareResponse(
        current_card=current_card_schema,
        recommended_cards=filtered_recommended_cards,
        recommended_card=recommended_card_schema,
        monthly_diff=monthly_diff,
        yearly_diff=yearly_diff,
        category_comparison=category_comparison,
        explanation=explanation,
    )
