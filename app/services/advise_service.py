"""
AdvisorAgent: 특정 신용카드에 대한 사용자 질문에 답변하는 에이전트.

LLM이 네이버 블로그 검색 툴을 직접 사용할지 판단합니다.
- 카드 공식 정보(수수료, 혜택 등)는 마크다운만으로 충분
- 후기·신청 방법처럼 외부 정보가 필요한 경우 LLM이 스스로 검색 툴을 호출

지원 query_type:
  - credit_fees       : 할부·신용 수수료
  - international_fees: 해외 사용 수수료
  - reviews           : 실사용자 후기 및 페인포인트
  - how_to_apply      : 온라인 신청 방법 및 발급 조건
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from loguru import logger
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langsmith import traceable

from app.core.config import get_llm
from app.core.database import get_supabase
from app.core.resilience import with_resilience
from app.tools.web_search import (
    search_blog,
    search_web,
    NaverSearchError,
    tavily_search,
    format_results as _format_web_results,
    WebSearchError,
)

# ===========================< Setting >============================

os.environ["LANGSMITH_TRACING_V2"] = "true"
os.environ["LANGSMITH_PROJECT"] = "SmartPick_Advisor"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"

MODEL = "solar-pro2"

QueryType = Literal[
    "credit_fees",
    "international_fees",
    "reviews",
    "how_to_apply",
    "late_payment",
    "revolving",
]


# ===========================< Button Queries (반말) >============================
# UI 버튼 구조:
#   [후기 보기]          → QUERIES_STANDALONE["reviews"]
#   [신청 방법]          → QUERIES_STANDALONE["how_to_apply"]
#   [추가 정보 ▼]        → 하위 버튼 펼침
#     ├ [수수료]         → QUERIES_DETAILS["credit_fees"]
#     ├ [해외 이용]       → QUERIES_DETAILS["international_fees"]
#     ├ [연체 안내]       → QUERIES_DETAILS["late_payment"]
#     └ [리볼빙]         → QUERIES_DETAILS["revolving"]

# --- Standalone buttons (top-level) ---

def _details_prompt(topic: str, summary: str, details: str) -> str:
    """QUERIES_DETAILS 항목용 공통 구조 생성기.
    모든 세부 쿼리는 ## 요약 → ## 상세 내용 → `> 참고:` 블록인용 구조를 공유한다."""
    return (
        f"{topic} 아래 형식으로만 답해줘. "
        "섹션 제목은 반드시 `##` 헤딩으로 출력하고 불릿 포인트로 쓰지 마. "
        "그 외 어떤 추가 블록·※ 참고는 넣지 마. (마지막 `> 참고:` 블록인용 한 줄은 제외)\n\n"
        f"## 요약\n{summary}\n\n"
        f"## 상세 내용\n약관·상품설명서에 없는 항목은 빼줘:\n\n{details}\n\n"
        + _DISCLAIMER
    )


_DISCLAIMER = (
    "답변 전체에서 💡·📌·※ 참고·추가 설명·불확실성 주석·HTML 태그(꺾쇠괄호로 감싼 태그)·인라인 스타일 등 "
    "어떤 추가 블록도 절대 넣지 마. "
    "답변의 진짜 마지막 줄은 반드시 아래 `> 참고:` 블록인용 한 줄이어야 해 — 그 뒤에는 아무것도 오면 안 돼.\n"
    "아래 형식으로 출력해 (실제 값으로 채우고, URL은 반드시 마크다운 링크 [텍스트](URL) 형식으로):\n"
    "> 참고: 실제_출처_명시. "
    "정확한 내용은 [카드사명 공식 홈페이지](실제_URL)나 고객센터(☎ 실제_대표번호)를 통해 확인하세요."
)

