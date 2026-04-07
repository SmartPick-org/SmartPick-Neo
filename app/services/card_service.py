from typing import Dict, List, Any

from app.domain.models import CardData
from app.repositories.card_repo import CardRepository
from app.tools.Calc_tool import BenefitCalculator
from loguru import logger


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
            if categories & user_categories or "General" in categories or "All_Domestic" in categories:
                filtered.append(card)
        logger.info(f"[CardRecommendService] 필터링 된 1차 결과(최종): {len(filtered)}장")
        return filtered

    def calculate_benefits(
        self,
        cards: List[CardData],
        total_budget: int,
        category_spending: Dict[str, Any],
    ) -> List[dict]:
        user_categories = {cat.value if hasattr(cat, 'value') else str(cat) for cat in category_spending.keys()}
        spending_str_keys = {cat.value if hasattr(cat, 'value') else str(cat): val for cat, val in category_spending.items()}
        
        results: List[dict] = []
        success_count = 0

        for card in cards:
            card_meta = card.get("card_meta", {})
            card_name = card_meta.get("card_name", "?")
            calculator = BenefitCalculator(card)
            result = calculator.calculate(spending_str_keys, user_total_spend=total_budget)

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

            if monthly > 0:
                success_count += 1

            results.append({
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
                "benefit_details": result.get("benefit_details", []),
                "annual_breakdown": result.get("annual_breakdown", []),
                "warnings": result.get("warnings", []),
                "_card_data": card,
            })

        results.sort(key=lambda item: item["expected_monthly_benefit"], reverse=True)
        logger.info(f"[CardRecommendService] 계산에 성공(혜택>0)한 카드 수량: {success_count}장")
        return results

    def rank_top(self, calc_results: List[dict], top_n: int = 3) -> List[dict]:
        ranked = sorted(calc_results, key=lambda item: item["expected_monthly_benefit"], reverse=True)[:top_n]
        logger.info(f"[CardRecommendService] Top-{top_n} 선정된 카드명: {[c['card_name'] for c in ranked]}")
        return ranked
