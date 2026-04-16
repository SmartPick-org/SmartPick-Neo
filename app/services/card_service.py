import asyncio
import json
from typing import Dict, List, Any
from pathlib import Path

from app.core.config import LEGACY_DATASETS_DIR
from app.domain.models import CardData
from app.repositories.card_repo import CardRepository
from app.tools.Calc_tool import BenefitCalculator
from loguru import logger


def _enrich_benefit_details(benefit_details: list[dict], raw_benefits: list[dict], legacy_benefits: list[dict] | None = None) -> list[dict]:
    """
    Calc_tool이 반환한 benefit_details에 카드 JSON의 content 필드를 보강합니다.
    1순위: json_v4의 content가 있을 경우 사용
    2순위: legacy(구버전) JSON에서 category/sub_category 매칭되는 content 사용
    3순위: 위 둘 다 없으면 조합형 fallback 로직 사용
    """
    def _create_fallback_content(b: dict) -> str:
        cat = b.get("category", "")
        sub = b.get("sub_category", "")
        rule = b.get("calculation_rule") or {}
        rate = rule.get("benefit_rate") or rule.get("rate")
        
        info = f"[{cat}]"
        if sub and sub != "general":
            info += f" {sub}"
            
        if rate:
            # 0.1 -> 10%
            info += f" {int(rate * 100)}% 혜택"
        elif rule.get("flat_discount"):
            info += f" {rule.get('flat_discount'):,}원 할인"
        elif rule.get("fixed_amount"):
            info += f" {rule.get('fixed_amount'):,}원 할인"
        else:
            info += " 맞춤 혜택"
            
        return info

    # 레거시 매핑 테이블 생성 (category, sub_category) -> content
    legacy_map = {}
    if legacy_benefits:
        for lb in legacy_benefits:
            cat = lb.get("category")
            sub = lb.get("sub_category")
            # sub_category가 없는 경우 "general"로 취급하거나 None 그대로 둠
            if cat:
                legacy_map[(cat, sub)] = lb.get("content")

    content_map = {}
    for b in raw_benefits:
        bid = b.get("benefit_id")
        if not bid:
            continue
            
        content = b.get("content")
        # 1. v4 본체에 content가 없으면 레거시에서 매칭 시도
        if not content and legacy_benefits:
            cat = b.get("category")
            sub = b.get("sub_category")
            content = legacy_map.get((cat, sub))
            
        # 2. 여전히 없으면 조합형 fallback
        if not content:
            content = _create_fallback_content(b)
            
        content_map[bid] = content

    valid = [bd for bd in benefit_details if bd.get("benefit_id") is not None]
    return [
        {**bd, "content": content_map.get(bd.get("benefit_id", ""), "맞춤 혜택")}
        for bd in valid
    ]

# 동시에 실행할 카드 혜택 계산의 최대 개수.
# 이 제한이 없으면 asyncio.gather가 N개의 카드를 한 번에 실행해
# 이벤트 루프나 DB/외부 API 등 하위 리소스에 과부하를 줄 수 있음.
_CONCURRENCY_LIMIT = 10