QUERIES_STANDALONE: dict[str, str] = {
    "reviews": (
        "이 카드의 실사용자 후기를 검색해서 아래 형식으로만 답해줘. "
        "카드 혜택·장점 설명, 공식 정보 인용, 공식 출처 확인 결과 등은 절대 포함하지 마. "
        "답변은 반드시 아래 세 섹션과 마지막 `> 참고:` 블록인용으로만 구성해야 해 — 그 외 어떤 섹션·블록·추가 인용도 넣지 마.\n\n"
        "## 전반적 평가\n"
        "실사용자들의 전반적인 만족도와 분위기를 2~3문장으로 요약해줘.\n\n"
        "## 주요 불만 및 페인포인트\n"
        "실사용자들이 공통적으로 언급한 불만이나 불편한 점을 불릿 포인트(•)로 정리해줘.\n\n"
        "---\n\n"
        "**참고한 후기 목록**\n"
        "각 후기마다 • 작성 시기 / 작성자 유형(실사용자 or 카드 추천 블로거) / 한 줄 요약 형식으로 나열해줘.\n\n"
        + _DISCLAIMER
    ),
    "how_to_apply": (
        "이 카드 온라인 신청 방법과 발급 조건만 아래 형식으로 정확히 답해줘. "
        "카드 혜택, 연회비, 사용자 후기 등 신청과 무관한 정보는 절대 포함하지 마. "
        "답변은 반드시 아래 세 `##` 헤딩 섹션과 마지막 `> 참고:` 블록인용으로만 구성해 — 각 섹션 제목은 불릿 포인트가 아닌 `##` 헤딩으로 출력하고, 그 외 어떤 추가 블록·※ 참고는 넣지 마.\n\n"
        "## 신청 URL\n"
        "카드사 메인 홈페이지가 아닌 이 카드의 신청 페이지 직접 URL을 web_search로 검색해서 기재해줘. "
        "URL을 찾지 못한 경우 '공식 홈페이지에서 카드명으로 검색 후 신청 가능'이라고 안내해줘.\n\n"
        "## 발급 조건\n"
        "나이·소득·신용등급 등 발급 자격 조건을 불릿 포인트(•)로 나열해줘.\n\n"
        "## 필요 서류\n"
        "신청 시 필요한 서류 목록을 불릿 포인트(•)로 나열해줘.\n\n"
        + _DISCLAIMER
    ),
}

# --- Detail sub-buttons (shown after "추가 정보" is expanded) ---

