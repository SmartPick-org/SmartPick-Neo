"""Advisor 프롬프트 포맷 회귀 방지.

프론트는 경량 MarkdownText 렌더러를 사용하므로 아래 HTML 태그는
LLM이 생성하지 않도록 프롬프트에서 언급·예시가 제거되어 있어야 한다.

- `<small>` / `<small style=...>` HTML 태그

반대로 아래는 반드시 유지되어야 한다.

- `## 요약` / `## 상세 내용` 헤딩 (QUERIES_DETAILS 4개 항목)
- `> 참고:` 블록인용 disclaimer (모든 프롬프트)

파이프 테이블은 프론트에서 `react-markdown + remark-gfm` 으로 렌더하기로 하여
프롬프트에서 허용한다 (이전에는 제거를 강제하던 테스트가 있었으나 철회).
"""
from __future__ import annotations

import pytest

from app.services.advise_service import (
    QUERIES,
    QUERIES_DETAILS,
)


class TestBrokenFormatsRemoved:
    """경량 렌더러에서 깨지는 포맷이 프롬프트에 남아 있으면 안 된다."""

    @pytest.mark.parametrize("key", list(QUERIES.keys()))
    def test_no_small_html_tag(self, key: str) -> None:
        prompt = QUERIES[key]
        assert "<small" not in prompt.lower(), (
            f"{key} 프롬프트에 <small> 태그가 남아 있음"
        )

    @pytest.mark.parametrize("key", list(QUERIES.keys()))
    def test_strikethrough_prohibited_in_prompt(self, key: str) -> None:
        """_DISCLAIMER를 통해 모든 쿼리 프롬프트에 취소선(~~) 사용 금지 지침이 포함되어야 한다.
        remark-gfm이 ~~text~~를 취소선으로 렌더링하므로 LLM이 절대 사용하지 않아야 한다."""
        prompt = QUERIES[key]
        assert "~~취소선~~" in prompt, (
            f"{key} 프롬프트에 ~~취소선~~ 사용 금지 지침이 없음 — "
            "_DISCLAIMER에 추가 필요"
        )


class TestRetainedStructure:
    """유지되어야 하는 포맷이 실수로 빠지지 않도록 고정."""

    @pytest.mark.parametrize("key", list(QUERIES_DETAILS.keys()))
    def test_details_keeps_summary_heading(self, key: str) -> None:
        assert "## 요약" in QUERIES_DETAILS[key]

    @pytest.mark.parametrize("key", list(QUERIES_DETAILS.keys()))
    def test_details_keeps_detail_heading(self, key: str) -> None:
        assert "## 상세 내용" in QUERIES_DETAILS[key]

    @pytest.mark.parametrize("key", list(QUERIES.keys()))
    def test_disclaimer_uses_blockquote(self, key: str) -> None:
        prompt = QUERIES[key]
        assert "> 참고:" in prompt, (
            f"{key} 프롬프트에 `> 참고:` 블록인용 disclaimer가 없음"
        )
