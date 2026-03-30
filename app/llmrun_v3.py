"""
JSON v3 + BenefitCalculator 기반 카드 추천 (llmrun_v3)

흐름: 유저 입력 → 필터링 → BenefitCalculator 전체 계산 → 랭킹 → LLM 설명
- json_v3 스키마의 카드 데이터 사용
- BenefitCalculator(Calc_tool.py)로 정밀 혜택 계산
- 스코어링 필터 없이 전체 카드 계산 → 혜택 금액 기준 랭킹

사용법: python -m apps.backend.agent.llmrun_v3
"""

import os
import json
import time
import uuid

from datetime import datetime
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, NotRequired, TypedDict

from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from langfuse import observe, Langfuse

from apps.backend.agent.prompts import EXPLAIN_PROMPT, QA_PROMPT
from apps.backend.tools.Calc_tool import BenefitCalculator

# ===========================< Setting >============================
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

REQUIRED_KEYS = ["LANGSMITH_API_KEY", "UPSTAGE_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]
for key in REQUIRED_KEYS:
    if not os.getenv(key):
        print(f"[WARN] {key}가 환경 변수에 설정되지 않았습니다.")

os.environ["LANGSMITH_TRACING_V2"] = "true"
os.environ["LANGSMITH_PROJECT"] = "Smart_Pick_V3"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"

langfuse = Langfuse()

MODEL = "solar-pro2"
llm = init_chat_model(model=MODEL, temperature=0.0)

# ===========================< Test Log >============================
TEST_LOG_DIR = Path(__file__).resolve().parents[3] / "test_logs" / "llmrun_v3"
PROMPT_VERSIONS = {"EXPLAIN_PROMPT": "V3", "QA_PROMPT": "V1"}

_test_log: dict = {}


def _init_test_log(total_budget: int, category_spending: dict):
    global _test_log
    _test_log = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "model": MODEL,
        "prompt_versions": PROMPT_VERSIONS,
        "input": {
            "total_budget": total_budget,
            "category_spending": category_spending,
        },
        "filter": {},
        "calc_results": [],
        "top3": [],
        "explain_raw": "",
    }


