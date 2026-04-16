"""ExplainService 내부 포매팅/집계 헬퍼 테스트.

LLM 호출이 없는 순수 로직만 검증합니다.
(ExplainService는 __init__에서 LLM을 주입받으므로 monkeypatch로 우회)
"""
from __future__ import annotations

import pytest

from app.services.explain_service import ExplainService


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> ExplainService:
    """LLM 없이 ExplainService 인스턴스를 만든다."""
    monkeypatch.setattr(
        "app.services.explain_service.ExplainService.__init__",
        lambda self, llm: setattr(self, "_resilient_invoke", None),
    )
    return ExplainService(llm=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_user_spending
# ---------------------------------------------------------------------------

class TestBuildUserSpending:
    def test_total_line_first(self, svc: ExplainService):
        result = svc.build_user_spending(500000, {"Coffee": 50000})
        assert result.startswith("월 총 소비: 500,000원")

    def test_int_category_single_line(self, svc: ExplainService):
        result = svc.build_user_spending(500000, {"Coffee": 50000})
        assert "- Coffee: 월 50,000원" in result
        # sub 라인이 없어야 함
        assert "└" not in result

    def test_dict_category_with_subs(self, svc: ExplainService):
        result = svc.build_user_spending(
            300000,
            {"Coffee": {"total": 50000, "cafe": "75%", "bakery": "25%"}},
        )
        assert "- Coffee: 월 50,000원" in result
        assert "└ cafe: 75%" in result
        assert "└ bakery: 25%" in result

    def test_total_key_not_shown_as_sub(self, svc: ExplainService):
        """'total' 키는 sub 항목으로 출력되지 않아야 함"""
        result = svc.build_user_spending(300000, {"Coffee": {"total": 50000, "cafe": "100%"}})
        assert "└ total" not in result

    def test_mixed_int_and_dict(self, svc: ExplainService):
        result = svc.build_user_spending(
            500000,
            {"Coffee": {"total": 50000, "cafe": "100%"}, "Shopping": 100000},
        )
        assert "- Coffee: 월 50,000원" in result
        assert "└ cafe: 100%" in result
        assert "- Shopping: 월 100,000원" in result

    def test_empty_category_spending(self, svc: ExplainService):
        result = svc.build_user_spending(500000, {})
        assert result == "월 총 소비: 500,000원"


# ---------------------------------------------------------------------------
# build_calc_summary — 30% 고비중 혜택 필터링이 핵심
# ---------------------------------------------------------------------------

class TestBuildCalcSummary:
    def _card(self, trace: list[dict] | None = None, monthly: int = 10000) -> dict:
        return {
            "card_name": "테스트카드",
            "card_company": "테스트카드사",
            "annual_fee": 15000,
            "expected_monthly_benefit": monthly,
            "expected_yearly_benefit": monthly * 12,
            "category_breakdown": [
                {"category": "Coffee", "monthly_discount_krw": monthly, "discount_info": {}}
            ],
            "applied_benefits_trace": trace or [],
        }

    def test_basic_info_always_included(self, svc: ExplainService):
        result = svc.build_calc_summary(self._card(monthly=10000))
        assert "테스트카드" in result
        assert "테스트카드사" in result
        assert "15,000원" in result  # 연회비
        assert "10,000원" in result  # 월 할인

    def test_no_trace_no_high_impact_section(self, svc: ExplainService):
        result = svc.build_calc_summary(self._card(trace=[], monthly=10000))
        assert "고비중 혜택" not in result

    def test_high_impact_shown_when_over_30_percent(self, svc: ExplainService):
        """yielded_discount / total ≥ 0.3 인 항목은 고비중 섹션에 노출"""
        trace = [
            {"benefit_id": "b1", "content": "카페 10% 할인",
             "yielded_discount": 5000, "applied_budget": 50000},  # 50%
        ]
        result = svc.build_calc_summary(self._card(trace=trace, monthly=10000))
        assert "고비중 혜택" in result
        assert "카페 10% 할인" in result
        assert "50%" in result  # 비율

    def test_low_impact_excluded(self, svc: ExplainService):
        """30% 미만은 고비중 섹션에 나타나지 않아야 함"""
        trace = [
            {"benefit_id": "b1", "content": "저비중 혜택",
             "yielded_discount": 2000, "applied_budget": 50000},  # 20%
        ]
        result = svc.build_calc_summary(self._card(trace=trace, monthly=10000))
        assert "고비중 혜택" not in result
        assert "저비중 혜택" not in result

    def test_exactly_30_percent_included(self, svc: ExplainService):
        """30% 경계값은 포함되어야 함 (>= 0.3)"""
        trace = [
            {"benefit_id": "b1", "content": "딱 30%",
             "yielded_discount": 3000, "applied_budget": 30000},
        ]
        result = svc.build_calc_summary(self._card(trace=trace, monthly=10000))
        assert "고비중 혜택" in result
        assert "딱 30%" in result

    def test_zero_total_discount_no_division_error(self, svc: ExplainService):
        """expected_monthly_benefit이 0이면 고비중 계산을 건너뛰어 ZeroDivisionError 없어야 함"""
        trace = [
            {"benefit_id": "b1", "content": "혜택",
             "yielded_discount": 0, "applied_budget": 10000},
        ]
        result = svc.build_calc_summary(self._card(trace=trace, monthly=0))
        assert "고비중 혜택" not in result

    def test_discount_info_sub_categories_shown(self, svc: ExplainService):
        card = {
            "card_name": "서브카드",
            "card_company": "C",
            "annual_fee": 0,
            "expected_monthly_benefit": 5000,
            "expected_yearly_benefit": 60000,
            "category_breakdown": [
                {"category": "Coffee", "monthly_discount_krw": 5000,
                 "discount_info": {"sub_category_cafe": 3000, "sub_category_bakery": 2000}},
            ],
            "applied_benefits_trace": [],
        }
        result = svc.build_calc_summary(card)
        # prefix 제거된 이름으로 출력되는지
        assert "cafe: 3,000원" in result
        assert "bakery: 2,000원" in result


# ---------------------------------------------------------------------------
# _round_to_thousands
# ---------------------------------------------------------------------------

class TestRoundToThousands:
    def test_zero_returns_zero_label(self):
        assert ExplainService._round_to_thousands(0) == "0원"

    def test_exact_thousand(self):
        assert ExplainService._round_to_thousands(28000) == "약 28,000원"

    def test_rounds_down_below_half(self):
        assert ExplainService._round_to_thousands(28400) == "약 28,000원"

    def test_rounds_up_above_half(self):
        assert ExplainService._round_to_thousands(28600) == "약 29,000원"

    def test_bankers_rounding_28500_rounds_to_even_down(self):
        """Python round()는 banker's rounding: 28,500 → 28,000 (28이 짝수)"""
        assert ExplainService._round_to_thousands(28500) == "약 28,000원"

    def test_bankers_rounding_29500_rounds_to_even_up(self):
        """Python round()는 banker's rounding: 29,500 → 30,000 (30이 짝수)"""
        assert ExplainService._round_to_thousands(29500) == "약 30,000원"

    def test_small_amount_rounds_to_zero(self):
        """499원 → "약 0원" (1,000원 미만은 0으로 반올림)"""
        assert ExplainService._round_to_thousands(499) == "약 0원"


# ---------------------------------------------------------------------------
# _format_card_detail
# ---------------------------------------------------------------------------

class TestFormatCardDetail:
    def _card(self) -> dict:
        return {
            "card_name": "현대카드 Z",
            "card_company": "현대카드",
            "annual_fee": 15000,
            "expected_monthly_benefit": 25000,
            "expected_yearly_benefit": 300000,
            "category_breakdown": [
                {"category": "Coffee", "monthly_discount_krw": 10000, "warnings": []},
                {"category": "Food", "monthly_discount_krw": 15000,
                 "warnings": ["전월 실적 30만원 이상"]},
            ],
        }

    def test_rank_prefix_shown(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=1)
        assert result.startswith("[1순위]")

    def test_different_rank_prefix(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=3)
        assert result.startswith("[3순위]")

    def test_card_name_and_company(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=1)
        assert "현대카드 Z" in result
        assert "(현대카드)" in result

    def test_annual_fee_and_benefits(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=1)
        assert "연회비: 15,000원" in result
        # 월 예상 할인은 _round_to_thousands 적용 (25000 → 약 25,000원)
        assert "약 25,000원" in result
        assert "300,000원" in result  # 연간 혜택

    def test_category_breakdown_shown(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=1)
        assert "Coffee: 10,000원" in result
        assert "Food: 15,000원" in result

    def test_warnings_shown_with_icon(self, svc: ExplainService):
        result = svc._format_card_detail(self._card(), rank=1)
        assert "⚠ 전월 실적 30만원 이상" in result

    def test_missing_yearly_benefit_defaults_to_zero(self, svc: ExplainService):
        """expected_yearly_benefit 키가 없으면 0원으로 처리"""
        card = self._card()
        del card["expected_yearly_benefit"]
        result = svc._format_card_detail(card, rank=1)
        assert "0원" in result  # 연 순이익 자리

    def test_empty_category_breakdown_does_not_crash(self, svc: ExplainService):
        card = self._card()
        card["category_breakdown"] = []
        result = svc._format_card_detail(card, rank=1)
        assert "[1순위]" in result  # 기본 정보는 여전히 출력
