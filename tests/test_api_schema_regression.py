"""API 스키마 회귀 테스트.

목적: 현재 공개된 모든 API 엔드포인트의 응답이 약속된 Pydantic 스키마를
유지하는지 **외부 의존성 없이** 검증한다. 어떤 커밋이 실수로 필드를 지우거나
이름을 바꾸면 여기서 잡힌다.

커버 범위 (8개 엔드포인트):
  - GET  /
  - GET  /api/v1/cards
  - POST /api/v1/cards/compare
  - POST /api/v1/cards/recommend
  - POST /api/v1/cards/qa
  - POST /api/v1/cards/recalculate
  - POST /api/v1/advisor/ask
  - GET  /api/v1/advisor/queries

Mocking 전략:
  - 카드 API: 핸들러가 직접 인스턴스화하는 4개 클래스 (`DatasetCardRepository`,
    `DigestRepository`, `CardRecommendService`, `ExplainService`) 와 `get_llm`
    을 모듈 레벨에서 monkeypatch. 실제 데이터셋/LLM/Supabase 호출 전부 차단.
  - Advisor API: `app.api.advisor.get_advice` async 함수만 patch.

검증 방식:
  1. Pydantic 응답 모델로 `model_validate()` → 타입·필수 필드 누락 여부 자동 검사.
  2. 핵심 스키마 불변 (하위 호환성 유지 필드, 중첩 구조의 명시적 키) 은 추가 assert.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.api.advisor as advisor_api
import app.api.card as card_api
from app.main import app as fastapi_app
from app.schemas.cards import CardListResponse
from app.schemas.recommend import (
    CompareResponse,
    QAResponse,
    RecalculateResponse,
    RecommendResponse,
)


client = TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# 공통 stub 빌더 — 카드 API 핸들러가 요구하는 데이터 형태
# ---------------------------------------------------------------------------

_STUB_TRACE = {
    "benefit_id": "stub_card_b_coffee_cafe",
    "content": "카페 10% 할인",
    "category": "Coffee",
    "sub_category": "cafe",
    "applied_budget": 50000,
    "yielded_discount": 5000,
    "user_choice": True,
    "warnings": [],
}

_STUB_BREAKDOWN = {
    "category": "Coffee",
    "monthly_discount_krw": 5000,
    "discount_info": {},
    "warnings": [],
}


def _stub_card_result(card_id: str = "stub_card", card_name: str = "스텁카드", company: str = "테스트카드사") -> dict:
    """`CardRecommendService.calculate_benefits` 가 돌려주는 dict 한 장 shape."""
    return {
        "card_name": card_name,
        "card_company": company,
        "card_id": card_id,
        "annual_fee": 10000,
        "minimum_performance": 300000,
        "expected_monthly_benefit": 5000,
        "expected_yearly_benefit": 60000,
        "performance_met": True,
        "category_breakdown": [dict(_STUB_BREAKDOWN)],
        "applied_benefits_trace": [dict(_STUB_TRACE)],
        "warnings": [],
        "_card_data": {
            "card_meta": {
                "card_id": card_id,
                "card_slug": card_id,
                "card_name": card_name,
                "card_company": company,
            }
        },
    }


def _stub_recommend_card_dict(card_id: str = "stub_card", explanation: str = "") -> dict:
    """Pydantic `RecommendCard` 로 바로 검증 가능한 dict."""
    return {
        "card_name": "스텁카드",
        "card_company": "테스트카드사",
        "card_id": card_id,
        "annual_fee": 10000,
        "minimum_performance": 300000,
        "expected_monthly_benefit": 5000,
        "expected_yearly_benefit": 60000,
        "category_breakdown": [dict(_STUB_BREAKDOWN)],
        "applied_benefits_trace": [dict(_STUB_TRACE)],
        "explanation": explanation,
    }


def _install_card_api_stubs(monkeypatch: pytest.MonkeyPatch, *, top_card_id: str = "stub_card") -> None:
    """`/cards/*` 핸들러가 외부 인스턴스를 만들지 못하도록 전부 stub 으로 치환."""

    stub_cards_meta = [
        {
            "card_meta": {
                "card_id": top_card_id,
                "card_slug": top_card_id,
                "card_name": "스텁카드",
                "card_company": "테스트카드사",
                "annual_fee_domestic": 10000,
                "minimum_performance": 300000,
            },
            "_card_categories": {"Coffee", "Shopping"},
        }
    ]

    class StubCardRepo:
        def __init__(self, *args, **kwargs):
            pass

        def list_cards(self):
            return stub_cards_meta

    class StubDigestRepo:
        def __init__(self, *args, **kwargs):
            pass

        async def get_digest(self, *args, **kwargs):
            return "stub-digest"

    class StubRecommendService:
        def __init__(self, *args, **kwargs):
            pass

        def filter_cards(self, total_budget, category_spending):
            return stub_cards_meta

        async def calculate_benefits(self, cards, total_budget, category_spending, excluded_benefit_ids=None):
            return [_stub_card_result(card_id=top_card_id)]

        def rank_top(self, calc_results, top_n=3):
            return calc_results[:top_n]

    class StubExplainService:
        def __init__(self, *args, **kwargs):
            pass

        async def explain(self, total_budget, category_spending, ranked_cards, card_digest):
            return "스텁 큐레이션 텍스트"

        async def compare(self, total_budget, category_spending, current, recommended):
            return "스텁 비교 텍스트"

        async def answer_qa(self, raw_data, question):
            return "스텁 Q&A 답변"

        def build_recommended_cards(self, ranked_cards, explanation, digests=None):
            out = []
            for idx, card in enumerate(ranked_cards):
                out.append(
                    _stub_recommend_card_dict(
                        card_id=card.get("card_id", top_card_id),
                        explanation=explanation if idx == 0 else "",
                    )
                )
            return out

    monkeypatch.setattr(card_api, "DatasetCardRepository", StubCardRepo)
    monkeypatch.setattr(card_api, "DigestRepository", StubDigestRepo)
    monkeypatch.setattr(card_api, "CardRecommendService", StubRecommendService)
    monkeypatch.setattr(card_api, "ExplainService", StubExplainService)
    monkeypatch.setattr(card_api, "get_llm", lambda *a, **k: object())


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestRoot:
    def test_returns_status_ok(self) -> None:
        res = client.get("/")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/v1/cards — 카드 카탈로그
# ---------------------------------------------------------------------------

class TestListCards:
    def test_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch)

        res = client.get("/api/v1/cards")
        assert res.status_code == 200

        body = res.json()
        # Pydantic 으로 전체 스키마 검증 (타입/필드 누락 자동 감지)
        parsed = CardListResponse.model_validate(body)

        # 스키마 불변 고정 — cards 배열 + 각 항목의 필드셋
        assert "cards" in body
        assert len(parsed.cards) == 1

        item = parsed.cards[0]
        assert set(item.model_dump().keys()) == {
            "card_id", "card_name", "card_company", "annual_fee",
            "minimum_performance", "categories", "digest_summary",
        }
        assert item.card_id == "stub_card"
        assert isinstance(item.categories, list)


# ---------------------------------------------------------------------------
# POST /api/v1/cards/recommend
# ---------------------------------------------------------------------------

class TestRecommend:
    _PAYLOAD = {
        "total_budget": 500000,
        "top_n": 3,
        "category_spending": {"Coffee": 50000, "Shopping": 100000},
    }

    def test_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch)

        res = client.post("/api/v1/cards/recommend", json=self._PAYLOAD)
        assert res.status_code == 200

        body = res.json()
        parsed = RecommendResponse.model_validate(body)

        # 응답 최상위 불변
        assert set(body.keys()) == {"recommended_cards", "explanation"}
        assert parsed.explanation == "스텁 큐레이션 텍스트"
        assert len(parsed.recommended_cards) == 1

        # RecommendCard 필드셋 — 프론트 계약의 핵심
        card = parsed.recommended_cards[0]
        expected_fields = {
            "card_name", "card_company", "card_id",
            "annual_fee", "minimum_performance",
            "expected_monthly_benefit", "expected_yearly_benefit",
            "category_breakdown", "applied_benefits_trace", "explanation",
        }
        assert set(card.model_dump().keys()) == expected_fields
        # 삭제된 구 필드가 부활하지 않아야 함
        assert "benefit_receipt" not in card.model_dump()

        # BenefitTraceItem 필드 — category/sub_category 는 PR #e135436 에서 추가됨
        trace = card.applied_benefits_trace[0]
        assert trace.category == "Coffee"
        assert trace.sub_category == "cafe"
        assert trace.user_choice is True

    def test_rejects_zero_total_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch)
        res = client.post(
            "/api/v1/cards/recommend",
            json={"total_budget": 0, "category_spending": {"Coffee": 1000}},
        )
        assert res.status_code == 400
        body = res.json()
        assert body["error_code"] == "INVALID_INPUT"
        assert body["fallback"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/cards/compare
# ---------------------------------------------------------------------------

class TestCompare:
    _PAYLOAD = {
        "total_budget": 500000,
        "category_spending": {"Coffee": 50000, "Shopping": 100000},
        "current_card_id": "stub_card",
    }

    def test_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch, top_card_id="stub_card")

        res = client.post("/api/v1/cards/compare", json=self._PAYLOAD)
        assert res.status_code == 200

        body = res.json()
        parsed = CompareResponse.model_validate(body)

        # CompareResponse 최상위 불변
        assert set(body.keys()) == {
            "current_card", "recommended_cards", "recommended_card",
            "monthly_diff", "yearly_diff", "category_comparison", "explanation",
        }

        # current_card / recommended_card 는 RecommendCard 스키마여야
        assert parsed.current_card.card_id == "stub_card"
        assert parsed.recommended_card.card_id == parsed.recommended_cards[0].card_id

        # category_comparison 항목 구조
        if parsed.category_comparison:
            cc = parsed.category_comparison[0]
            assert set(cc.model_dump().keys()) == {
                "category", "current_benefit", "recommended_benefit", "diff",
            }

        assert isinstance(parsed.monthly_diff, int)
        assert isinstance(parsed.yearly_diff, int)


# ---------------------------------------------------------------------------
# POST /api/v1/cards/qa
# ---------------------------------------------------------------------------

class TestQA:
    _PAYLOAD = {
        "raw_data": '{"recommended_cards": []}',
        "question": "왜 이 카드가 1순위야?",
    }

    def test_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch)

        res = client.post("/api/v1/cards/qa", json=self._PAYLOAD)
        assert res.status_code == 200

        body = res.json()
        parsed = QAResponse.model_validate(body)

        assert set(body.keys()) == {"answer"}
        assert parsed.answer == "스텁 Q&A 답변"

    def test_invalid_raw_data_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_card_api_stubs(monkeypatch)
        res = client.post(
            "/api/v1/cards/qa",
            json={"raw_data": "{invalid_json", "question": "안녕"},
        )
        assert res.status_code == 400
        assert res.json()["error_code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# POST /api/v1/cards/recalculate
# ---------------------------------------------------------------------------

class TestRecalculate:
    def _payload(self, *, top_card_id: str = "stub_card", second_card_id: str | None = None) -> dict:
        # 각 카드에 고유한 benefit_id 를 부여해야 exclude 가 카드별로 독립적으로 적용됨
        old = _stub_recommend_card_dict(card_id=top_card_id, explanation="기존 1순위 설명")
        old["applied_benefits_trace"][0]["benefit_id"] = f"{top_card_id}_benefit"
        cards = [old]
        if second_card_id:
            new = _stub_recommend_card_dict(card_id=second_card_id)
            new["expected_monthly_benefit"] = 3000  # 1순위보다 낮게
            new["applied_benefits_trace"][0]["benefit_id"] = f"{second_card_id}_benefit"
            new["applied_benefits_trace"][0]["yielded_discount"] = 3000
            cards.append(new)
        return {
            "total_budget": 500000,
            "category_spending": {"Coffee": 50000},
            "recommended_cards": cards,
            "excluded_benefit_ids": [],
        }

    def test_schema_no_rank_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """순위 변동이 없으면 top-level explanation 은 빈 문자열."""
        _install_card_api_stubs(monkeypatch)

        res = client.post("/api/v1/cards/recalculate", json=self._payload())
        assert res.status_code == 200

        body = res.json()
        parsed = RecalculateResponse.model_validate(body)

        # 최상위 불변 — explanation 필드 존재 (PR #48 이후 규격)
        assert set(body.keys()) == {"recommended_cards", "explanation"}
        assert parsed.explanation == ""  # 순위 변동 없음 → 빈 문자열
        assert len(parsed.recommended_cards) >= 1

    def test_schema_rank_change_regenerates_explanation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1순위 카드 card_id 가 바뀌면 새 큐레이션 텍스트가 실려 내려온다."""
        _install_card_api_stubs(monkeypatch)

        payload = self._payload(top_card_id="old_top", second_card_id="new_top")
        # old_top 의 유일한 benefit 만 제외 → old_top 의 월 혜택이 0 으로 떨어지고
        # new_top(3000원) 이 1순위로 올라옴 → 핸들러가 LLM explain 재호출
        payload["excluded_benefit_ids"] = ["old_top_benefit"]

        res = client.post("/api/v1/cards/recalculate", json=payload)
        assert res.status_code == 200

        body = res.json()
        parsed = RecalculateResponse.model_validate(body)
        assert parsed.recommended_cards[0].card_id == "new_top"
        assert parsed.explanation == "스텁 큐레이션 텍스트"


