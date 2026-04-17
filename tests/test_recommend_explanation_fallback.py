"""POST /api/v1/cards/recommend — LLM 실패 시 응답 보호.

회귀 방지 대상: ExplainService.explain() 이 예외를 던져도
응답 `explanation` 필드에 파이썬 traceback이 실려 나가면 안 된다.
반드시 고정 한글 fallback 문자열(_LLM_FALLBACK_EXPLAIN)로 내려가야 한다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.api.card as card_api
from app.main import app as fastapi_app


client = TestClient(fastapi_app)


def _ranked_card() -> dict:
    return {
        "card_name": "Card1",
        "card_company": "C1",
        "card_id": "id1",
        "annual_fee": 100,
        "minimum_performance": 200,
        "expected_monthly_benefit": 1000,
        "expected_yearly_benefit": 12000,
        "category_breakdown": [
            {"category": "Coffee", "monthly_discount_krw": 1000, "discount_info": {}, "warnings": []}
        ],
        "applied_benefits_trace": [],
        "_card_data": {"card_meta": {"card_id": "id1", "card_company": "C1", "card_name": "Card1"}},
    }


def _install_stubs(monkeypatch: pytest.MonkeyPatch, *, explain_raises: bool) -> None:
    """핸들러가 직접 생성하는 의존성들을 모두 스텁으로 치환."""

    ranked = [_ranked_card()]

    class StubCardRepo:
        def __init__(self, *args, **kwargs):
            pass

    class StubDigestRepo:
        def __init__(self, *args, **kwargs):
            pass

        async def get_digest(self, *args, **kwargs):
            return "digest"

    class StubRecommendService:
        def __init__(self, *args, **kwargs):
            pass

        def filter_cards(self, total_budget, category_spending):
            return [{"_dummy": True}]

        async def calculate_benefits(self, cards, total_budget, category_spending, excluded_benefit_ids=None):
            return ranked

        def rank_top(self, calc_results, top_n=3):
            return ranked[:top_n]

    class StubExplainService:
        def __init__(self, *args, **kwargs):
            pass

        async def explain(self, total_budget, category_spending, ranked_cards, card_digest):
            if explain_raises:
                raise RuntimeError("LLM invoke failed: sensitive/internal/path.py")
            return "HAPPY_PATH_EXPLANATION"

        def build_recommended_cards(self, ranked_cards, explanation, digests=None):
            results = []
            for idx, card in enumerate(ranked_cards):
                results.append(
                    {
                        "card_name": card["card_name"],
                        "card_company": card["card_company"],
                        "card_id": card["card_id"],
                        "annual_fee": card["annual_fee"],
                        "minimum_performance": card["minimum_performance"],
                        "expected_monthly_benefit": card["expected_monthly_benefit"],
                        "expected_yearly_benefit": card.get("expected_yearly_benefit", 0),
                        "category_breakdown": card["category_breakdown"],
                        "applied_benefits_trace": card.get("applied_benefits_trace", []),
                        "explanation": explanation if idx == 0 else "",
                    }
                )
            return results

    monkeypatch.setattr(card_api, "DatasetCardRepository", StubCardRepo)
    monkeypatch.setattr(card_api, "DigestRepository", StubDigestRepo)
    monkeypatch.setattr(card_api, "CardRecommendService", StubRecommendService)
    monkeypatch.setattr(card_api, "ExplainService", StubExplainService)
    monkeypatch.setattr(card_api, "get_llm", lambda *a, **k: object())


def test_recommend_returns_fixed_fallback_when_explain_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 예외 시 응답 explanation은 traceback이 아니라 고정 fallback 문자열이어야 한다."""
    _install_stubs(monkeypatch, explain_raises=True)

    res = client.post(
        "/api/v1/cards/recommend",
        json={"total_budget": 100000, "category_spending": {"Coffee": 100000}},
    )
    assert res.status_code == 200
    body = res.json()

    # 고정 fallback 문자열
    assert body["explanation"] == card_api._LLM_FALLBACK_EXPLAIN

    # traceback/내부 경로 흔적이 응답에 노출되면 안 됨
    assert "ERROR IN EXPLAIN" not in body["explanation"]
    assert "Traceback" not in body["explanation"]
    assert ".py" not in body["explanation"]


def test_recommend_happy_path_uses_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 경로에서는 LLM 응답이 그대로 explanation 에 실려야 한다 (회귀 방지)."""
    _install_stubs(monkeypatch, explain_raises=False)

    res = client.post(
        "/api/v1/cards/recommend",
        json={"total_budget": 100000, "category_spending": {"Coffee": 100000}},
    )
    assert res.status_code == 200
    assert res.json()["explanation"] == "HAPPY_PATH_EXPLANATION"
