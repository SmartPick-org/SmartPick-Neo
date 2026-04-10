"""
EXPLAIN_PROMPT 빠른 테스트 스크립트
실행: python scripts/test_explain_prompt.py
"""
import asyncio
from langchain_core.messages import SystemMessage
from app.core.config import get_llm
from app.prompts import EXPLAIN_PROMPT

# ── 테스트 데이터 (원하는 값으로 자유롭게 수정) ─────────────────────────────

USER_SPENDING = """
월 총 소비: 600,000원
- 배달/외식: 월 200,000원
- 온라인쇼핑: 월 150,000원
- OTT/구독: 월 80,000원
- 교통: 월 80,000원
- 카페: 월 90,000원
""".strip()

CARD_DIGEST = """
카드명: 현대카드 Z family
카드사: 현대카드
연회비: 30,000원

주요 혜택:
- 배달의민족/요기요: 월 최대 5,000원 할인 (건당 5%)
- 쿠팡/네이버쇼핑 등 온라인 쇼핑: 월 최대 5,000원 할인 (건당 3%)
- 넷플릭스/유튜브프리미엄 등 구독 서비스: 월 최대 3,000원 할인 (건당 10%)
- 스타벅스/이디야 등 카페: 월 최대 3,000원 할인 (건당 5%)
전월 실적 조건: 30만원 이상
""".strip()

CALC_SUMMARY = ""  # V4에서는 사용 안 함

# ────────────────────────────────────────────────────────────────────────────

async def main():
    llm = get_llm()
    prompt = EXPLAIN_PROMPT.format(
        user_spending=USER_SPENDING,
        card_digest=CARD_DIGEST,
        calc_summary=CALC_SUMMARY,
    )

    print("=" * 60)
    print("▶ 프롬프트 미리보기 (첫 300자)")
    print(prompt[:300])
    print("=" * 60)
    print("▶ LLM 응답 생성 중...\n")

    response = await llm.ainvoke([SystemMessage(content=prompt)])
    print(response.content)
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
