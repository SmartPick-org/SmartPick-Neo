"""
TDD: benefit_receipt / excluded_benefit_ids / top_n 기능 검증

커버하는 항목
─────────────────────────────────────────────────────────────
1. BenefitCalculator.calculate() — benefit_details 구조 검증
2. BenefitCalculator.calculate() — excluded_benefit_ids 적용
3. _enrich_benefit_details()     — content join 로직
4. CardRecommendService          — excluded_benefit_ids 전달 & top_n
5. ExplainService.build_recommended_cards() — benefit_receipt 포함
"""

import pytest
from app.tools.Calc_tool import BenefitCalculator
from app.services.card_service import CardRecommendService, _enrich_benefit_details
from app.services.explain_service import ExplainService


# ─────────────────────────────────────────────
# 공통 픽스처
# ─────────────────────────────────────────────

def _make_benefit(benefit_id: str, category: str, sub_category: str | None,
                  rate: float, monthly_limit: float | None = None,
                  ui_warnings: list[str] | None = None) -> dict:
    return {
        "benefit_id": benefit_id,
        "category": category,
        "sub_category": sub_category,
        "frequency": "MONTHLY",
        "reward_type": "DISCOUNT",
        "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
        "tier_conditions": [],
        "calculation_rule": {
            "calc_method": "RATE",
            "rate": rate,
            "monthly_limit": monthly_limit,
        },
        "transaction_conditions": {},
        "ui_warnings": ui_warnings or [],
        "group_id": None,
    }


CARD_MULTI = {
    "card_meta": {
        "card_id": "test_multi",
        "card_name": "멀티혜택카드",
        "card_company": "테스트카드사",
        "annual_fee": 15000,
        "minimum_performance": 0,
        "performance_excluded_categories": [],
    },
    "benefit_groups": [],
    "benefits": [
        _make_benefit("b001", "Coffee",   "cafe",     0.10, monthly_limit=5000),
        _make_benefit("b002", "Food",     "delivery", 0.05, monthly_limit=None),
        _make_benefit("b003", "Shopping", None,       0.03, monthly_limit=None,
                      ui_warnings=["전월 실적 30만원 이상 시 적용"]),
    ],
}

# 카드 JSON의 benefits 배열 (content 필드 포함)
RAW_BENEFITS_CONTENT = [
    {"benefit_id": "b001", "content": "카페 10% 할인 (월 최대 5,000원)"},
    {"benefit_id": "b002", "content": "배달앱 5% 할인"},
    {"benefit_id": "b003", "content": "국내 일반 쇼핑 3% 할인"},
]

SPENDING = {
    "Coffee": {"total": 50000, "cafe": "100%"},   # b001: min(50000*0.1=5000, 5000) = 5000
    "Food":   {"total": 100000, "delivery": "100%"},  # b002: 100000*0.05 = 5000
    "Shopping": 80000,                              # b003: 80000*0.03 = 2400
}
TOTAL_BUDGET = 230000


# ═════════════════════════════════════════════
# 1. BenefitCalculator — benefit_details 구조
# ═════════════════════════════════════════════

