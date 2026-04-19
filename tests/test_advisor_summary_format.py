"""QUERIES_DETAILS 항목의 ## 요약 섹션이 불릿 포인트를 지시해야 한다.

reviews 는 제외 (전반적 평가 prose 유지).
credit_fees / international_fees / late_payment / revolving 의 ## 요약 섹션은
'2~3문장 prose, 번호·불릿 금지' 대신 '4~6개 불릿 포인트(•)' 방식으로
지시해야 가독성이 개선된다.

검증 기준
- 각 프롬프트에 불릿 포인트 지시 키워드(불릿 포인트) 가 포함될 것
- 가독성을 해치는 'prose' 또는 '번호·불릿 금지' 지침이 ## 요약 섹션에 없을 것
"""
from __future__ import annotations

import pytest

from app.services.advise_service import QUERIES_DETAILS

DETAIL_KEYS = ["credit_fees", "international_fees", "late_payment", "revolving"]


class TestSummaryUsesBulletPoints:
    @pytest.mark.parametrize("key", DETAIL_KEYS)
    def test_summary_section_instructs_bullet_points(self, key: str) -> None:
        prompt = QUERIES_DETAILS[key]
        # ## 요약 섹션 추출 (## 상세 내용 이전까지)
        summary_section = prompt.split("## 상세 내용")[0]
        assert "불릿 포인트" in summary_section, (
            f"{key}: ## 요약 섹션에 '불릿 포인트' 지시가 없음"
        )

    @pytest.mark.parametrize("key", DETAIL_KEYS)
    def test_summary_section_no_prose_prohibition(self, key: str) -> None:
        prompt = QUERIES_DETAILS[key]
        summary_section = prompt.split("## 상세 내용")[0]
        assert "번호·불릿 금지" not in summary_section, (
            f"{key}: ## 요약 섹션에 '번호·불릿 금지' 지침이 남아 있음"
        )
