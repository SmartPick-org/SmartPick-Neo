"""
v4 스키마 기반 BenefitCalculator / CardRecommendService 회귀 테스트.

v3 → v4 이관 후 달라진 계약:
- 계산기 입력 필드: `calc_method` → `calc_type: "PERCENTAGE"`, `rate` → `benefit_rate`,
  `monthly_limit` → `monthly_benefit_limit`, `ui_warnings` → `conditional_metadata.warnings`
- 계산기 출력 필드: `benefit_details` → `applied_benefits_trace`,
  항목 필드 `amount_krw` → `yielded_discount`, 슬림화로 `category`/`sub_category` 제외
- 카드 메타: `annual_fee` → `annual_fee_domestic`
- `_enrich_benefit_details`: content가 없으면 `[카테고리] N% 혜택` 형태로 fallback 생성
- RecommendCard에서 `benefit_receipt`/`BenefitReceiptItem` 삭제 — applied_benefits_trace로 일원화
"""

import pytest
from app.tools.Calc_tool import BenefitCalculator
from app.services.card_service import CardRecommendService, _enrich_benefit_details


# ─────────────────────────────────────────────
# 공통 픽스처 (v4 스키마)
# ─────────────────────────────────────────────

def _make_benefit(benefit_id: str, category: str, sub_category: str,
                  rate: float, monthly_limit: float | None = None,
                  warnings: list[str] | None = None,
                  content: str | None = None) -> dict:
    return {
        "benefit_id": benefit_id,
        "group_id": None,
        "category": category,
        "sub_category": sub_category,
        "content": content or "",
        "reward_type": "DIRECT_FINANCIAL",
        "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
        "calculation_rule": {
            "calc_type": "PERCENTAGE",
            "benefit_rate": rate,
            "fallback_rate": 0.0,
            "monthly_benefit_limit": monthly_limit,
            "annual_benefit_limit": None,
        },
        "transaction_conditions": {},
        "tier_conditions": [],
        "conditional_metadata": {
            "warnings": warnings or [],
            "excludes_from_performance": False,
        },
    }