class TestBenefitDetails:
    def setup_method(self):
        self.calc = BenefitCalculator(CARD_MULTI)
        self.result = self.calc.calculate(SPENDING, user_total_spend=TOTAL_BUDGET)

    def test_benefit_details_present(self):
        """benefit_details 키가 결과에 존재해야 한다"""
        assert "benefit_details" in self.result

    def test_benefit_details_only_positive_amounts(self):
        """amount_krw > 0 인 항목만 포함되어야 한다"""
        for item in self.result["benefit_details"]:
            assert item["amount_krw"] > 0, f"{item['benefit_id']} 가 amount_krw=0이지만 포함됨"

    def test_benefit_details_has_required_fields(self):
        """각 항목에 필수 필드가 모두 있어야 한다"""
        required = {"benefit_id", "category", "sub_category", "amount_krw", "warnings"}
        for item in self.result["benefit_details"]:
            assert required <= item.keys(), f"누락 필드: {required - item.keys()}"

    def test_benefit_details_amounts_correct(self):
        """계산 금액이 예상값과 일치해야 한다"""
        detail_map = {d["benefit_id"]: d["amount_krw"] for d in self.result["benefit_details"]}
        assert detail_map["b001"] == 5000   # 한도 5000 적용
        assert detail_map["b002"] == 5000   # 100000 * 5%
        assert detail_map["b003"] == 2400   # 80000  * 3%

    def test_benefit_details_warnings_propagated(self):
        """ui_warnings가 benefit_details의 warnings에 포함되어야 한다"""
        detail_map = {d["benefit_id"]: d for d in self.result["benefit_details"]}
        assert "전월 실적 30만원 이상 시 적용" in detail_map["b003"]["warnings"]

    def test_benefit_details_sub_category(self):
        """sub_category 값이 올바르게 채워져야 한다"""
        detail_map = {d["benefit_id"]: d for d in self.result["benefit_details"]}
        assert detail_map["b001"]["sub_category"] == "cafe"
        assert detail_map["b002"]["sub_category"] == "delivery"
        assert detail_map["b003"]["sub_category"] is None


# ═════════════════════════════════════════════
# 2. BenefitCalculator — excluded_benefit_ids
# ═════════════════════════════════════════════

