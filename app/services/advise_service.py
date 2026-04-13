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

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from loguru import logger
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langsmith import traceable

from app.core.config import MARKDOWN_DIR, get_llm
from app.core.resilience import with_resilience
from app.core.database import fetch_markdown_from_s3, get_supabase
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
        "이 카드 온라인 신청 방법과 발급 조건만 아래 형식으로 정확히 답해줘. "
        "카드 혜택, 연회비, 사용자 후기 등 신청과 무관한 정보는 절대 포함하지 마. "
        "반드시 다음 형식을 그대로 사용해:\n\n"
        "1. 신청 URL\n"
        "카드사 메인 홈페이지가 아닌 이 카드의 신청 페이지 직접 URL을 web_search로 검색해서 기재해줘. "
        "URL을 찾지 못한 경우 '공식 홈페이지에서 카드명으로 검색 후 신청 가능'이라고 안내해줘.\n\n"
        "2. 발급 조건\n"
        "나이·소득·신용등급 등 발급 자격 조건을 불릿 포인트(•)로 나열해줘.\n\n"
        "3. 필요 서류\n"
        "신청 시 필요한 서류 목록을 불릿 포인트(•)로 나열해줘.\n\n"
        "※ 정확한 조건은 회사 웹사이트나 고객센터를 통해 확인하는 것을 권장해."
    ),
}

# --- Detail sub-buttons (shown after "추가 정보" is expanded) ---

QUERIES_DETAILS: dict[str, str] = {
    "credit_fees": (
        "이 카드의 이용형태별 수수료율을 안내해줘. "
        "아래 항목 중 약관에 명시된 것만 골라서 수치와 함께 알려줘: "
        "① 일시불 수수료, "
        "② 할부 수수료율(연, 최저~최고), "
        "③ 단기카드대출(현금서비스) 수수료율(연, 최저~최고), "
        "④ 일부결제금액이월약정(리볼빙) 수수료율(연, 최저~최고), "
        "⑤ 연체이자율. "
        "항목이 약관에 없으면 그 항목은 목록에서 빼고, '확인 불가' 같은 말은 하지 마. "
        "찾은 항목만 불릿 포인트로 정리해줘."
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
사용자 질문에 대해 아래 [카드 공식 정보]를 우선 참고해서 답해줘.
공식 정보만으로 부족하다고 판단되면 아래 툴을 자유롭게 활용해:
- naver_blog_search: 실사용자 후기, 개인 경험담 등 비공식 의견이 필요할 때
- web_search: 공식 신청 페이지, 발급 조건 등 공식 출처 정보가 필요할 때

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
            .single()
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

def _local_load_card_info(card_name: str) -> str:
    """
    DB/S3를 사용할 수 없을 때 로컬 datasets/markdown_upstage 폴더에서 일치하는 마크다운 파일을 로드합니다.
    """
    target_file = None
    if MARKDOWN_DIR.exists():
        company_dirs = [d for d in MARKDOWN_DIR.iterdir() if d.is_dir()]
        for d in company_dirs:
            terms_dir = d / "terms"
            if not terms_dir.exists():
                continue
            for file in terms_dir.glob("*.md"):
                if card_name.replace(" ", "") in file.name.replace(" ", ""):
                    target_file = file
                    break
            if target_file:
                break

    if not target_file:
        logger.warning(f"[CardAdvisorService] 일치하는 마크다운 파일을 로컬에서도 찾을 수 없음: {card_name}")
        return "카드 상세 약관 정보를 찾을 수 없어. 카드사 공식 홈페이지를 확인해봐야 할 것 같아."

    logger.info(f"[CardAdvisorService] 로컬 카드 정보 로드 성공: {target_file.name} ({target_file.stat().st_size} chars)")
    return target_file.read_text(encoding="utf-8")


def _load_card_info(card_name: str) -> str:
    try:
        supabase = get_supabase()
        response = supabase.table("cards").select("manual_file_path").eq("card_name", card_name).single().execute()
        
        if not response.data or not response.data.get("manual_file_path"):
            logger.warning(f"[CardAdvisorService] No manual_file_path found in DB for card: {card_name}")
            return _local_load_card_info(card_name)

        file_path = response.data["manual_file_path"].replace("manual/", "terms/", 1)
        logger.info(f"[CardAdvisorService] Fetching card markdown from S3: {file_path}")
        content = fetch_markdown_from_s3(file_path)
        if not content:
            logger.warning(f"[CardAdvisorService] S3 파일 찾을 수 없음, 로컬으로 fallback 시도: {file_path}")
            return _local_load_card_info(card_name)
            
        logger.info(f"[CardAdvisorService] Loaded card info from S3: {file_path} ({len(content)} chars)")
        return content
    except Exception as exc:
        logger.warning(f"[CardAdvisorService] DB lookup failed or S3 failed, falling back to local: {exc}")
        return _local_load_card_info(card_name)



# ===========================< Agent Loop >============================

@traceable(name="advisor_agent")
async def get_advice(
    card_name: str,
    query_type: QueryType,
    file_path: str | None = None,
) -> str:
    """
    특정 신용카드에 대한 상세 정보(수수료, 후기 등)를 제공하는 어드바이저 서비스.
    LLM이 필요하다고 판단할 때만 naver_blog_search 툴을 호출합니다.

    Args:
        card_name  : 카드 이름  (예: "현대카드 M")
        query_type : 질문 유형
        file_path  : S3 파일 경로 (제공 시 DB 조회 생략, 예: "manual/kb_GoodDay.md")

    Returns:
        LLM이 생성한 답변 문자열
    """
    logger.info(f"[CardAdvisorService] get_advice 시작 | card={card_name} query_type={query_type}")

    # 캐시 확인 -동일한 카드+질문 유형 조합의 답변이 7일 이내에 생성된 경우 바로 반환
    cache_key = f"{card_name}::{query_type}"
    cached_answer = _cache_get(cache_key)
    if cached_answer is not None:
        return cached_answer

    # 1. Load card terms markdown
    if file_path:
        logger.info("Loading card info directly from S3: %s", file_path)
        card_info = fetch_markdown_from_s3(file_path)
        if not card_info:
            card_info = f"카드 파일을 S3에서 불러올 수 없어: {file_path}"
    else:
        card_info = _load_card_info(card_name)

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
            logger.info(f"[CardAdvisorService] 도구 실행: {name} | args={tool_call['args']}")
            result = _tools[name].invoke(tool_call["args"])
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