CARD_MULTI = {
    "card_meta": {
        "card_id": "test_multi",
        "card_name": "멀티혜택카드",
        "card_company": "테스트카드사",
        "annual_fee_domestic": 15000,
        "minimum_performance": 0,
        "performance_excluded_categories": [],
    },
    "benefit_groups": [],
    "benefits": [
        _make_benefit("b001", "Coffee",   "cafe",     0.10, monthly_limit=5000),
        _make_benefit("b002", "Food",     "delivery", 0.05),
        _make_benefit("b003", "Shopping", "general",  0.03,
                      warnings=["전월 실적 30만원 이상 시 적용"]),
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
# 1. BenefitCalculator — applied_benefits_trace 구조
# ═════════════════════════════════════════════

class TestBenefitTrace:
    def setup_method(self):
        self.calc = BenefitCalculator(CARD_MULTI)
        self.result = self.calc.calculate(SPENDING, user_total_spend=TOTAL_BUDGET)

    def test_trace_present(self):
        """applied_benefits_trace 키가 결과에 존재해야 한다."""
        assert "applied_benefits_trace" in self.result

    def test_trace_only_positive_amounts(self):
        """yielded_discount > 0 인 항목만 포함되어야 한다."""
        for item in self.result["applied_benefits_trace"]:
            assert item["yielded_discount"] > 0, f"{item['benefit_id']}의 yielded_discount가 0인데 포함됨"

    def test_trace_has_required_fields(self):
        """각 trace 항목에 필수 필드가 있어야 한다 (v4 슬림 구조)."""
        required = {"benefit_id", "content", "applied_budget", "yielded_discount", "warnings"}
        for item in self.result["applied_benefits_trace"]:
            assert required <= item.keys(), f"누락 필드: {required - item.keys()}"

    def test_trace_amounts_correct(self):
        """계산 금액이 예상값과 일치해야 한다."""
        amount_map = {d["benefit_id"]: d["yielded_discount"] for d in self.result["applied_benefits_trace"]}
        assert amount_map["b001"] == 5000   # 한도 5000 적용
        assert amount_map["b002"] == 5000   # 100000 * 5%
        assert amount_map["b003"] == 2400   # 80000  * 3%

    def test_trace_warnings_propagated(self):
        """conditional_metadata.warnings가 trace의 warnings에 전파되어야 한다."""
        detail_map = {d["benefit_id"]: d for d in self.result["applied_benefits_trace"]}
        assert "전월 실적 30만원 이상 시 적용" in detail_map["b003"]["warnings"]

    def test_monthly_total_matches_trace_sum(self):
        """monthly_total_krw = sum of yielded_discount."""
        total = sum(item["yielded_discount"] for item in self.result["applied_benefits_trace"])
        assert self.result["monthly_total_krw"] == total


# ═════════════════════════════════════════════
# 2. BenefitCalculator — excluded_benefit_ids
# ═════════════════════════════════════════════

class TestExcludedBenefitIds:
    def test_exclude_one_benefit(self):
        """b001을 제외하면 trace에 b001이 없어야 한다."""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, user_total_spend=TOTAL_BUDGET,
                                excluded_benefit_ids={"b001"})
        ids = {d["benefit_id"] for d in result["applied_benefits_trace"]}
        assert "b001" not in ids
        assert "b002" in ids
        assert "b003" in ids

    def test_exclude_one_reduces_monthly_total(self):
        """b001(5000) 제외 시 월 합계가 5000 감소해야 한다."""
        calc1 = BenefitCalculator(CARD_MULTI)
        calc2 = BenefitCalculator(CARD_MULTI)
        base = calc1.calculate(SPENDING, TOTAL_BUDGET)
        excl = calc2.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids={"b001"})
        assert excl["monthly_total_krw"] == base["monthly_total_krw"] - 5000

    def test_exclude_multiple_benefits(self):
        """b001, b002 제외 시 b003만 남아야 한다."""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET,
                                excluded_benefit_ids={"b001", "b002"})
        ids = {d["benefit_id"] for d in result["applied_benefits_trace"]}
        assert ids == {"b003"}

    def test_exclude_all_benefits_zero(self):
        """모든 benefit 제외 시 월 합계 0원이어야 한다."""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET,
                                excluded_benefit_ids={"b001", "b002", "b003"})
        assert result["monthly_total_krw"] == 0
        assert result["applied_benefits_trace"] == []

    def test_exclude_none_is_same_as_default(self):
        """excluded_benefit_ids=None은 제외 없음과 동일해야 한다."""
        calc1 = BenefitCalculator(CARD_MULTI)
        calc2 = BenefitCalculator(CARD_MULTI)
        r1 = calc1.calculate(SPENDING, TOTAL_BUDGET)
        r2 = calc2.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids=None)
        assert r1["monthly_total_krw"] == r2["monthly_total_krw"]

    def test_exclude_nonexistent_id_no_effect(self):
        """존재하지 않는 ID 제외는 결과에 영향 없어야 한다."""
        calc1 = BenefitCalculator(CARD_MULTI)
        calc2 = BenefitCalculator(CARD_MULTI)
        base = calc1.calculate(SPENDING, TOTAL_BUDGET)
        result = calc2.calculate(SPENDING, TOTAL_BUDGET,
                                 excluded_benefit_ids={"not_exist_id"})
        assert result["monthly_total_krw"] == base["monthly_total_krw"]


# ═════════════════════════════════════════════
# 3. _enrich_benefit_details — content join & fallback 로직
# ═════════════════════════════════════════════