class CardRecommendService:
    def __init__(self, card_repo: CardRepository):
        self.card_repo = card_repo

    def filter_cards(self, total_budget: int, category_spending: Dict[str, Any]) -> List[CardData]:
        user_categories = {cat.value if hasattr(cat, 'value') else str(cat) for cat in category_spending.keys()}
        all_cards = self.card_repo.list_cards()
        logger.info(f"[CardRecommendService] 전체 카드 수량: {len(all_cards)}")

        after_performance = [
            card for card in all_cards
            if card.get("card_meta", {}).get("minimum_performance", 0) <= total_budget
        ]
        logger.info(f"[CardRecommendService] 전월 실적 충족(<= {total_budget}): {len(after_performance)}")

        filtered = []
        for card in after_performance:
            categories = card.get("_card_categories", set())
            if categories & user_categories or "General" in categories:
                filtered.append(card)
        logger.info(f"[CardRecommendService] 필터링 된 1차 결과(최종): {len(filtered)}장")
        return filtered

    async def calculate_benefits(
        self,
        cards: List[CardData],
        total_budget: int,
        category_spending: Dict[str, Any],
        excluded_benefit_ids: list[str] | None = None,
    ) -> List[dict]:
        user_categories = {cat.value if hasattr(cat, 'value') else str(cat) for cat in category_spending.keys()}
        spending_str_keys = {cat.value if hasattr(cat, 'value') else str(cat): val for cat, val in category_spending.items()}

        # 세마포어로 동시에 실행되는 카드 계산 수를 제한함.
        # 없으면 gather가 N개의 코루틴을 한꺼번에 실행해 스레드 풀이나
        # 하위 I/O 리소스에 과부하가 발생할 수 있음.
        semaphore = asyncio.Semaphore(_CONCURRENCY_LIMIT)

        async def _calculate_single(card: CardData) -> dict:
            async with semaphore:
                # BenefitCalculator.calculate는 CPU 연산 위주의 동기 코드임.
                # asyncio.to_thread로 워커 스레드에 위임해 실행하는 동안
                # 이벤트 루프가 다른 코루틴을 처리할 수 있도록 함.
                # to_thread 없이 동기 함수를 직접 호출하면 이벤트 루프 전체가
                # 블로킹되어 동시성 효과가 사라짐.
                def _compute():
                    card_meta = card.get("card_meta", {})
                    card_name = card_meta.get("card_name", "?")
                    calculator = BenefitCalculator(card)
                    _excluded_set = set(excluded_benefit_ids) if excluded_benefit_ids else None
                    result = calculator.calculate(
                        spending_str_keys,
                        user_total_spend=total_budget,
                        excluded_benefit_ids=_excluded_set,
                    )

                    monthly = result.get("monthly_total_krw", 0)
                    annual_extra = result.get("annual_total_krw", 0)
                    yearly = monthly * 12 + annual_extra

                    card_categories = card.get("_card_categories", set())
                    specific_cats = card_categories - {"General"}
                    overlapping = user_categories & specific_cats
                    fit_score = len(overlapping) / len(user_categories) if user_categories else 0.0
                    covered_spend = sum(
                        (spending_str_keys[cat].get('total', 0) if isinstance(spending_str_keys[cat], dict) else spending_str_keys[cat])
                        for cat in overlapping if cat in spending_str_keys
                    )
                    coverage_score = covered_spend / total_budget if total_budget > 0 else 0.0
                    min_perf = card_meta.get("minimum_performance", 0)
                    min_spend_score = min_perf / total_budget if total_budget > 0 else 1.0

                    # 레거시 데이터 로드 (content 추출용)
                    legacy_benefits = []
                    legacy_path = LEGACY_DATASETS_DIR / f"{card_meta.get('card_id')}.json"
                    if legacy_path.exists():
                        try:
                            with open(legacy_path, "r", encoding="utf-8") as f:
                                legacy_data = json.load(f)
                                legacy_benefits = legacy_data.get("benefits", [])
                        except Exception as e:
                            logger.error(f"Failed to load legacy data from {legacy_path}: {e}")

                    return {
                        "card_name": card_name,
                        "card_company": card_meta.get("card_company", ""),
                        "card_id": card_meta.get("card_id", ""),
                        "annual_fee": card_meta.get("annual_fee", 0),
                        "minimum_performance": min_perf,
                        "performance_met": result.get("performance_met", False),
                        "expected_monthly_benefit": monthly,
                        "expected_yearly_benefit": yearly,
                        "scores": {
                            "fit_score": round(fit_score, 3),
                            "coverage_score": round(coverage_score, 3),
                            "min_spend_score": round(min_spend_score, 3),
                        },
                        "category_breakdown": result.get("category_breakdown", []),
                        "applied_benefits_trace": _enrich_benefit_details(
                            result.get("applied_benefits_trace", []),
                            card.get("benefits", []),
                            legacy_benefits
                        ),
                        "benefit_details": _enrich_benefit_details(
                            result.get("benefit_details", []),
                            card.get("benefits", []),
                            legacy_benefits
                        ),
                        "annual_breakdown": result.get("annual_breakdown", []),
                        "warnings": result.get("warnings", []),
                        "_card_data": card,
                    }
                return await asyncio.to_thread(_compute)

        # asyncio.gather로 모든 카드를 동시에 처리 (순차 O(N) → 동시 O(N / _CONCURRENCY_LIMIT))
        results: List[dict] = list(
            await asyncio.gather(*[_calculate_single(card) for card in cards])
        )

        results.sort(key=lambda item: item["expected_monthly_benefit"], reverse=True)
        success_count = sum(1 for r in results if r["expected_monthly_benefit"] > 0)
        logger.info(f"[CardRecommendService] 계산에 성공(혜택>0)한 카드 수량: {success_count}장")
        return results

    def rank_top(self, calc_results: List[dict], top_n: int = 3) -> List[dict]:
        ranked = sorted(calc_results, key=lambda item: item["expected_monthly_benefit"], reverse=True)[:top_n]
        logger.info(f"[CardRecommendService] Top-{top_n} 선정된 카드명: {[c['card_name'] for c in ranked]}")
        return ranked