# ---------------------------------------------------------------------------
# POST /api/v1/advisor/ask
# ---------------------------------------------------------------------------

class TestAdvisorAsk:
    _PAYLOAD = {
        "card_name": "스텁카드",
        "query_type": "reviews",
    }

    def test_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(advisor_api, "get_advice", AsyncMock(return_value="스텁 어드바이저 답변"))

        res = client.post("/api/v1/advisor/ask", json=self._PAYLOAD)
        assert res.status_code == 200

        body = res.json()
        assert set(body.keys()) == {"answer", "query_used"}
        assert body["answer"] == "스텁 어드바이저 답변"
        # query_used 는 실제 QUERIES 딕셔너리의 `reviews` 항목 값
        assert body["query_used"] == advisor_api.QUERIES["reviews"]


# ---------------------------------------------------------------------------
# GET /api/v1/advisor/queries
# ---------------------------------------------------------------------------

class TestAdvisorQueries:
    def test_schema(self) -> None:
        res = client.get("/api/v1/advisor/queries")
        assert res.status_code == 200

        body = res.json()
        # 최상위 두 키 고정 (프론트 UI 구성 계약)
        assert set(body.keys()) == {"standalone", "details"}

        # standalone 그룹 — reviews / how_to_apply 두 버튼
        assert set(body["standalone"].keys()) == {"reviews", "how_to_apply"}
        # details 그룹 — 4개 서브 버튼
        assert set(body["details"].keys()) == {
            "credit_fees", "international_fees", "late_payment", "revolving",
        }

        # 모든 value 는 비어 있지 않은 프롬프트 문자열
        for group in ("standalone", "details"):
            for query_type, prompt in body[group].items():
                assert isinstance(prompt, str) and prompt, f"{group}.{query_type} empty"
