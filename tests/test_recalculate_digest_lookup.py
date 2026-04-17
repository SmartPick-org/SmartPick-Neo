"""
Regression: /cards/recalculate 가 1순위 변경 시 digest 를 조회할 때
DigestRepository.get_digest 에 전달하는 인자 형태가 올바른지 검증한다.

배경:
- DigestRepository.get_digest 는 CardData 형태를 기대한다.
  card_meta = card.get("card_meta", {})
  card_slug = card_meta.get("card_slug", "")
  card_name = card_meta.get("card_name", "알 수 없음")

- 그러나 구버전 recalculate 핸들러는 flat dict 를 넘겨
  `{"card_slug": ..., "card_name": ...}` 로 호출했고,
  결과적으로 card_meta 가 빈 dict 가 되어
  "알 수 없음 (slug=)" 로 digest lookup 실패 → 더미 텍스트 반환 →
  LLM 이 카드 정보를 모르는 상태로 큐레이션 재생성.

이 테스트는 `card_meta` 래퍼로 감싼 dict 가 전달되는지를 확인한다.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.card import recalculate_benefits
from app.schemas.recommend import (
    BenefitTraceItem,
    CategoryBreakdown,
    RecalculateRequest,
    RecommendCard,
)


def _stub_explain_service(explain_return: str) -> MagicMock:
    """ExplainService 의 생성자 의존(LLM 래퍼)을 건너뛴 가짜 인스턴스 팩토리."""
    instance = MagicMock()
    instance.explain = AsyncMock(return_value=explain_return)
    factory = MagicMock(return_value=instance)
    return factory


def _trace(benefit_id: str, category: str, amount: int) -> BenefitTraceItem:
    return BenefitTraceItem(
        benefit_id=benefit_id,
        content=f"{benefit_id} 혜택",
        category=category,
        sub_category=None,
        applied_budget=amount * 10,
        yielded_discount=amount,
        user_choice=True,
    )


def _card(
    card_id: str,
    card_name: str,
    monthly_benefit: int,
    traces: list[BenefitTraceItem],
) -> RecommendCard:
    breakdown: dict[str, int] = {}
    for t in traces:
        breakdown[t.category] = breakdown.get(t.category, 0) + t.yielded_discount

    return RecommendCard(
        card_name=card_name,
        card_company="테스트카드사",
        card_id=card_id,
        annual_fee=10000,
        minimum_performance=300000,
        expected_monthly_benefit=monthly_benefit,
        expected_yearly_benefit=monthly_benefit * 12,
        category_breakdown=[
            CategoryBreakdown(category=c, monthly_discount_krw=v, discount_info={}, warnings=[])
            for c, v in breakdown.items()
        ],
        applied_benefits_trace=traces,
        explanation="기존 1순위 카드 설명",
    )


def _build_payload_that_flips_ranking() -> RecalculateRequest:
    """
    card_A 가 초기 1순위지만, A의 대형 혜택을 제외하면 card_B 가 1순위가 되도록 구성.
    """
    # card_A: big benefit (80000) + small benefit (5000) = 85000
    a_traces = [
        _trace("a_big", "Food", 80000),
        _trace("a_small", "Coffee", 5000),
    ]
    # card_B: 70000 — a_big 제외 시 85000 - 80000 = 5000 보다 높아 1순위로 올라감
    b_traces = [
        _trace("b_main", "Food", 70000),
    ]

    return RecalculateRequest(
        total_budget=500000,
        category_spending={"Food": 300000, "Coffee": 50000},
        recommended_cards=[
            _card("card_A", "A카드", 85000, a_traces),
            _card("card_B", "B카드", 70000, b_traces),
        ],
        excluded_benefit_ids=["a_big"],  # A의 대형 혜택 제외 → B가 1순위
    )


@pytest.mark.asyncio
async def test_recalculate_passes_card_meta_wrapped_dict_to_get_digest():
    """
    1순위 카드가 변경될 때 DigestRepository.get_digest 에 넘기는 인자는
    `{"card_meta": {"card_slug": ..., "card_name": ...}}` 형태여야 한다.

    flat dict `{"card_slug": ..., "card_name": ...}` 를 넘기면
    digest_repo 내부에서 card_meta 를 꺼내지 못해 조회가 빈 값으로 실패한다.
    """
    payload = _build_payload_that_flips_ranking()

    captured: dict[str, Any] = {}

    async def fake_get_digest(self, card: dict) -> str:
        captured["card"] = card
        return "# B카드\n진짜 digest 내용"

    explain_factory = _stub_explain_service("새 1순위 B카드에 대한 큐레이션")

    with patch(
        "app.api.card.DigestRepository.get_digest",
        new=fake_get_digest,
    ), patch(
        "app.api.card.ExplainService",
        new=explain_factory,
    ), patch(
        "app.api.card.get_llm",
        return_value=object(),
    ):
        result = await recalculate_benefits(payload)

    # 1순위가 바뀌었으므로 digest 조회가 일어나야 한다.
    assert "card" in captured, "get_digest 가 호출되지 않았습니다 (1순위 변경 조건 확인 필요)"

    passed = captured["card"]

    # 핵심 검증: card_meta 래퍼로 감싸져 있어야 한다.
    assert "card_meta" in passed, (
        f"get_digest 에 card_meta 래퍼 없이 flat dict 가 전달됨: {passed}. "
        "DigestRepository 는 card_meta 하위의 card_slug/card_name 을 읽는다."
    )

    meta = passed["card_meta"]
    assert meta.get("card_slug"), "card_meta.card_slug 가 비어 있음"
    assert meta.get("card_name"), "card_meta.card_name 이 비어 있음"
    assert meta["card_slug"] == "card_B"
    assert meta["card_name"] == "B카드"

    # 부가 검증: digest 가 제대로 로드되었으니 explanation 도 채워져야 한다.
    assert result.explanation == "새 1순위 B카드에 대한 큐레이션"


@pytest.mark.asyncio
async def test_recalculate_no_rank_change_does_not_call_get_digest():
    """1순위가 그대로면 digest 조회/큐레이션 재생성이 일어나지 않고 explanation 은 빈 문자열."""
    # A(85000) 가 유지되는 케이스 — 작은 혜택만 제외
    a_traces = [
        _trace("a_big", "Food", 80000),
        _trace("a_small", "Coffee", 5000),
    ]
    b_traces = [_trace("b_main", "Food", 70000)]

    payload = RecalculateRequest(
        total_budget=500000,
        category_spending={"Food": 300000, "Coffee": 50000},
        recommended_cards=[
            _card("card_A", "A카드", 85000, a_traces),
            _card("card_B", "B카드", 70000, b_traces),
        ],
        excluded_benefit_ids=["a_small"],  # A 합계 80000 > B 70000, 순위 유지
    )

    call_count = {"n": 0}

    async def fake_get_digest(self, card: dict) -> str:
        call_count["n"] += 1
        return "should not be called"

    explain_factory = _stub_explain_service("should not be called either")

    with patch(
        "app.api.card.DigestRepository.get_digest",
        new=fake_get_digest,
    ), patch(
        "app.api.card.ExplainService",
        new=explain_factory,
    ), patch(
        "app.api.card.get_llm",
        return_value=object(),
    ):
        result = await recalculate_benefits(payload)

    assert call_count["n"] == 0, "1순위가 유지되면 digest 를 다시 조회하지 않아야 한다"
    explain_factory.return_value.explain.assert_not_called()
    assert result.explanation == ""