class TestEnrichBenefitDetails:
    def _make_trace(self, benefit_id: str, amount: int = 1000) -> dict:
        """Calc_tool의 slim trace item 모양을 흉내 낸 항목."""
        return {
            "benefit_id": benefit_id,
            "category": "Coffee",
            "sub_category": "cafe",
            "yielded_discount": amount,
            "warnings": [],
            "calculation_rule": {"benefit_rate": 0.10},
        }

    def test_content_from_raw_benefits(self):
        """raw_benefits에 content가 있으면 그대로 사용."""
        details = [self._make_trace("b001"), self._make_trace("b002")]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        by_id = {e["benefit_id"]: e for e in enriched}
        assert by_id["b001"]["content"] == "카페 10% 할인 (월 최대 5,000원)"
        assert by_id["b002"]["content"] == "배달앱 5% 할인"

    def test_raw_benefit_without_content_triggers_fallback_generator(self):
        """raw_benefits에 id는 있지만 content가 비어있으면 `_create_fallback_content`가 동작.
        `[카테고리] 서브 N% 혜택` 형태의 문자열이 생성된다."""
        details = [self._make_trace("b001")]
        # v4 raw에 content가 없는 상태
        v4_raw_no_content = [{
            "benefit_id": "b001",
            "category": "Coffee",
            "sub_category": "cafe",
            "calculation_rule": {"benefit_rate": 0.10},
        }]
        enriched = _enrich_benefit_details(details, v4_raw_no_content)
        content = enriched[0]["content"]
        assert "Coffee" in content  # 카테고리
        assert "cafe" in content    # 서브카테고리
        assert "10%" in content     # rate

    def test_id_not_in_raw_benefits_returns_default_label(self):
        """raw_benefits에 id 자체가 없으면 기본 '맞춤 혜택' 문자열이 들어간다."""
        details = [self._make_trace("unknown_id")]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        assert enriched[0]["content"] == "맞춤 혜택"

    def test_original_fields_preserved(self):
        """기존 필드는 유지되어야 한다."""
        details = [self._make_trace("b001", amount=1000)]
        enriched = _enrich_benefit_details(details, RAW_BENEFITS_CONTENT)
        assert enriched[0]["yielded_discount"] == 1000
        assert enriched[0]["category"] == "Coffee"

    def test_empty_raw_benefits_uses_fallback_for_all(self):
        """raw_benefits가 빈 리스트여도 fallback으로 각 항목에 content가 채워진다."""
        details = [self._make_trace("b001"), self._make_trace("b002")]
        enriched = _enrich_benefit_details(details, [])
        for e in enriched:
            # fallback content가 생성되어야 함 (빈 문자열 아님)
            assert e["content"] != ""

    def test_empty_details(self):
        """benefit_details가 빈 리스트이면 빈 리스트를 반환."""
        result = _enrich_benefit_details([], RAW_BENEFITS_CONTENT)
        assert result == []

    def test_uses_legacy_content_when_v4_missing(self):
        """v4 raw에 content가 없으면 legacy 카드 benefits의 (category, sub_category) 매칭으로 보강."""
        details = [self._make_trace("b001")]
        # v4 raw는 content 없음. legacy에서 매칭.
        v4_raw_no_content = [{"benefit_id": "b001", "category": "Coffee", "sub_category": "cafe"}]
        legacy = [{"category": "Coffee", "sub_category": "cafe", "content": "레거시 카페 할인"}]
        enriched = _enrich_benefit_details(details, v4_raw_no_content, legacy_benefits=legacy)
        assert enriched[0]["content"] == "레거시 카페 할인"


# ═════════════════════════════════════════════
# 4. (구) benefit_receipt 테스트 — 스키마에서 필드가 제거되면서 함께 삭제됨
#    RecommendCard에 benefit_receipt / BenefitReceiptItem 클래스가 더 이상 존재하지 않습니다.
#    build_recommended_cards의 출력은 applied_benefits_trace로 대체되었습니다.
# ═════════════════════════════════════════════


# ═════════════════════════════════════════════
# 5. CardRecommendService — top_n & excluded_benefit_ids 전달
# ═════════════════════════════════════════════

class FakeRepo:
    def __init__(self, cards):
        self._cards = cards
    def list_cards(self):
        return self._cards


