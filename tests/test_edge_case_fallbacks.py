import json
import pytest
from fastapi.testclient import TestClient

import app.api.card as card_api
from app.core.config import get_llm
from app.main import app as fastapi_app
from app.core import dependencies

client = TestClient(fastapi_app)


def _ranked_cards_for_tests() -> list[dict]:
    return [
        {
            "card_name": "Card1",
            "card_company": "C1",
            "card_id": "id1",
            "annual_fee": 100,
            "minimum_performance": 200,
            "expected_monthly_benefit": 1000,
            "category_breakdown": [
                {"category": "Coffee", "monthly_discount_krw": 1000, "warnings": []}
            ],
            "_card_data": {"card_meta": {"card_id": "id1", "card_company": "KB", "card_name": "Card1"}},
        }
    ]


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    fastapi_app.dependency_overrides = {}
    yield
    fastapi_app.dependency_overrides = {}


def test_recommend_input_value_error_total_budget() -> None:
    res = client.post(
        "/api/v1/cards/recommend",
        json={"total_budget": 0, "category_spending": {"Coffee": 1000}},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["error_code"] == "INVALID_INPUT"
    assert body["fallback"] is False
    assert body["message"] == "요청 데이터가 올바르지 않습니다."


def test_recommend_llm_failure_fallback_success_200(monkeypatch: pytest.MonkeyPatch) -> None:
    ranked_cards = _ranked_cards_for_tests()

    class StubCardRecommendService:
        def __init__(self, repo):
            pass

        def filter_cards(self, total_budget: int, category_spending: dict) -> list[dict]:
            return [{"_dummy": True}]

        async def calculate_benefits(self, cards, total_budget: int, category_spending: dict) -> list[dict]:
            return [{"_calc_dummy": True}]

        def rank_top(self, calc_results: list[dict], top_n: int = 3) -> list[dict]:
            return ranked_cards[:top_n]

    class StubExplainService:
        def __init__(self, llm):
            pass

        async def explain(self, total_budget: int, category_spending: dict, ranked: list[dict], card_digest: str) -> str:
            raise RuntimeError("LLM invoke failed")

        @staticmethod
        def build_recommended_cards(ranked: list[dict], explanation: str, digests: list[str]) -> list[dict]:
            cards = []
            for idx, card in enumerate(ranked or []):
                cards.append(
                    {
                        "card_name": card["card_name"],
                        "card_company": card["card_company"],
                        "card_id": card["card_id"],
                        "annual_fee": card["annual_fee"],
                        "minimum_performance": card["minimum_performance"],
                        "expected_monthly_benefit": card["expected_monthly_benefit"],
                        "category_breakdown": card["category_breakdown"],
                        "explanation": explanation if idx == 0 else "",
                    }
                )
            return cards

    from unittest.mock import AsyncMock
    monkeypatch.setattr(card_api, "CardRecommendService", StubCardRecommendService)
    monkeypatch.setattr(card_api, "ExplainService", StubExplainService)
    monkeypatch.setattr(card_api.DigestRepository, "get_digest", AsyncMock(return_value="digest"))
    monkeypatch.setattr(card_api, "get_llm", lambda *args, **kwargs: object())

    res = client.post(
        "/api/v1/cards/recommend",
        json={"total_budget": 100000, "category_spending": {"Coffee": 100000}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["explanation"] == card_api._LLM_FALLBACK_EXPLAIN
    assert body["recommended_cards"][0]["explanation"] == card_api._LLM_FALLBACK_EXPLAIN


def test_recommend_build_recommended_cards_keyerror_fallback_safe_builder_success_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranked_cards = _ranked_cards_for_tests()

    class StubCardRecommendService:
        def __init__(self, repo):
            pass

        def filter_cards(self, total_budget: int, category_spending: dict) -> list[dict]:
            return [{"_dummy": True}]

        async def calculate_benefits(self, cards, total_budget: int, category_spending: dict) -> list[dict]:
            return [{"_calc_dummy": True}]

        def rank_top(self, calc_results: list[dict], top_n: int = 3) -> list[dict]:
            return ranked_cards[:top_n]

    class StubExplainService:
        def __init__(self, llm):
            pass

        async def explain(self, total_budget: int, category_spending: dict, ranked: list[dict], card_digest: str) -> str:
            # 설명은 정상적으로 만들었지만, build 단계에서 KeyError가 발생한다고 가정합니다.
            return "OK_EXPLANATION"

        @staticmethod
        def build_recommended_cards(ranked: list[dict], explanation: str, digests: list[str]) -> list[dict]:
            raise KeyError("card_name")

    from unittest.mock import AsyncMock
    monkeypatch.setattr(card_api, "CardRecommendService", StubCardRecommendService)
    monkeypatch.setattr(card_api, "ExplainService", StubExplainService)
    monkeypatch.setattr(card_api.DigestRepository, "get_digest", AsyncMock(return_value="digest"))
    monkeypatch.setattr(card_api, "get_llm", lambda *args, **kwargs: object())

    res = client.post(
        "/api/v1/cards/recommend",
        json={"total_budget": 100000, "category_spending": {"Coffee": 100000}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["explanation"] == "OK_EXPLANATION"
    assert len(body["recommended_cards"]) >= 1


def test_qa_invalid_raw_data_value_error_400() -> None:
    res = client.post(
        "/api/v1/cards/qa",
        json={"raw_data": "{invalid_json", "question": "hello"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["error_code"] == "INVALID_INPUT"
    assert body["fallback"] is False


def test_qa_llm_failure_returns_fallback_error_format_422(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubExplainService:
        async def answer_qa(self, raw_data: str, question: str) -> str:
            raise RuntimeError("llm down")

    fastapi_app.dependency_overrides[dependencies.get_explain_service] = lambda: StubExplainService()

    res = client.post(
        "/api/v1/cards/qa",
        json={"raw_data": json.dumps({"a": 1}), "question": "hello"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["error_code"] == "LLM_UNAVAILABLE"
    assert body["fallback"] is True
    assert "message" in body