QUERIES_DETAILS: dict[str, str] = {
    "credit_fees": _details_prompt(
        topic="이 카드의 연회비와 이용형태별 수수료율을",
        summary=(
            "다음 두 가지를 자연스러운 문장으로 설명해줘 (숫자 나열 대신, 사용자 입장에서 와닿는 방식으로):\n"
            "1) 연회비 구간이 여러 개라면, 왜 더 비싼 타입이 존재하는지 — 즉 높은 연회비를 내면 어떤 혜택이 추가되는지 1~2문장으로 설명해줘.\n"
            "2) 연체이자율을 기준으로, '예를 들어 50만 원 결제 후 한 달 연체하면 이자가 얼마나 붙는지' 실제 금액으로 계산해서 알려줘."
        ),
        details=(
            "아래 항목을 표(table) 형식으로 정리해줘:\n\n"
            "| 항목 | 수수료율 |\n"
            "|------|----------|\n"
            "| 일시불 | |\n"
            "| 할부 수수료율 (연, 최저~최고) | |\n"
            "| 단기카드대출(현금서비스) 수수료율 (연, 최저~최고) | |\n"
            "| 리볼빙(일부결제금액이월약정) 수수료율 (연, 최저~최고) | |\n"
            "| 연체이자율 | |"
        ),
    ),
    "international_fees": _details_prompt(
        topic="이 카드의 해외 사용 수수료를",
        summary=(
            "다음 세 가지를 자연스러운 문장으로 설명해줘 (숫자 나열 대신, 처음 해외에서 카드를 쓰는 사람이 이해하기 쉽게):\n"
            "1) 해외 수수료는 국내 결제와 달리 언제, 왜 붙는지 — 즉 국제브랜드 수수료와 해외서비스 수수료가 각각 누가 떼어가는 비용인지 한 문장씩 설명해줘.\n"
            "2) 환율 외에 이 수수료가 추가된다는 점을 강조하면서, 예를 들어 100달러짜리 결제 시 실제 수수료가 원화로 얼마나 더 붙는지 계산해서 알려줘.\n"
            "3) 이 수수료는 해외 현지뿐 아니라 국내에서 외화 결제(해외 직구 등)를 할 때도 동일하게 적용된다는 점을 알려줘."
        ),
        details=(
            "아래 항목을 표(table) 형식으로 정리해줘:\n\n"
            "| 항목 | 내용 |\n"
            "|------|------|\n"
            "| 국제브랜드 수수료 (비자/마스터/기타 브랜드별) | |\n"
            "| 해외서비스 수수료율 | |\n"
            "| 현금서비스 해외 이용 수수료 / 면제 조건 | |\n"
            "| 원화 청구 시 환율 기준 | |"
        ),
    ),
    "late_payment": _details_prompt(
        topic="이 카드 이용대금을 연체하면 어떻게 되는지",
        summary=(
            "다음 두 가지를 자연스러운 문장으로 설명해줘 (숫자 나열 대신, 처음 카드를 쓰는 사람이 와닿게):\n"
            "1) 연체이자율을 기준으로, '예를 들어 50만 원 청구 후 한 달 연체하면 연체이자가 얼마나 붙는지' 실제 금액으로 계산해서 알려줘.\n"
            "2) 연체가 길어질수록 어떤 일이 순서대로 벌어지는지 (이자 → 신용점수 하락 → 카드 정지 → 최악의 경우) 흐름을 한 문장으로 요약해줘."
        ),
        details=(
            "아래 항목을 불릿 포인트(•)로 정리해줘:\n"
            "• 연체이자율 계산 방식 (정상이자율 + 가산금리, 최고 연이율)\n"
            "• 일시불·무이자할부 연체 시 적용 기준\n"
            "• 연체로 인한 불이익 (신용점수 하락, 카드 이용 정지, 한도 감액, 계약 해지 등)\n"
            "• 기한의 이익 상실 주요 사유"
        ),
    ),
    "revolving": _details_prompt(
        topic="이 카드의 리볼빙(일부결제금액이월약정) 서비스를",
        summary=(
            "다음 세 가지를 자연스러운 문장으로 설명해줘 (리볼빙을 처음 접하는 사람이 이해하기 쉽게, 숫자 나열 대신 체감되는 방식으로):\n"
            "1) 리볼빙이 무엇인지 한 문장으로 설명하고, 왜 쓰는지(일시적 자금 부족 해결)와 왜 위험한지(수수료 누적)를 함께 짚어줘.\n"
            "2) 이 카드의 수수료율을 기준으로, '예를 들어 100만 원을 리볼빙으로 한 달 이월하면 수수료가 얼마인지' 실제 금액으로 계산해줘.\n"
            "3) 같은 잔액을 3개월 연속 이월하면 총 수수료가 얼마가 되는지 계산해서, 눈덩이처럼 불어나는 구조를 한 문장으로 설명해줘."
        ),
        details=(
            "아래 항목을 불릿 포인트(•)로 정리해줘:\n"
            "• 리볼빙 수수료율 범위 (연 최저~최고)\n"
            "• 약정결제비율과 최소결제비율의 차이\n"
            "• 리볼빙 수수료 계산 방식 (계산 예시 포함)\n"
            "• 이월잔액 발생 시 신용점수에 미치는 영향"
        ),
    ),
}

# Combined lookup used by run_advisor
QUERIES: dict[str, str] = {**QUERIES_STANDALONE, **QUERIES_DETAILS}


# ===========================< Search Tools >============================