def _make_card_data(card_id: str, card_name: str, monthly_benefit: int) -> dict:
    return {
        "card_meta": {
            "card_id": card_id,
            "card_name": card_name,
            "card_company": "테스트카드사",
            "annual_fee_domestic": 0,
            "minimum_performance": 0,
        },
        "_card_categories": {"Coffee"},
        "benefits": [],
        "benefit_groups": [],
        "_monthly_benefit": monthly_benefit,
    }


@pytest.mark.asyncio
async def test_rank_top_respects_top_n():
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
    """calculate_benefits가 excluded_benefit_ids를 BenefitCalculator에 올바르게 전달해야 한다."""
    received_excluded = []

    class CapturingCalculator:
        def __init__(self, card):
            self.card = card
        def calculate(self, spending, user_total_spend=None, excluded_benefit_ids=None):
            received_excluded.append(excluded_benefit_ids)
            return {
                "monthly_total_krw": 1000, "annual_total_krw": 12000,
                "performance_met": True, "category_breakdown": [],
                "applied_benefits_trace": [], "warnings": [],
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
    """excluded_benefit_ids=None 일 때 None이 그대로 전달."""
    received_excluded = []

    class CapturingCalculator:
        def __init__(self, card):
            pass
        def calculate(self, spending, user_total_spend=None, excluded_benefit_ids=None):
            received_excluded.append(excluded_benefit_ids)
            return {
                "monthly_total_krw": 500, "annual_total_krw": 6000,
                "performance_met": True, "category_breakdown": [],
                "applied_benefits_trace": [], "warnings": [],
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
    """실제 BenefitCalculator → _enrich_benefit_details → build_recommended_cards 파이프라인."""

    def test_full_pipeline_no_exclusion(self):
        """
        제외 없는 전체 파이프라인:
        BenefitCalculator.calculate() → _enrich_benefit_details() 결과에
        3개 혜택의 yielded_discount와 enrich된 content가 모두 담겨야 한다.
        (v4 스키마 이관 후 benefit_receipt 필드는 제거되어 applied_benefits_trace로 검증)
        """
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET)
        enriched = _enrich_benefit_details(
            result["applied_benefits_trace"], RAW_BENEFITS_CONTENT
        )

        assert len(enriched) == 3

        by_id = {r["benefit_id"]: r for r in enriched}
        assert by_id["b001"]["yielded_discount"] == 5000
        assert by_id["b001"]["content"] == "카페 10% 할인 (월 최대 5,000원)"
        assert by_id["b002"]["yielded_discount"] == 5000
        assert by_id["b002"]["content"] == "배달앱 5% 할인"
        assert by_id["b003"]["yielded_discount"] == 2400
        assert by_id["b003"]["content"] == "국내 일반 쇼핑 3% 할인"

    def test_full_pipeline_with_exclusion(self):
        """b001 제외 시 trace에 b001이 없어야 한다."""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(SPENDING, TOTAL_BUDGET, excluded_benefit_ids={"b001"})
        trace_ids = {r["benefit_id"] for r in result["applied_benefits_trace"]}
        assert "b001" not in trace_ids
        assert "b002" in trace_ids
        assert "b003" in trace_ids

    def test_monthly_limit_reflected_in_trace(self):
        """monthly_benefit_limit 5000 적용 후 b001 yielded_discount가 정확히 5000."""
        calc = BenefitCalculator(CARD_MULTI)
        result = calc.calculate(
            {"Coffee": {"total": 200000, "cafe": "100%"},  # 200000*0.1=20000 > 한도5000
             "Food": 0, "Shopping": 0},
            user_total_spend=200000,
        )
        detail_map = {d["benefit_id"]: d for d in result["applied_benefits_trace"]}
        assert detail_map["b001"]["yielded_discount"] == 5000  # 한도 적용

    def test_performance_not_met_returns_empty_trace(self):
        """전월 실적 미달 카드는 applied_benefits_trace가 비어야 한다."""
        card_high_perf = {
            "card_meta": {
                "card_id": "high_perf",
                "card_name": "하이퍼프카드",
                "card_company": "테스트",
                "annual_fee_domestic": 0,
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
        assert result["applied_benefits_trace"] == []
        assert result["monthly_total_krw"] == 0
