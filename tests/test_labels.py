"""CategoryEnum / SubCategoryEnum → 한글 라벨 매핑 모듈 테스트.

`app/schemas/labels.py` 는 두 가지를 보장해야 한다.
1. `CategoryEnum` 과 `SubCategoryEnum` 의 모든 값에 대해 한글 라벨이 정의되어 있다.
2. `category_label_ko` / `sub_category_label_ko` 헬퍼는 매핑에 없는 값에 대해
   원본 문자열을 그대로 돌려준다 (fail-open).
"""
from __future__ import annotations

import pytest

from app.schemas.enums import CategoryEnum, SubCategoryEnum
from app.schemas.labels import (
    CATEGORY_LABELS_KO,
    SUB_CATEGORY_LABELS_KO,
    category_label_ko,
    sub_category_label_ko,
)


class TestCoverage:
    @pytest.mark.parametrize("value", [e.value for e in CategoryEnum])
    def test_every_category_has_korean_label(self, value: str) -> None:
        assert value in CATEGORY_LABELS_KO, f"CategoryEnum '{value}'에 대한 한글 라벨이 없음"
        assert CATEGORY_LABELS_KO[value], f"CategoryEnum '{value}' 라벨이 빈 문자열"

    @pytest.mark.parametrize("value", [e.value for e in SubCategoryEnum])
    def test_every_sub_category_has_korean_label(self, value: str) -> None:
        assert value in SUB_CATEGORY_LABELS_KO, f"SubCategoryEnum '{value}'에 대한 한글 라벨이 없음"
        assert SUB_CATEGORY_LABELS_KO[value], f"SubCategoryEnum '{value}' 라벨이 빈 문자열"


class TestKeyExamples:
    """프론트에서 자주 등장하는 대표 라벨이 예상과 일치해야 한다 (회귀 방지)."""

    @pytest.mark.parametrize("value,expected", [
        ("EduHealth", "교육/헬스"),
        ("Coffee", "커피"),
        ("Food", "외식"),
        ("Traffic", "교통"),
        ("Shopping", "쇼핑"),
        ("Cultural", "문화"),
        ("Travel", "여행"),
        ("Life", "생활"),
        ("General", "일반"),
        ("Others", "기타"),
    ])
    def test_category_label(self, value: str, expected: str) -> None:
        assert category_label_ko(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("hospital", "병원"),
        ("cafe", "카페"),
        ("restaurant", "음식점"),
        ("delivery", "배달"),
        ("transit", "대중교통"),
        ("beauty", "뷰티"),
    ])
    def test_sub_category_label(self, value: str, expected: str) -> None:
        assert sub_category_label_ko(value) == expected


class TestFailOpen:
    """매핑에 없는 값은 원본 문자열 그대로 반환해야 한다 (KeyError 금지)."""

    def test_unknown_category_returns_original(self) -> None:
        assert category_label_ko("UnknownCategory") == "UnknownCategory"

    def test_unknown_sub_category_returns_original(self) -> None:
        assert sub_category_label_ko("unknown_sub") == "unknown_sub"

    def test_empty_string_returns_empty_string(self) -> None:
        assert category_label_ko("") == ""
        assert sub_category_label_ko("") == ""