class TestExcludedBenefitIds:
    def test_exclude_one_benefit(self):
        """b001을 제외하면 benefit_details에 b001이 없어야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, user_total_spend=TOTAL_BUDGET,
                                excluded_benefit_ids={"b001"})
        ids = {d["benefit_id"] for d in result["benefit_details"]}
        assert "b001" not in ids
        assert "b002" in ids
        assert "b003" in ids

    def test_exclude_one_reduces_monthly_total(self):
        """b001(5000) 제외 시 월 합계가 5000 감소해야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        base = BenefitCalculator(CARD_MULTI).calculate(SPENDING, TOTAL_BUDGET)
        excl = calc.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids={"b001"})
        assert excl["monthly_total_krw"] == base["monthly_total_krw"] - 5000

    def test_exclude_multiple_benefits(self):
        """b001, b002 제외 시 b003만 남아야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET,
                                excluded_benefit_ids={"b001", "b002"})
        ids = {d["benefit_id"] for d in result["benefit_details"]}
        assert ids == {"b003"}

    def test_exclude_all_benefits_zero(self):
        """모든 benefit 제외 시 월 합계 0원이어야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET,
                                excluded_benefit_ids={"b001", "b002", "b003"})
        assert result["monthly_total_krw"] == 0
        assert result["benefit_details"] == []

    def test_exclude_none_is_same_as_default(self):
        """excluded_benefit_ids=None은 제외 없음과 동일해야 한다"""
        calc1 = BenefitCalculator(CARD_MULTI)
        calc2 = BenefitCalculator(CARD_MULTI)
        r1 = calc1.calculate(SPENDING, TOTAL_BUDGET)
        r2 = calc2.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids=None)
        assert r1["monthly_total_krw"] == r2["monthly_total_krw"]

    def test_exclude_nonexistent_id_no_effect(self):
        """존재하지 않는 ID 제외는 결과에 영향 없어야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        base = BenefitCalculator(CARD_MULTI).calculate(SPENDING, TOTAL_BUDGET)
        result = calc.calculate(SPENDING, TOTAL_BUDGET,
                                excluded_benefit_ids={"not_exist_id"})
        assert result["monthly_total_krw"] == base["monthly_total_krw"]


# ═════════════════════════════════════════════
# 3. _enrich_benefit_details — content join
# ═════════════════════════════════════════════

class TestEnrichBenefitDetails:
    def _make_detail(self, benefit_id: str, amount: int = 1000) -> dict:
        return {
            "benefit_id": benefit_id,
            "category": "Coffee",
            "sub_category": "cafe",
            "amount_krw": amount,
            "warnings": [],
        }

    def test_content_is_joined(self):
        """benefit_id로 content가 올바르게 join되어야 한다"""
        details = [self._make_detail("b001"), self._make_detail("b002")]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        by_id = {e["benefit_id"]: e for e in enriched}
        assert by_id["b001"]["content"] == "카페 10% 할인 (월 최대 5,000원)"
        assert by_id["b002"]["content"] == "배달앱 5% 할인"

    def test_missing_content_is_empty_string(self):
        """raw_benefits에 없는 benefit_id는 content=""가 되어야 한다"""
        details = [self._make_detail("unknown_id")]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        assert enriched[0]["content"] == ""

    def test_original_fields_preserved(self):
        """기존 필드가 그대로 유지되어야 한다"""
        details = [self._make_detail("b001")]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        assert enriched[0]["amount_krw"] == 1000
        assert enriched[0]["category"] == "Coffee"

    def test_empty_raw_benefits(self):
        """raw_benefits가 빈 리스트이면 모든 content=""여야 한다"""
        details = [self._make_detail("b001"), self._make_detail("b002")]
        enriched = _enrich_benefit_details(details, [])
        for e in enriched:
            assert e["content"] == ""

    def test_empty_details(self):
        """benefit_details가 빈 리스트이면 빈 리스트를 반환해야 한다"""
        result = _enrich_benefit_details([], RAW_BENEFITS_CONTENT)
        assert result == []


# ═════════════════════════════════════════════
# 4. ExplainService.build_recommended_cards — benefit_receipt
# ═════════════════════════════════════════════

class TestBuildRecommendedCards:
    """
    build_recommended_cards()가 benefit_receipt를 올바르게 포함하는지 검증합니다.
    ExplainService는 LLM 없이 instantiate하므로 __init__ monkeypatching 활용.
    """

    def _make_ranked_card(self, benefit_details: list[dict] | None = None) -> dict:
        default_details = [
            {"benefit_id": "b001", "category": "Coffee", "sub_category": "cafe",
             "amount_krw": 5000, "content": "카페 10% 할인", "warnings": []},
            {"benefit_id": "b002", "category": "Food",   "sub_category": "delivery",
             "amount_krw": 5000, "content": "배달앱 5% 할인",  "warnings": []},
            {"benefit_id": "b003", "category": "Shopping", "sub_category": None,
             "amount_krw": 2400, "content": "쇼핑 3% 할인",   "warnings": ["전월 실적 30만원 이상"]},
        ]
        return {
            "card_name": "테스트카드",
            "card_company": "테스트카드사",
            "card_id": "test_card",
            "annual_fee": 15000,
            "minimum_performance": 300000,
            "expected_monthly_benefit": 12400,
            "expected_yearly_benefit": 148800,
            "category_breakdown": [
                {"category": "Coffee", "monthly_discount_krw": 5000, "discount_info": {}, "warnings": []},
                {"category": "Food",   "monthly_discount_krw": 5000, "discount_info": {}, "warnings": []},
                {"category": "Shopping","monthly_discount_krw": 2400,"discount_info": {}, "warnings": []},
            ],
            "benefit_details": benefit_details if benefit_details is not None else default_details,
        }

    def _get_service(self, monkeypatch) -> ExplainService:
        """LLM 없이 ExplainService 인스턴스를 만든다"""
        monkeypatch.setattr(
            "app.services.explain_service.ExplainService.__init__",
            lambda self, llm: setattr(self, "_resilient_invoke", None),
        )
        return ExplainService(llm=None)  # type: ignore[arg-type]

    def test_benefit_receipt_included(self, monkeypatch):
        """benefit_receipt 필드가 결과에 포함되어야 한다"""
        svc = self._get_service(monkeypatch)
        ranked = [self._make_ranked_card()]
        cards = svc.build_recommended_cards(ranked, explanation="테스트")
        assert "benefit_receipt" in cards[0]

    def test_benefit_receipt_count_matches(self, monkeypatch):
        """benefit_receipt 항목 수가 benefit_details와 같아야 한다"""
        svc = self._get_service(monkeypatch)
        ranked = [self._make_ranked_card()]
        cards = svc.build_recommended_cards(ranked, explanation="테스트")
        assert len(cards[0]["benefit_receipt"]) == 3

    def test_benefit_receipt_fields(self, monkeypatch):
        """benefit_receipt의 각 항목 값이 benefit_details와 일치해야 한다"""
        svc = self._get_service(monkeypatch)
        ranked = [self._make_ranked_card()]
        cards = svc.build_recommended_cards(ranked, explanation="테스트")
        first = cards[0]["benefit_receipt"][0]
        assert first["benefit_id"] == "b001"
        assert first["amount_krw"] == 5000
        assert first["content"] == "카페 10% 할인"

    def test_benefit_receipt_empty_when_no_details(self, monkeypatch):
        """benefit_details가 없으면 benefit_receipt는 빈 리스트여야 한다"""
        svc = self._get_service(monkeypatch)
        ranked = [self._make_ranked_card(benefit_details=[])]
        cards = svc.build_recommended_cards(ranked, explanation="테스트")
        assert cards[0]["benefit_receipt"] == []

    def test_multiple_cards_each_have_benefit_receipt(self, monkeypatch):
        """여러 카드가 각자 benefit_receipt를 가져야 한다"""
        svc = self._get_service(monkeypatch)
        card2 = self._make_ranked_card()
        card2["card_id"] = "test_card_2"
        ranked = [self._make_ranked_card(), card2]
        cards = svc.build_recommended_cards(ranked, explanation="테스트")
        assert len(cards) == 2
        for c in cards:
            assert "benefit_receipt" in c
            assert len(c["benefit_receipt"]) == 3


# ═════════════════════════════════════════════
# 5. CardRecommendService — top_n & excluded_benefit_ids 전달
# ═════════════════════════════════════════════

class FakeRepo:
    def __init__(self, cards):
        self._cards = cards
    def list_cards(self):
        return self._cards


def _make_card_data(card_id: str, card_name: str, monthly_benefit: int,
                    benefit_details: list[dict] | None = None) -> dict:
    return {
        "card_meta": {
            "card_id": card_id,
            "card_name": card_name,
            "card_company": "테스트카드사",
            "annual_fee": 0,
            "minimum_performance": 0,
        },
        "_card_categories": {"Coffee"},
        "benefits": [],
        "benefit_groups": [],
        "_monthly_benefit": monthly_benefit,  # FakeCalculator가 참조
    }


class FakeCalculatorFactory:
    """monkeypatch용 — card 메타에서 _monthly_benefit을 꺼내 고정값 반환"""
    def __init__(self, card: dict):
        self._card = card
        self._excluded: set[str] = set()

    def calculate(self, spending, user_total_spend=None, excluded_benefit_ids=None):
        self._excluded = excluded_benefit_ids or set()
        monthly = self._card.get("_monthly_benefit", 0)
        return {
            "monthly_total_krw": monthly,
            "annual_total_krw": 0,
            "performance_met": True,
            "category_breakdown": [],
            "benefit_details": [
                {"benefit_id": "bid1", "category": "Coffee", "sub_category": None,
                 "amount_krw": monthly, "warnings": []}
            ] if monthly > 0 and "bid1" not in self._excluded else [],
            "annual_breakdown": [],
            "warnings": [],
        }


@pytest.mark.asyncio
async def test_rank_top_respects_top_n():
    """rank_top(top_n=2)이면 정확히 2개만 반환해야 한다"""
    svc = CardRecommendService(FakeRepo([]))
    results = [
        {"card_name": "A", "expected_monthly_benefit": 10},
        {"card_name": "B", "expected_monthly_benefit": 30},
        {"card_name": "C", "expected_monthly_benefit": 20},
        {"card_name": "D", "expected_monthly_benefit": 5},
    ]
    ranked = svc.rank_top(results, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["card_name"] == "B"
    assert ranked[1]["card_name"] == "C"


@pytest.mark.asyncio
async def test_rank_top_top_n_1():
    """rank_top(top_n=1)이면 1위 카드만 반환해야 한다"""
    svc = CardRecommendService(FakeRepo([]))
    results = [
        {"card_name": "A", "expected_monthly_benefit": 15},
        {"card_name": "B", "expected_monthly_benefit": 50},
    ]
    ranked = svc.rank_top(results, top_n=1)
    assert len(ranked) == 1
    assert ranked[0]["card_name"] == "B"


@pytest.mark.asyncio
async def test_calculate_benefits_passes_excluded_ids(monkeypatch):
    """calculate_benefits가 excluded_benefit_ids를 BenefitCalculator에 올바르게 전달해야 한다"""
    received_excluded = []

    class CapturingCalculator:
        def __init__(self, card):
            self.card = card
        def calculate(self, spending, user_total_spend=None, excluded_benefit_ids=None):
            received_excluded.append(excluded_benefit_ids)
            return {
                "monthly_total_krw": 1000, "annual_total_krw": 0,
                "performance_met": True, "category_breakdown": [],
                "benefit_details": [], "annual_breakdown": [], "warnings": [],
            }

    monkeypatch.setattr("app.services.card_service.BenefitCalculator", CapturingCalculator)
    cards = [_make_card_data("c1", "CardA", 1000)]
    svc = CardRecommendService(FakeRepo(cards))
    await svc.calculate_benefits(cards, 300000, {"Coffee": 50000},
                                 excluded_benefit_ids=["b001", "b002"])

    assert len(received_excluded) == 1
    assert received_excluded[0] == {"b001", "b002"}


@pytest.mark.asyncio
async def test_calculate_benefits_excluded_ids_none(monkeypatch):
    """excluded_benefit_ids=None 일 때 None이 그대로 전달되어야 한다"""
    received_excluded = []

    class CapturingCalculator:
        def __init__(self, card):
            pass
        def calculate(self, spending, user_total_spend=None, excluded_benefit_ids=None):
            received_excluded.append(excluded_benefit_ids)
            return {
                "monthly_total_krw": 500, "annual_total_krw": 0,
                "performance_met": True, "category_breakdown": [],
                "benefit_details": [], "annual_breakdown": [], "warnings": [],
            }

    monkeypatch.setattr("app.services.card_service.BenefitCalculator", CapturingCalculator)
    cards = [_make_card_data("c2", "CardB", 500)]
    svc = CardRecommendService(FakeRepo(cards))
    await svc.calculate_benefits(cards, 300000, {"Coffee": 50000})

    assert received_excluded[0] is None


# ═════════════════════════════════════════════
# 6. 통합: 실제 BenefitCalculator + enrich + 영수증 E2E
# ═════════════════════════════════════════════

class TestEndToEndBenefitReceipt:
    """
    실제 BenefitCalculator → _enrich_benefit_details → build_recommended_cards
    파이프라인 전체를 검증합니다.
    """

    def test_full_pipeline_no_exclusion(self, monkeypatch):
        """제외 없는 전체 파이프라인 — 3개 혜택 모두 benefit_receipt에 포함"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET)
        enriched = _enrich_benefit_details(result["benefit_details"], RAW_BENEFITS_CONTENT)

        ranked_card = {
            **result,
            "card_name": CARD_MULTI["card_meta"]["card_name"],
            "card_company": CARD_MULTI["card_meta"]["card_company"],
            "card_id": CARD_MULTI["card_meta"]["card_id"],
            "annual_fee": CARD_MULTI["card_meta"]["annual_fee"],
            "minimum_performance": CARD_MULTI["card_meta"]["minimum_performance"],
            "expected_monthly_benefit": result["monthly_total_krw"],
            "expected_yearly_benefit": result["monthly_total_krw"] * 12,
            "benefit_details": enriched,
        }

        monkeypatch.setattr(
            "app.services.explain_service.ExplainService.__init__",
            lambda self, llm: setattr(self, "_resilient_invoke", None),
        )
        svc = ExplainService(llm=None)  # type: ignore
        cards = svc.build_recommended_cards([ranked_card], explanation="설명")

        receipt = cards[0]["benefit_receipt"]
        assert len(receipt) == 3

        by_id = {r["benefit_id"]: r for r in receipt}
        assert by_id["b001"]["amount_krw"] == 5000
        assert by_id["b001"]["content"] == "카페 10% 할인 (월 최대 5,000원)"
        assert by_id["b002"]["amount_krw"] == 5000
        assert by_id["b002"]["content"] == "배달앱 5% 할인"
        assert by_id["b003"]["amount_krw"] == 2400
        assert by_id["b003"]["content"] == "국내 일반 쇼핑 3% 할인"

    def test_full_pipeline_with_exclusion(self, monkeypatch):
        """b001 제외 시 benefit_receipt에 b001이 없어야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids={"b001"})
        enriched = _enrich_benefit_details(result["benefit_details"], RAW_BENEFITS_CONTENT)

        ranked_card = {
            **result,
            "card_name": "멀티혜택카드",
            "card_company": "테스트카드사",
            "card_id": "test_multi",
            "annual_fee": 15000,
            "minimum_performance": 300000,
            "expected_monthly_benefit": result["monthly_total_krw"],
            "expected_yearly_benefit": result["monthly_total_krw"] * 12,
            "benefit_details": enriched,
        }

        monkeypatch.setattr(
            "app.services.explain_service.ExplainService.__init__",
            lambda self, llm: setattr(self, "_resilient_invoke", None),
        )
        svc = ExplainService(llm=None)  # type: ignore
        cards = svc.build_recommended_cards([ranked_card], explanation="설명")

        receipt_ids = {r["benefit_id"] for r in cards[0]["benefit_receipt"]}
        assert "b001" not in receipt_ids
        assert "b002" in receipt_ids
        assert "b003" in receipt_ids

    def test_monthly_limit_reflected_in_receipt(self, monkeypatch):
        """monthly_limit 5000 적용 후 b001 amount_krw가 정확히 5000이어야 한다"""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(
            {"Coffee": {"total": 200000, "cafe": "100%"},  # 200000*0.1=20000 > 한도5000
             "Food": 0, "Shopping": 0},
            user_total_spend=200000,
        )
        detail_map = {d["benefit_id"]: d for d in result["benefit_details"]}
        assert detail_map["b001"]["amount_krw"] == 5000  # 한도 적용

    def test_performance_not_met_returns_empty_receipt(self):
        """전월 실적 미달 카드는 benefit_details가 비어야 한다"""
        card_high_perf = {
            "card_meta": {
                "card_id": "high_perf",
                "card_name": "하이퍼프카드",
                "card_company": "테스트",
                "annual_fee": 0,
                "minimum_performance": 1_000_000,  # 100만원 실적 필요
                "performance_excluded_categories": [],
            },
            "benefit_groups": [],
            "benefits": [
                _make_benefit("bp001", "Coffee", "cafe", 0.10),
            ],
        }
        calc = BenefitCalculator(card_high_perf)
        result = calc.calculate({"Coffee": 50000}, user_total_spend=50000)
        assert result["benefit_details"] == []
        assert result["monthly_total_krw"] == 0
