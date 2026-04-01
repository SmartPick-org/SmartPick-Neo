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

import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langsmith import traceable

from apps.backend.tools.web_search import (
    search_blog,
    search_web,
    NaverSearchError,
    tavily_search,
    duckduckgo_search,
    serper_search,
    format_results as _format_web_results,
    WebSearchError,
)

# ===========================< Setting >============================
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO, format="[ADVISOR] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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

MARKDOWN_DIR = Path(__file__).resolve().parents[3] / "datasets" / "markdown"

# ---------------------------------------------------------------------------
# TODO: Replace this hardcoded path with dynamic lookup.
# Naming convention: {CompanyCode}_{FullCardName}_{descriptor}_terms.md
# e.g. card_company="KB", card_name="KB 국민 굿데이 카드"
#   → datasets/markdown/kb/terms/KB_KB 국민 굿데이 카드_PDF로 파일저장_terms.md
#
# Future logic should:
#   1. Lowercase card_company → subfolder (e.g. "KB" → "kb")
#   2. Glob MARKDOWN_DIR / subfolder / "terms" / f"{card_company}_{card_name}_*_terms.md"
#   3. Return the first match
# ---------------------------------------------------------------------------
_HARDCODED_CARD_FILE = (
    MARKDOWN_DIR
    / "kb"
    / "terms"
    / "KB_KB 국민 굿데이 카드_PDF로 파일저장_terms.md"
)

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

QUERIES_STANDALONE: dict[str, str] = {
    "reviews": (
        "이 카드의 실사용자 후기를 검색해서 아래 형식으로만 답해줘. "
        "카드 혜택·장점 설명은 하지 마. "
        "\n\n[전반적 평가]\n실사용자들의 전반적인 만족도와 분위기를 2~3문장으로 요약해줘."
        "\n\n[참고한 후기 목록]\n각 후기마다 • 작성 시기 / 작성자 유형(실사용자 or 카드 추천 블로거) / 한 줄 요약 형식으로 나열해줘."
        "\n\n[주요 불만 및 페인포인트]\n실사용자들이 공통적으로 언급한 불만이나 불편한 점을 불릿 포인트로 정리해줘."
    ),
    "how_to_apply": (
        "이 카드 온라인 신청 방법과 발급 조건만 알려줘. "
        "카드사 메인 홈페이지가 아닌 이 카드의 신청 페이지 직접 URL을 검색해서 알려줘. "
        "발급 자격(나이·소득 등 조건)과 필요 서류도 함께 안내해줘. "
        "카드 혜택, 연회비, 사용자 후기 등 신청과 무관한 정보는 절대 포함하지 마."
    ),
}

# --- Detail sub-buttons (shown after "추가 정보" is expanded) ---

QUERIES_DETAILS: dict[str, str] = {
    "credit_fees": (
        "이 카드의 이용형태별 수수료율을 알려줘. "
        "다음 항목을 각각 찾아서 정확한 수치와 함께 안내해줘: "
        "① 일시불 수수료, "
        "② 할부 수수료율(연, 최저~최고), "
        "③ 단기카드대출(현금서비스) 수수료율(연, 최저~최고), "
        "④ 일부결제금액이월약정(리볼빙) 수수료율(연, 최저~최고). "
        "수수료율이 개인신용평점에 따라 달라지는 경우 그 사실도 안내해줘."
    ),
    "international_fees": (
        "이 카드의 해외 사용 수수료를 알려줘. "
        "다음 항목을 각각 찾아서 정확한 수치와 함께 안내해줘: "
        "① 국제브랜드수수료(비자·마스터·JCB·아멕스 등 브랜드별 요율), "
        "② 해외서비스수수료율, "
        "③ 현금서비스 해외 이용 시 수수료 면제 조건(조기 결제 기간 등). "
        "원화 청구 시 적용되는 환율 기준(전신환매도율 기준일 등)도 알려줘."
    ),
    "late_payment": (
        "이 카드 이용대금을 연체하면 어떻게 되는지 알려줘. "
        "다음 항목을 각각 찾아서 안내해줘: "
        "① 연체이자율 계산 방식(정상이자율 + 가산금리, 최고 연이율), "
        "② 일시불·무이자할부 연체 시 적용 기준, "
        "③ 연체로 인한 불이익(신용점수 하락, 카드 이용 정지, 한도 감액, 계약 해지 등), "
        "④ 기한의 이익 상실 주요 사유."
    ),
    "revolving": (
        "이 카드의 리볼빙(일부결제금액이월약정) 서비스를 설명해줘. "
        "다음 항목을 각각 찾아서 안내해줘: "
        "① 리볼빙 수수료율 범위(연 최저~최고), "
        "② 약정결제비율과 최소결제비율의 차이, "
        "③ 리볼빙 수수료 계산 방식(계산 예시 포함), "
        "④ 이월잔액이 발생할 경우 신용점수에 미치는 영향."
    ),
}

