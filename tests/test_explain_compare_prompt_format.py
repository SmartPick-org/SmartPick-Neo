"""EXPLAIN_PROMPT / COMPARE_PROMPT 취소선 금지 회귀 방지.

remark-gfm 이 ~~text~~ 를 취소선으로 렌더링하기 때문에,
LLM 이 큐레이션 텍스트(explain/compare)에 취소선 마크다운을 사용하면
프론트 화면에 글자에 줄이 그어진 채로 노출된다.
두 프롬프트 모두 '~~취소선~~ 문법 사용 금지' 지침을 명시해야 한다.
"""
from __future__ import annotations

import pytest

from app.prompts import EXPLAIN_PROMPT, COMPARE_PROMPT


class TestStrikethroughProhibited:
    """EXPLAIN_PROMPT 와 COMPARE_PROMPT 에 취소선 금지 지침이 있어야 한다."""

    def test_explain_prompt_prohibits_strikethrough(self) -> None:
        assert "~~" in EXPLAIN_PROMPT, (
            "EXPLAIN_PROMPT 에 ~~취소선~~ 금지 지침이 없음 — 프롬프트에 추가 필요"
        )

    def test_compare_prompt_prohibits_strikethrough(self) -> None:
        assert "~~" in COMPARE_PROMPT, (
            "COMPARE_PROMPT 에 ~~취소선~~ 금지 지침이 없음 — 프롬프트에 추가 필요"
        )