def _log_and_format(results: list[dict], source: str) -> str:
    logger.info(f"[CardAdvisorService] {source} returned {len(results)} results")
    return _format_web_results(results)


# --- always-on: Naver blog (personal reviews, experience posts) ---

@tool
def naver_blog_search(query: str) -> str:
    """
    네이버 블로그에서 신용카드 관련 정보를 검색합니다.
    실사용자 후기, 장단점, 개인 경험담 등 비공식 의견을 찾을 때 사용하세요.
    검색 쿼리는 카드명과 핵심 키워드를 포함한 자연어로 작성하세요.
    """
    logger.info(f"[CardAdvisorService] Tool called — naver_blog_search | query: {query}")
    try:
        return _log_and_format(search_blog(query, display=5), "naver_blog_search")
    except NaverSearchError as exc:
        logger.warning(f"[CardAdvisorService] naver_blog_search failed: {exc}")
        return f"검색 실패: {exc}"


# --- web search: Naver first, Tavily as fallback ---

@tool
def web_search(query: str) -> str:
    """
    웹 검색으로 공식 페이지와 뉴스를 검색합니다.
    카드사 공식 신청 페이지, 발급 조건, 공지사항 등 공식 출처 정보를 찾을 때 사용하세요.
    """
    logger.info(f"[CardAdvisorService] Tool called — web_search | query: {query}")
    try:
        return _log_and_format(search_web(query, display=5), "naver_web_search")
    except NaverSearchError as exc:
        logger.warning(f"[CardAdvisorService] naver_web_search failed ({exc}) — falling back to Tavily")
    try:
        return _log_and_format(tavily_search(query, max_results=5), "tavily_web_search")
    except WebSearchError as exc:
        logger.warning(f"[CardAdvisorService] tavily_web_search also failed: {exc}")
        return f"검색 실패: {exc}"


# ===========================< System Prompt >============================

_SYSTEM_PROMPT = """
너는 {card_name} 전문 상담사야.
사용자 질문에 대해 아래 공식 문서를 우선 참고해서 답해줘.
공식 문서만으로 부족하다고 판단되면 아래 툴을 자유롭게 활용해:
- naver_blog_search: 실사용자 후기, 개인 경험담 등 비공식 의견이 필요할 때
- web_search: 공식 신청 페이지, 발급 조건 등 공식 출처 정보가 필요할 때

{card_info}

[답변 규칙]
- 공식 정보에 있는 수치(할인율, 연회비, 수수료율 등)는 정확히 인용해
- 공식 정보에 없는 항목은 추측하지 말고 "카드사 공식 홈페이지나 약관을 직접 확인해야 해"라고 안내해
- 검색 결과의 사용자 의견은 후기를 명시적으로 요청한 경우에만 출처 없이 자연스럽게 요약해
- 질문에서 출력 형식(표, 헤딩, 불릿 등)이 지정된 경우 반드시 그 형식을 따라줘. 지정이 없을 때만 불릿 포인트(•)로 정리해
- 반말로 친근하게 답해줘
""".strip()


def _build_card_info(manual: str, terms: str) -> str:
    """manual과 terms를 조합해 시스템 프롬프트에 삽입할 card_info 블록을 만듭니다."""
    if not manual and not terms:
        return "(제공된 공식 문서가 없습니다. 검색 툴을 활용해서 답해줘.)"

    parts: list[str] = []
    if manual:
        parts.append(f"[카드 상품 정보]\n{manual}")
    if terms:
        parts.append(f"[약관 정보]\n{terms}")
    return "\n\n".join(parts)


# ===========================< Advisor Cache >============================
# 동일한 카드+질문 유형 조합에 대해 LLM을 반복 호출하지 않도록
# Supabase에 결과를 단기 캐시로 저장함.
# 카드 약관·수수료 정보는 자주 바뀌지 않지만 완전히 정적이지도 않으므로
# 7일 후 만료시켜 오래된 정보가 계속 노출되는 것을 방지함.

_CACHE_TTL_DAYS = 7