# Combined lookup used by run_advisor
QUERIES: dict[str, str] = {**QUERIES_STANDALONE, **QUERIES_DETAILS}

# ===========================< Search Tools >============================

def _log_and_format(results: list[dict], source: str) -> str:
    logger.info("%s returned %d results", source, len(results))
    return _format_web_results(results)


# --- always-on: Naver blog (personal reviews, experience posts) ---

@tool
def naver_blog_search(query: str) -> str:
    """
    네이버 블로그에서 신용카드 관련 정보를 검색합니다.
    실사용자 후기, 장단점, 개인 경험담 등 비공식 의견을 찾을 때 사용하세요.
    검색 쿼리는 카드명과 핵심 키워드를 포함한 자연어로 작성하세요.
    """
    logger.info("Tool called — naver_blog_search | query: %s", query)
    try:
        return _log_and_format(search_blog(query, display=5), "naver_blog_search")
    except NaverSearchError as exc:
        logger.warning("naver_blog_search failed: %s", exc)
        return f"검색 실패: {exc}"


# --- web search backends (one is selected via ACTIVE_WEB_SEARCH_TOOL below) ---

@tool
def naver_web_search(query: str) -> str:
    """
    네이버 웹 검색으로 공식 페이지와 뉴스를 검색합니다.
    카드사 공식 신청 페이지, 발급 조건, 공지사항 등 공식 출처 정보를 찾을 때 사용하세요.
    """
    logger.info("Tool called — naver_web_search | query: %s", query)
    try:
        return _log_and_format(search_web(query, display=5), "naver_web_search")
    except NaverSearchError as exc:
        logger.warning("naver_web_search failed: %s", exc)
        return f"검색 실패: {exc}"


@tool
def tavily_web_search(query: str) -> str:
    """
    Tavily 웹 검색으로 공식 페이지와 뉴스를 검색합니다.
    카드사 공식 신청 페이지, 발급 조건, 공지사항 등 공식 출처 정보를 찾을 때 사용하세요.
    """
    logger.info("Tool called — tavily_web_search | query: %s", query)
    try:
        return _log_and_format(tavily_search(query, max_results=5), "tavily_web_search")
    except WebSearchError as exc:
        logger.warning("tavily_web_search failed: %s", exc)
        return f"검색 실패: {exc}"


@tool
def duckduckgo_web_search(query: str) -> str:
    """
    DuckDuckGo 웹 검색으로 공식 페이지와 뉴스를 검색합니다.
    카드사 공식 신청 페이지, 발급 조건, 공지사항 등 공식 출처 정보를 찾을 때 사용하세요.
    """
    logger.info("Tool called — duckduckgo_web_search | query: %s", query)
    try:
        return _log_and_format(duckduckgo_search(query, max_results=5), "duckduckgo_web_search")
    except WebSearchError as exc:
        logger.warning("duckduckgo_web_search failed: %s", exc)
        return f"검색 실패: {exc}"


@tool
def serper_web_search(query: str) -> str:
    """
    Serper(Google) 웹 검색으로 공식 페이지와 뉴스를 검색합니다.
    카드사 공식 신청 페이지, 발급 조건, 공지사항 등 공식 출처 정보를 찾을 때 사용하세요.
    """
    logger.info("Tool called — serper_web_search | query: %s", query)
    try:
        return _log_and_format(serper_search(query, max_results=5), "serper_web_search")
    except WebSearchError as exc:
        logger.warning("serper_web_search failed: %s", exc)
        return f"검색 실패: {exc}"


# ===========================< Active Web Search Backend >============================
# Switch this to test different backends alongside naver_blog_search.
# Options: naver_web_search | tavily_web_search | duckduckgo_web_search | serper_web_search

ACTIVE_WEB_SEARCH_TOOL = naver_web_search


# ===========================< System Prompt >============================

