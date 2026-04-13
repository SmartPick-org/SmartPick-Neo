from typing import Dict, List

import pytest

from app.services.card_service import CardRecommendService


class FakeRepo:
    def __init__(self, cards: List[dict]):
        self._cards = cards

    def list_cards(self) -> List[dict]:
        return self._cards


class FakeBenefitCalculator:
    def __init__(self, card: dict):
        self.card = card

    def calculate(self, category_spending: Dict[str, int], user_total_spend: int) -> dict:
        name = self.card["card_meta"]["card_name"]
        if name == "CardA":
            return {
                "monthly_total_krw": 1000,
                "annual_total_krw": 500,
                "performance_met": True,
                "category_breakdown": [{"category": "Coffee", "monthly_discount_krw": 1000}],
                "benefit_details": [],
                "annual_breakdown": [],
                "warnings": [],
            }
        return {
            "monthly_total_krw": 3000,
            "annual_total_krw": 0,
            "performance_met": True,
            "category_breakdown": [{"category": "Shopping", "monthly_discount_krw": 3000}],
            "benefit_details": [],
            "annual_breakdown": [],
            "warnings": [],
        }


class FakeBenefitCalculatorSparse:
    def __init__(self, card: dict):
        self.card = card

    def calculate(self, category_spending: Dict[str, int], user_total_spend: int) -> dict:
        return {
            "monthly_total_krw": 1200,
        }


def test_filter_cards_by_performance_and_category():
    cards = [
        {
            "card_meta": {"card_name": "CardA", "minimum_performance": 200000},
            "_card_categories": {"Coffee"},
        },
        {
            "card_meta": {"card_name": "CardB", "minimum_performance": 600000},
            "_card_categories": {"Shopping"},
        },
        {
            "card_meta": {"card_name": "CardC", "minimum_performance": 0},
            "_card_categories": {"General"},
        },
    ]
    service = CardRecommendService(FakeRepo(cards))

    filtered = service.filter_cards(500000, {"Coffee": 50000})

    names = [card["card_meta"]["card_name"] for card in filtered]
    assert "CardA" in names
    assert "CardC" in names
    assert "CardB" not in names


@pytest.mark.asyncio
async def test_calculate_benefits_aggregates_and_sorts(monkeypatch):
    cards = [
        {
            "card_meta": {"card_name": "CardA", "card_company": "C1", "annual_fee": 1000, "card_id": "a"},
            "_card_categories": {"Coffee"},
        },
        {
            "card_meta": {"card_name": "CardB", "card_company": "C2", "annual_fee": 2000, "card_id": "b"},
            "_card_categories": {"Shopping"},
        },
    ]
    service = CardRecommendService(FakeRepo(cards))

    monkeypatch.setattr("app.services.card_service.BenefitCalculator", FakeBenefitCalculator)

    results = await service.calculate_benefits(cards, 500000, {"Coffee": 50000, "Shopping": 100000})

    assert results[0]["card_name"] == "CardB"
    assert results[0]["expected_monthly_benefit"] == 3000
    assert results[1]["expected_monthly_benefit"] == 1000
    assert results[0]["expected_yearly_benefit"] == 3000 * 12


def test_rank_top():
    service = CardRecommendService(FakeRepo([]))
    calc_results = [
        {"card_name": "A", "expected_monthly_benefit": 10},
        {"card_name": "B", "expected_monthly_benefit": 30},
        {"card_name": "C", "expected_monthly_benefit": 20},
    ]

    ranked = service.rank_top(calc_results, top_n=2)

    assert [r["card_name"] for r in ranked] == ["B", "C"]


def test_filter_cards_with_empty_spending_only_allows_general():
    cards = [
        {
            "card_meta": {"card_name": "OnlyCoffee", "minimum_performance": 0},
            "_card_categories": {"Coffee"},
        },
        {
            "card_meta": {"card_name": "GeneralCard", "minimum_performance": 0},
            "_card_categories": {"General"},
        },
    ]
    service = CardRecommendService(FakeRepo(cards))

    filtered = service.filter_cards(0, {})

    names = [card["card_meta"]["card_name"] for card in filtered]
    assert names == ["GeneralCard"]


@pytest.mark.asyncio
async def test_calculate_benefits_handles_zero_budget_and_sparse_result(monkeypatch):
    cards = [
        {
            "card_meta": {"card_name": "Sparse", "card_company": "C1", "annual_fee": 0, "card_id": "x"},
            "_card_categories": {"Coffee"},
        },
    ]
    service = CardRecommendService(FakeRepo(cards))
    monkeypatch.setattr("app.services.card_service.BenefitCalculator", FakeBenefitCalculatorSparse)

    results = await service.calculate_benefits(cards, 0, {})
    result = results[0]

    assert result["expected_monthly_benefit"] == 1200
    assert result["expected_yearly_benefit"] == 1200 * 12
    assert result["performance_met"] is False
    assert result["scores"]["fit_score"] == 0.0
    assert result["scores"]["coverage_score"] == 0.0
    assert result["scores"]["min_spend_score"] == 1.0
    assert result["category_breakdown"] == []
    assert result["benefit_details"] == []
    assert result["annual_breakdown"] == []
    assert result["warnings"] == []