def _save_test_log(case_name: str):
    TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = case_name.replace(" ", "_").replace("+", "")
    filepath = TEST_LOG_DIR / f"{ts}_{safe_name}.json"
    filepath.write_text(json.dumps(_test_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[LOG] 테스트 로그 저장: {filepath}")


# ===========================< Data Loading >============================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json_v3"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"


def _adapt_v3_for_calculator(card_data: dict) -> dict:
    """
    json_v3 스키마를 BenefitCalculator가 기대하는 형식으로 어댑팅합니다.

    주요 변환:
    - FIXED_PER_VOLUME → PER_UNIT + unit_label/unit_amount 추가
    - reward_unit을 card_meta에서 benefit별로 복사
    - 누락된 필드에 기본값 채우기
    """
    meta = card_data.get("card_meta", {})
    currency = meta.get("reward_currency", "KRW")
    krw_rate = meta.get("currency_to_krw_rate", 1.0)

    adapted_benefits = []
    for b in card_data.get("benefits", []):
        ab = dict(b)  # shallow copy

        # reward_unit 추가 (card_meta 기반)
        if "reward_unit" not in ab or ab["reward_unit"] is None:
            ab["reward_unit"] = {
                "currency": currency,
                "currency_to_krw_rate": krw_rate,
            }

        # calculation_rule 어댑팅
        rule = dict(ab.get("calculation_rule", {}))

        # FIXED_PER_VOLUME → PER_UNIT
        if rule.get("calc_method") == "FIXED_PER_VOLUME":
            rule["calc_method"] = "PER_UNIT"
            if "unit_label" not in rule or rule.get("unit_label") is None:
                rule["unit_label"] = "liter"
            if "unit_amount" not in rule or rule.get("unit_amount") is None:
                rule["unit_amount"] = rule.get("fixed_amount", 0)

        # 누락 필드 기본값
        rule.setdefault("unit_label", None)
        rule.setdefault("unit_amount", None)
        rule.setdefault("monthly_usage_limit", None)
        rule.setdefault("fallback_reward_rate", 0.0)
        rule.setdefault("transaction_tiers", None)
        ab["calculation_rule"] = rule

        # transaction_conditions 누락 필드 기본값
        tc = dict(ab.get("transaction_conditions", {}))
        tc.setdefault("min_payment_amount", 0)
        tc.setdefault("max_payment_amount_applied", None)
        tc.setdefault("max_count_per_day", None)
        tc.setdefault("max_count_per_month", None)
        tc.setdefault("max_count_per_year", None)
        tc.setdefault("day_of_week", None)
        tc.setdefault("time_of_day", {"start": None, "end": None})
        tc.setdefault("requires_auto_payment", False)
        tc.setdefault("requires_offline", False)
        tc.setdefault("requires_online", False)
        ab["transaction_conditions"] = tc

        # edge_case_flags 누락 필드 기본값
        ef = dict(ab.get("edge_case_flags", {}))
        ef.setdefault("requires_user_selection", False)
        ef.setdefault("excludes_from_performance", False)
        ef.setdefault("category_excludes_from_performance", False)
        ef.setdefault("special_month_bonus", None)
        ef.setdefault("performance_gap_forgiveness", {"enabled": False})
        ef.setdefault("current_month_performance", False)
        ef.setdefault("payment_platform_bonus", {"platform": None, "additional_rate": None})
        ef.setdefault("annual_usage_tiers", [])
        ef.setdefault("annual_voucher", {})
        ef.setdefault("escape_hatch_note", None)
        ab["edge_case_flags"] = ef

        adapted_benefits.append(ab)

    return {
        "card_meta": meta,
        "benefit_groups": card_data.get("benefit_groups", []),
        "benefits": adapted_benefits,
    }


def load_all_cards_v3() -> list[dict]:
    """datasets/json_v3/ 하위의 모든 카드 JSON을 로드하고 어댑팅합니다."""
    all_cards = []
    for company_dir in DATASETS_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        for json_file in company_dir.glob("*.json"):
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            if not raw.get("card_meta", {}).get("card_name"):
                continue

            adapted = _adapt_v3_for_calculator(raw)
            # 편의용 필드 추가
            adapted["_file_path"] = str(json_file)
            adapted["_raw_v3"] = raw

            # 카테고리 목록 추출 (필터용)
            card_categories = set()
            for b in adapted["benefits"]:
                cat = b.get("category", "")
                if cat and cat not in ("All_Domestic", "General"):
                    card_categories.add(cat)
                elif cat in ("All_Domestic", "General"):
                    card_categories.add(cat)
            adapted["_card_categories"] = card_categories

            all_cards.append(adapted)
    return all_cards


def load_digest(card: dict) -> str:
    """카드의 compact digest 마크다운을 로드합니다."""
    card_id = card.get("card_meta", {}).get("card_id", "")
    company = card.get("card_meta", {}).get("card_company", "")

    # company → digest 디렉토리 매핑
    company_dir_map = {
        "KB국민카드": "kb", "신한카드": "shinhan", "현대카드": "hyundai",
    }
    company_dir = company_dir_map.get(company, "")
    if company_dir:
        digest_dir = DIGEST_DIR / company_dir
        if digest_dir.exists():
            # card_id로 매칭 시도
            for md_file in digest_dir.glob("*.md"):
                if card_id.replace("_", "") in md_file.stem.replace("_", "").replace(" ", "").lower():
                    return md_file.read_text(encoding="utf-8")

    card_name = card.get("card_meta", {}).get("card_name", "알 수 없음")
    return f"# {card_name}\n(digest 파일 없음)"


# ===========================< State >============================

class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    total_budget: NotRequired[Optional[int]]
    category_spending: NotRequired[Optional[Dict[str, int]]]
    filtered_cards: NotRequired[Optional[list]]
    calc_results: NotRequired[Optional[list]]
    recommended_cards: NotRequired[Optional[list]]
    last_raw_data: NotRequired[Optional[str]]


# ===========================< Nodes >============================

@observe(name="v3_filter_cards")
@traceable(run_type="chain", name="v3_filter_cards")
def filter_cards_node(state: AgentState):
    """전월실적 + 카테고리 겹침 기준으로 카드를 필터링합니다."""
    print("[DEBUG] filter_cards_node (v3)")
    total_budget = state.get("total_budget", 0)
    category_spending = state.get("category_spending", {})
    user_categories = set(category_spending.keys())

    all_cards = load_all_cards_v3()

    # 필터 A: 전월실적 충족
    after_performance = [
        card for card in all_cards
        if card["card_meta"].get("minimum_performance", 0) <= total_budget
    ]

    # 필터 B: 카테고리 겹침 (All_Domestic/General은 항상 매칭)
    filtered = []
    for card in after_performance:
        cats = card["_card_categories"]
        if cats & user_categories or "All_Domestic" in cats or "General" in cats:
            filtered.append(card)

    print(f"  전체 {len(all_cards)}개 → 실적 충족 {len(after_performance)}개 → 카테고리 매칭 {len(filtered)}개")

    _test_log["filter"]["total_cards"] = len(all_cards)
    _test_log["filter"]["after_performance"] = len(after_performance)
    _test_log["filter"]["after_category"] = len(filtered)

    if not filtered:
        return {
            "messages": [AIMessage(
                content=f"월 소비 {total_budget:,}원 기준으로 조건을 충족하는 카드가 없습니다."
            )],
            "filtered_cards": [],
        }

    return {"filtered_cards": filtered}


@observe(name="v3_calculate_benefits")
@traceable(run_type="chain", name="v3_calculate_benefits")
def calculate_benefits_node(state: AgentState):
    """BenefitCalculator로 전체 카드의 혜택을 계산합니다."""
    print("[DEBUG] calculate_benefits_node (v3: BenefitCalculator)")
    filtered_cards = state.get("filtered_cards", [])
    category_spending = state.get("category_spending", {})
    total_budget = state.get("total_budget", 0)

    calc_results = []
    for card in filtered_cards:
        card_name = card["card_meta"].get("card_name", "?")
        try:
            calculator = BenefitCalculator(card)
            result = calculator.calculate(category_spending, user_total_spend=total_budget)

            monthly = result.get("monthly_total_krw", 0)
            annual_extra = result.get("annual_total_krw", 0)
            yearly = monthly * 12 + annual_extra

            calc_results.append({
                "card_name": card_name,
                "card_company": card["card_meta"].get("card_company", ""),
                "card_id": card["card_meta"].get("card_id", ""),
                "annual_fee": card["card_meta"].get("annual_fee", 0),
                "minimum_performance": card["card_meta"].get("minimum_performance", 0),
                "performance_met": result.get("performance_met", False),
                "expected_monthly_benefit": monthly,
                "expected_yearly_benefit": yearly,
                "category_breakdown": result.get("category_breakdown", []),
                "annual_breakdown": result.get("annual_breakdown", []),
                "warnings": result.get("warnings", []),
                "_card_data": card,
            })

            print(f"  {card_name}: 월 {monthly:,}원 (카테고리 {len(result.get('category_breakdown', []))}개)")

        except Exception as e:
            print(f"  [ERROR] {card_name} 계산 실패: {e}")

    # 혜택 금액 기준 정렬
    calc_results.sort(key=lambda x: x["expected_monthly_benefit"], reverse=True)

    print(f"\n  === 전체 계산 결과 ({len(calc_results)}장) ===")
    for i, r in enumerate(calc_results):
        marker = "★" if i < 7 else " "
        print(f"    {marker} {i+1:2d}. {r['card_name']}: 월 {r['expected_monthly_benefit']:,}원")
        for cb in r["category_breakdown"]:
            print(f"         - {cb['category']}: {cb['monthly_discount_krw']:,}원")

    _test_log["calc_results"] = [
        {
            "card_name": r["card_name"],
            "card_id": r["card_id"],
            "expected_monthly_benefit": r["expected_monthly_benefit"],
            "expected_yearly_benefit": r["expected_yearly_benefit"],
            "category_breakdown": r["category_breakdown"],
            "performance_met": r["performance_met"],
        }
        for r in calc_results
    ]

    return {"calc_results": calc_results}


@observe(name="v3_rank_and_explain")
def rank_and_explain_node(state: AgentState):
    """최종 랭킹 후 LLM 추천 설명을 생성합니다."""
    print("[DEBUG] rank_and_explain_node (v3)")
    calc_results = state.get("calc_results", [])
    category_spending = state.get("category_spending", {})
    total_budget = state.get("total_budget", 0)

    if not calc_results:
        return {"messages": [AIMessage(content="혜택 계산 결과가 없습니다.")]}

    # Top 3 선정
    ranked = sorted(calc_results, key=lambda x: x["expected_monthly_benefit"], reverse=True)[:3]

    # 유저 소비 패턴 텍스트
    spending_lines = [f"월 총 소비: {total_budget:,}원"]
    for cat, amount in category_spending.items():
        spending_lines.append(f"- {cat}: 월 {amount:,}원")
    user_spending = "\n".join(spending_lines)

    # 1순위 카드의 digest 로드
    top1 = ranked[0]
    card_digest = load_digest(top1.get("_card_data", {}))

    # calc_summary 텍스트
    breakdown_lines = []
    for cb in top1["category_breakdown"]:
        breakdown_lines.append(f"  - {cb['category']}: {cb['monthly_discount_krw']:,}원")
    calc_summary = (
        f"카드: {top1['card_name']} ({top1['card_company']})\n"
        f"연회비: {top1['annual_fee']:,}원\n"
        f"월 예상 할인: {top1['expected_monthly_benefit']:,}원 | "
        f"연간 예상: {top1['expected_yearly_benefit']:,}원\n"
        + "\n".join(breakdown_lines)
    )

    # LLM 추천 설명
    explain_prompt = EXPLAIN_PROMPT.format(
        user_spending=user_spending,
        card_digest=card_digest,
        calc_summary=calc_summary,
    )
    explanation = llm.invoke([SystemMessage(content=explain_prompt)]).content

    # 테스트 로그
    _test_log["top3"] = [
        {
            "card_name": r["card_name"],
            "card_id": r["card_id"],
            "expected_monthly_benefit": r["expected_monthly_benefit"],
            "category_breakdown": r["category_breakdown"],
        }
        for r in ranked
    ]
    _test_log["explain_raw"] = explanation if isinstance(explanation, str) else str(explanation)

    # 최종 응답 구성
    response_parts = []
    for i, card in enumerate(ranked):
        rank_label = ["1순위", "2순위", "3순위"][i]
        monthly = card["expected_monthly_benefit"]
        yearly = card["expected_yearly_benefit"]
        annual_fee = card["annual_fee"]
        net_benefit = yearly - annual_fee

        details = []
        for cb in card["category_breakdown"]:
            details.append(f"  - {cb['category']}: {cb['monthly_discount_krw']:,}원")
            if cb.get("warnings"):
                for w in cb["warnings"]:
                    details.append(f"    ⚠ {w}")

        section = f"[{rank_label}] {card['card_name']} ({card['card_company']})\n"
        section += f"연회비: {annual_fee:,}원 | 월 예상 할인: {monthly:,}원 | 연 순이익 추정: {net_benefit:,}원\n"
        if details:
            section += "\n".join(details) + "\n"

        if card.get("warnings"):
            for w in card["warnings"]:
                section += f"  [참고] {w}\n"

        response_parts.append(section)

    final_response = "\n".join(response_parts)
    final_response += f"\n{'=' * 40}\n{explanation}"

    recommended_cards = [
        {
            "card_name": r["card_name"],
            "card_company": r["card_company"],
            "card_id": r["card_id"],
            "annual_fee": r["annual_fee"],
            "minimum_performance": r["minimum_performance"],
            "expected_monthly_benefit": r["expected_monthly_benefit"],
            "category_breakdown": r["category_breakdown"],
            "explanation": explanation if i == 0 else "",
        }
        for i, r in enumerate(ranked)
    ]

    return {
        "messages": [AIMessage(content=final_response)],
        "recommended_cards": recommended_cards,
        "last_raw_data": json.dumps(recommended_cards, ensure_ascii=False),
    }


@observe(name="v3_answer_qa")
def answer_qa_node(state: AgentState):
    """추천된 카드에 대한 후속 질문에 답변합니다."""
    print("[DEBUG] answer_qa_node (v3)")
    raw_data = state.get("last_raw_data", "이전 검색 결과 원본이 존재하지 않습니다.")
    qa_prompt = QA_PROMPT.format(raw_data=raw_data)
    response = llm.invoke([SystemMessage(content=qa_prompt)] + state["messages"])
    return {"messages": [AIMessage(content=response.content)]}


# ===========================< Edge Logic >============================

def check_filter_result(state: AgentState) -> Literal["calculate", "no_results"]:
    filtered = state.get("filtered_cards", [])
    return "calculate" if filtered else "no_results"


# ===========================< Graph Construction >============================

workflow = StateGraph(AgentState)

workflow.add_node("filter_cards", filter_cards_node)
workflow.add_node("calculate_benefits", calculate_benefits_node)
workflow.add_node("rank_and_explain", rank_and_explain_node)
workflow.add_node("answer_qa", answer_qa_node)

# 메인 흐름: filter → calculate → explain → END (스코어링 단계 없음)
workflow.add_edge(START, "filter_cards")
workflow.add_conditional_edges(
    "filter_cards",
    check_filter_result,
    {
        "calculate": "calculate_benefits",
        "no_results": END,
    },
)
workflow.add_edge("calculate_benefits", "rank_and_explain")
workflow.add_edge("rank_and_explain", END)
workflow.add_edge("answer_qa", END)

memory = InMemorySaver()
app = workflow.compile(checkpointer=memory)

# ===========================< Test Execution >============================

if __name__ == "__main__":
    TEST_CASES = {
        "1": {
            "name": "카페 + 교통 위주 소비자",
            "total_budget": 500000,
            "category_spending": {"Coffee": 50000, "Traffic": 100000, "Shopping": 150000},
        },
        "2": {
            "name": "여행 + 쇼핑 고소비자",
            "total_budget": 1000000,
            "category_spending": {"Travel": 300000, "Shopping": 200000, "Food": 200000},
        },
        "3": {
            "name": "생활비 중심 알뜰 소비자",
            "total_budget": 300000,
            "category_spending": {"Traffic": 50000, "Shopping": 30000, "Food": 100000},
        },
        "4": {
            "name": "주유 + 차량 관리 위주",
            "total_budget": 700000,
            "category_spending": {"Traffic": 150000, "Shopping": 200000, "Life": 100000},
        },
    }

    def run_test(case_id: str):
        case = TEST_CASES[case_id]
        print(f"\n{'=' * 20} [테스트: {case['name']}] {'=' * 20}")
        print(f"  총 월소비: {case['total_budget']:,}원")
        for cat, amt in case["category_spending"].items():
            print(f"  - {cat}: {amt:,}원")
        print()

        _init_test_log(case["total_budget"], case["category_spending"])

        start_time = time.time()

        session_id = f"test_{uuid.uuid4().hex[:6]}"
        config: RunnableConfig = {"configurable": {"thread_id": session_id}}

        inputs: AgentState = {
            "messages": [],
            "total_budget": case["total_budget"],
            "category_spending": case["category_spending"],
        }

        for event in app.stream(inputs, config=config):
            for key, value in event.items():
                if "messages" in value and value["messages"]:
                    print(f"[{key}] {value['messages'][-1].content}")
                if "filtered_cards" in value:
                    print(f"  [필터 결과] {len(value['filtered_cards'])}개 카드 통과")

        elapsed = time.time() - start_time
        _test_log["elapsed_seconds"] = round(elapsed, 2)
        print(f"\n[TIME] 소요 시간: {elapsed:.1f}초")

        _save_test_log(case["name"])
        print(f"{'=' * 60}\n")

    # 인터랙티브 메뉴
    while True:
        print("\n테스트 케이스를 선택하세요:")
        for k, v in TEST_CASES.items():
            print(f"  [{k}] {v['name']} (월 {v['total_budget']:,}원)")
        print("  [q] 종료")

        cmd = input("번호 입력: ").strip().lower()
        if cmd == "q":
            print("테스트를 종료합니다.")
            break
        elif cmd in TEST_CASES:
            run_test(cmd)
        else:
            print("[WARN] 잘못된 입력입니다.")