_SYSTEM_PROMPT = """
너는 {card_company} {card_name} 전문 상담사야.
사용자 질문에 대해 아래 [카드 공식 정보]를 우선 참고해서 답해줘.
공식 정보만으로 부족하다고 판단되면 아래 툴을 자유롭게 활용해:
- naver_blog_search: 실사용자 후기, 개인 경험담 등 비공식 의견이 필요할 때
- {web_tool_name}: 공식 신청 페이지, 발급 조건 등 공식 출처 정보가 필요할 때

[카드 공식 정보]
{card_info}

[답변 규칙]
- 공식 정보에 있는 수치(할인율, 연회비, 수수료율 등)는 정확히 인용해
- 공식 정보에 없는 항목은 추측하지 말고 "카드사 공식 홈페이지나 약관을 직접 확인해야 해"라고 안내해
- 검색 결과의 사용자 의견은 후기를 명시적으로 요청한 경우에만 출처 없이 자연스럽게 요약해
- 답변은 핵심 항목별로 불릿 포인트(•)로 정리해
- 반말로 친근하게 답해줘
- 답변 마지막에 공식 채널(앱, 홈페이지)을 안내해줘 (단, 본문에서 이미 언급한 URL·채널은 중복 표기하지 마)
""".strip()


# ===========================< Card Info Loader >============================

def _load_card_info(card_company: str, card_name: str) -> str:  # noqa: ARG001
    # TODO: replace with dynamic file resolution using card_company + card_name
    # (see _HARDCODED_CARD_FILE comment above for the naming convention)
    md_file = _HARDCODED_CARD_FILE
    if not md_file.exists():
        logger.error("Card markdown not found: %s", md_file)
        return f"카드 파일을 찾을 수 없어: {md_file}"
    logger.info("Loaded card info from: %s (%d chars)", md_file.name, md_file.stat().st_size)
    return md_file.read_text(encoding="utf-8")


# ===========================< Agent Loop >============================

@traceable(name="advisor_agent")
def run_advisor(
    card_name: str,
    card_company: str,
    query_type: QueryType,
) -> str:
    """
    특정 신용카드에 대한 사용자 질문에 답변하는 어드바이저 에이전트.
    LLM이 필요하다고 판단할 때만 naver_blog_search 툴을 호출합니다.

    Args:
        card_name    : 카드 이름  (예: "현대카드 M")
        card_company : 카드사 이름 (예: "Hyundai", "KB", "Shinhan")
        query_type   : 질문 유형

    Returns:
        LLM이 생성한 답변 문자열
    """
    logger.info("run_advisor start | card=%s (%s) query_type=%s", card_name, card_company, query_type)

    # 1. Load card markdown
    card_info = _load_card_info(card_company, card_name)

    # 2. Build LLM with tools
    # naver_blog_search is only relevant for reviews; all other queries use web search only
    tools = (
        [naver_blog_search, ACTIVE_WEB_SEARCH_TOOL]
        if query_type == "reviews"
        else [ACTIVE_WEB_SEARCH_TOOL]
    )
    llm = init_chat_model(model=MODEL, temperature=0.0)
    llm_with_tools = llm.bind_tools(tools)
    logger.info("LLM initialised | model=%s | tools=%s", MODEL, [t.name for t in tools])

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.format(
            card_company=card_company,
            card_name=card_name,
            card_info=card_info,
            web_tool_name=ACTIVE_WEB_SEARCH_TOOL.name,
        )),
        HumanMessage(content=QUERIES[query_type]),
    ]
    logger.info("Prompt built | user query: %s", QUERIES[query_type])

    # 3. Agent loop — LLM decides whether to call the search tool
    turn = 0
    while True:
        turn += 1
        logger.info("LLM invoke | turn=%d", turn)
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            logger.info("No tool calls — generating final answer (turn=%d)", turn)
            break

        _tools = {t.name: t for t in tools}
        logger.info("%d tool call(s) requested", len(response.tool_calls))
        for tool_call in response.tool_calls:
            name = tool_call["name"]
            logger.info("Executing tool: %s | args=%s", name, tool_call["args"])
            result = _tools[name].invoke(tool_call["args"])
            messages.append(ToolMessage(
                content=result,
                tool_call_id=tool_call["id"],
            ))
            logger.info("Tool result received (%d chars)", len(result))

    logger.info("run_advisor complete | answer length=%d chars", len(str(response.content)))
    return str(response.content)


# ===========================< Test Run >============================

if __name__ == "__main__":
    TEST_CARD_NAME = "KB 국민 굿데이 카드"
    TEST_CARD_COMPANY = "KB"

    # One from QUERIES_DETAILS, both from QUERIES_STANDALONE
    for qtype in ["how_to_apply"]:
        print(f"\n{'='*60}")
        print(f"Query type: {qtype}")
        print(f"Query: {QUERIES[qtype]}")
        print("="*60)
        answer = run_advisor(TEST_CARD_NAME, TEST_CARD_COMPANY, qtype)
        print(answer)
        print()
