"""EXPLAIN_PROMPT / COMPARE_PROMPT 에 bold(**) 문법 금지 지침 회귀 방지.

LLM 이 카드명을 **카드명** 형태로 강조하면 remark-gfm 의 closing delimiter
규칙(특히 '+**' 패턴)으로 인해 파싱이 실패, ** 가 리터럴로 화면에 노출된다.
두 프롬프트 모두 ** / * 강조 문법 금지를 명시해야 한다.
"""
from __future__ import annotations

import pytest

from app.prompts import EXPLAIN_PROMPT, COMPARE_PROMPT


CURATION_PROMPTS = {
    "EXPLAIN_PROMPT": EXPLAIN_PROMPT,
    "COMPARE_PROMPT": COMPARE_PROMPT,
}

BOLD_PROHIBITION_MARKER = "**bold**"


class TestBoldSyntaxProhibited:
    @pytest.mark.parametrize("name,prompt", list(CURATION_PROMPTS.items()))
    def test_bold_syntax_prohibition_present(self, name: str, prompt: str) -> None:
        assert BOLD_PROHIBITION_MARKER in prompt, (
            f"{name} 에 **bold** 강조 문법 금지 지침이 없음 — 프롬프트에 추가 필요"
        )