def _cache_get(cache_key: str) -> str | None:
    """캐시에서 유효한(7일 이내) 답변을 조회. 없거나 만료됐으면 None 반환."""
    try:
        supabase = get_supabase()
        response = (
            supabase.table("advisor_cache")
            .select("answer, created_at")
            .eq("cache_key", cache_key)
            .maybe_single()
            .execute()
        )
        if not response.data:
            return None

        # created_at 기준으로 만료 여부 확인
        created_at = datetime.fromisoformat(response.data["created_at"])
        if datetime.now(timezone.utc) - created_at > timedelta(days=_CACHE_TTL_DAYS):
            # 만료된 항목을 지연 삭제 (별도 배치 없이 읽는 시점에 정리)
            supabase.table("advisor_cache").delete().eq("cache_key", cache_key).execute()
            logger.info("Cache expired and deleted | key=%s", cache_key)
            return None

        logger.info("Cache hit | key=%s", cache_key)
        return response.data["answer"]
    except Exception as exc:
        # 캐시 조회 실패 시 에이전트를 정상 실행하도록 None 반환 (서비스 중단 방지)
        logger.warning("Cache lookup failed (에이전트 정상 실행으로 계속): %s", exc)
        return None


def _cache_set(cache_key: str, answer: str) -> None:
    """답변을 캐시에 저장. 동일 키가 이미 있으면 덮어씀(upsert)."""
    try:
        supabase = get_supabase()
        supabase.table("advisor_cache").upsert({
            "cache_key": cache_key,
            "answer": answer,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        logger.info("Cache set | key=%s", cache_key)
    except Exception as exc:
        # 캐시 저장 실패는 치명적이지 않으므로 경고만 기록하고 계속 진행
        logger.warning("Cache write failed (결과는 정상 반환): %s", exc)


# ===========================< Card Info Loader >============================

_terms_repo = None
_manual_repo = None
# In-memory cache for card documents: card_name → (manual, terms)
# Files are stable — cached for the lifetime of the process.
_doc_cache: dict[str, tuple[str, str]] = {}


def _get_terms_repo():
    global _terms_repo
    if _terms_repo is None:
        from app.core.config import TERMS_DIR
        from app.repositories.terms_repo import TermsRepository
        _terms_repo = TermsRepository(TERMS_DIR)
    return _terms_repo


def _get_manual_repo():
    global _manual_repo
    if _manual_repo is None:
        from app.core.config import MANUALS_DIR
        from app.repositories.manual_repo import ManualRepository
        _manual_repo = ManualRepository(MANUALS_DIR)
    return _manual_repo


async def _load_card_docs(card_name: str) -> tuple[str, str]:
    """manual + terms를 병렬 로드. 프로세스 생존 기간 동안 in-memory 캐시."""
    if card_name in _doc_cache:
        logger.info(f"[CardAdvisorService] 문서 캐시 히트 | card={card_name}")
        return _doc_cache[card_name]
    manual, terms = await asyncio.gather(
        _get_manual_repo().get_manual(card_name),
        _get_terms_repo().get_terms(card_name),
    )
    _doc_cache[card_name] = (manual, terms)
    logger.info(f"[CardAdvisorService] 문서 로드 완료 및 캐시 저장 | card={card_name} | manual={len(manual)} chars | terms={len(terms)} chars")
    return manual, terms



# ===========================< Agent Loop >============================

@traceable(name="advisor_agent")
async def get_advice(
    card_name: str,
    query_type: QueryType,
) -> str:
    """
    특정 신용카드에 대한 상세 정보(수수료, 후기 등)를 제공하는 어드바이저 서비스.
    cards 테이블에서 terms_file_path를 조회해 Supabase storage에서 마크다운을 로드합니다.
    LLM이 필요하다고 판단할 때만 naver_blog_search 툴을 호출합니다.

    Args:
        card_name  : 카드 이름  (예: "현대카드 M")
        query_type : 질문 유형

    Returns:
        LLM이 생성한 답변 문자열
    """
    logger.info(f"[CardAdvisorService] get_advice 시작 | card={card_name} query_type={query_type}")

    # 캐시 확인 -동일한 카드+질문 유형 조합의 답변이 7일 이내에 생성된 경우 바로 반환
    cache_key = f"{card_name}::{query_type}"
    cached_answer = _cache_get(cache_key)
    if cached_answer is not None:
        return cached_answer

    # 1. 상품설명서(manual) + 약관(terms) 로드
    # QUERIES_STANDALONE(reviews, how_to_apply)은 웹 검색 기반이므로 문서 불필요
    if query_type in QUERIES_DETAILS:
        manual, terms = await _load_card_docs(card_name)
        card_info = _build_card_info(manual, terms)
    else:
        card_info = ""
        logger.info(f"[CardAdvisorService] standalone 쿼리 — 문서 로드 생략 | query_type={query_type}")

    # 2. Build LLM with tools
    # naver_blog_search is only relevant for reviews; all other queries use web search only
    tools = (
        [naver_blog_search, web_search]
        if query_type == "reviews"
        else [web_search]
    )
    llm = get_llm(model=MODEL, temperature=0.0)
    llm_with_tools = llm.bind_tools(tools)
    resilient_invoke = with_resilience(llm_with_tools.ainvoke)
    logger.info(f"[CardAdvisorService] LLM 초기화 완료 (cached) | model={MODEL} | tools={[t.name for t in tools]}")

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.format(
            card_name=card_name,
            card_info=card_info,
        )),
        HumanMessage(content=QUERIES[query_type]),
    ]
    logger.info(f"[CardAdvisorService] 프롬프트 구성 완료 | 사용자 쿼리: {QUERIES[query_type][:50]}...")

    # 3. Agent loop -LLM decides whether to call the search tool
    turn = 0
    while True:
        turn += 1
        logger.info(f"[CardAdvisorService] LLM 호출 시작 | turn={turn}")
        response = await resilient_invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            logger.info(f"[CardAdvisorService] 도구 호출 없음 — 최종 답변 생성 중 (turn={turn})")
            break

        _tools = {t.name: t for t in tools}
        logger.info(f"[CardAdvisorService] {len(response.tool_calls)}개의 도구 호출 요청됨")
        for tool_call in response.tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            logger.info(f"[CardAdvisorService] 도구 실행: {name} | args={args}")
            if not args:
                result = f"도구 호출 오류: '{name}' 필수 인자가 누락되었습니다. 검색어(query)를 포함해서 다시 호출해주세요."
                logger.warning(f"[CardAdvisorService] 도구 호출 인자 누락 — tool={name}")
            else:
                result = _tools[name].invoke(args)
            messages.append(ToolMessage(
                content=result,
                tool_call_id=tool_call["id"],
            ))
            logger.info(f"[CardAdvisorService] 도구 실행 결과 수신 ({len(result)} chars)")

    answer = str(response.content)
    logger.info(f"[CardAdvisorService] get_advice 완료 | 답변 길이={len(answer)} chars")

    # 생성된 답변을 캐시에 저장 -동일 조합의 다음 요청은 LLM 호출 없이 바로 반환됨
    _cache_set(cache_key, answer)
    return answer


# ===========================< Test Run >============================

if __name__ == "__main__":
    import asyncio
    import time
    from app.core.logger import init_logger

    init_logger()  # 로컬 테스트 시에도 JSON 로거 적용

    TEST_CARD_NAME = "KB 국민 굿데이 카드"

    async def run_test():
        logger.info(f"Testing get_advice for {TEST_CARD_NAME}...")
        start_time = time.perf_counter()
        
        answer = await get_advice(TEST_CARD_NAME, "how_to_apply")
        
        latency = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Test Finished", 
            latency_ms=round(latency, 2), 
            answer=answer
        )

    asyncio.run(run_test())
