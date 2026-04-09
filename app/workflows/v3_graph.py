from loguru import logger
from typing import Annotated, Dict, List, Literal, NotRequired, Optional, TypedDict, Any

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.repositories.digest_repo import DigestRepository
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    total_budget: NotRequired[Optional[int]]
    category_spending: NotRequired[Optional[Dict[str, Any]]]
    filtered_cards: NotRequired[Optional[list]]
    calc_results: NotRequired[Optional[list]]
    recommended_cards: NotRequired[Optional[list]]
    last_raw_data: NotRequired[Optional[str]]
    # 에러 전파용 필드
    _has_error: NotRequired[bool]
    _fallback: NotRequired[bool]
    _error_message: NotRequired[Optional[str]]
    _error_type: NotRequired[Optional[str]]


def build_graph(
    recommend_service: CardRecommendService,
    explain_service: ExplainService,
    digest_repo: DigestRepository,
):
    _LLM_FAILURE_MESSAGE = "현재 답변 생성이 원활하지 않습니다. 잠시 후 다시 시도해 주세요."

    # -----------------------------------------------------------------------
    # 비상구 노드 — 어떤 노드에서든 에러가 나면 여기로 라우팅
    # -----------------------------------------------------------------------
    def error_recovery_node(state: AgentState):
        """LLM/계산 실패 시 Fallback 응답 반환. 워크플로우가 중단되지 않도록 합니다."""
        error_type = state.get("_error_type") or ""
        fallback = bool(state.get("_fallback", False))

        if error_type == "LLM":
            error_msg = _LLM_FAILURE_MESSAGE
            fallback = True
        else:
            error_msg = state.get("_error_message") or "처리 중 오류가 발생했습니다."

        logger.warning("[error_recovery_node] Fallback 반환 (type=%s fallback=%s): %s", error_type, fallback, error_msg)
        return {
            "messages": [AIMessage(content=error_msg)],
            "recommended_cards": state.get("recommended_cards") or [],
            "_has_error": True,
            "_fallback": fallback,
        }

    # -----------------------------------------------------------------------
    # 노드 정의
    # -----------------------------------------------------------------------
    def filter_cards_node(state: AgentState):
        total_budget = state.get("total_budget", 0)
        category_spending = state.get("category_spending", {})
        try:
            filtered = recommend_service.filter_cards(total_budget, category_spending)
        except Exception as e:
            logger.exception("[filter_cards_node] 예외 발생: {}", repr(e))
            return {
                "messages": [AIMessage(content="카드 필터링 중 오류가 발생했습니다.")],
                "filtered_cards": [],
                "_has_error": True,
                "_error_message": "카드 필터링 중 오류가 발생했습니다.",
                "_error_type": "DATA",
            }

        if not filtered:
            return {
                "messages": [AIMessage(content=f"월 소비 {total_budget:,}원 기준으로 조건을 충족하는 카드가 없습니다.")],
                "filtered_cards": [],
            }
        return {"filtered_cards": filtered}

    # calculate_benefits가 asyncio.gather를 사용하는 코루틴으로 변경되었으므로
    # LangGraph가 올바르게 await할 수 있도록 이 노드도 async로 선언함.
    async def calculate_benefits_node(state: AgentState):
        filtered_cards = state.get("filtered_cards", [])
        category_spending = state.get("category_spending", {})
        total_budget = state.get("total_budget", 0)
        try:
            calc_results = await recommend_service.calculate_benefits(
                filtered_cards, total_budget, category_spending
            )
            return {"calc_results": calc_results}
        except Exception as e:
            # 계산 실패 → error_recovery로 라우팅
            logger.exception("[calculate_benefits_node] 예외 발생: {}", repr(e))
            return {
                "_has_error": True,
                "_error_message": "혜택 계산 중 오류가 발생했습니다.",
                "calc_results": [],
                "_error_type": "DATA",
            }

    async def rank_and_explain_node(state: AgentState):
        calc_results = state.get("calc_results", [])
        category_spending = state.get("category_spending", {})
        total_budget = state.get("total_budget", 0)

        ranked = recommend_service.rank_top(calc_results, top_n=3)

        if not ranked:
            return {
                "messages": [AIMessage(content="혜택 계산 결과가 없습니다.")],
                "recommended_cards": [],
            }

        # 모든 상위 카드의 Digest를 로드하여 상세 설명 생성에 대비
        digests = []
        top_digest = ""
        try:
            digests = [digest_repo.get_digest(card.get("_card_data", {})) for card in ranked]
            top_digest = digests[0] if digests else ""
        except Exception as e:
            logger.warning("[rank_and_explain_node] digest 로드 실패: %s", repr(e))
            digests = [""] * len(ranked)

        try:
            explanation = await explain_service.explain(total_budget, category_spending, ranked, top_digest)
            if not explanation or not explanation.strip():
                raise ValueError("LLM이 빈 응답을 반환했습니다.")
        except Exception as e:
            # LLM 실패 → error_recovery로 라우팅 (카드 목록은 state에 보존)
            logger.warning("[rank_and_explain_node] LLM 실패, error_recovery로 이동: %s", repr(e))
            try:
                # 상세 Tracing 기능이 포함된 빌더 호출 (LLM 설명 없이 상세 내역만)
                recommended_cards = explain_service.build_recommended_cards(ranked, "", digests)
            except Exception:
                logger.exception("[rank_and_explain_node] build_recommended_cards 실패")
                recommended_cards = []
            return {
                "_has_error": True,
                "_error_message": _LLM_FAILURE_MESSAGE,
                "_error_type": "LLM",
                "_fallback": True,
                "recommended_cards": recommended_cards,
                "last_raw_data": explain_service.to_raw_data(recommended_cards) if recommended_cards else "",
            }

        try:
            recommended_cards = explain_service.build_recommended_cards(ranked, explanation, digests)
        except Exception:
            logger.exception("[rank_and_explain_node] build_recommended_cards 실패")
            return {
                "_has_error": True,
                "_error_message": _LLM_FAILURE_MESSAGE,
                "_error_type": "LLM",
                "_fallback": True,
                "recommended_cards": [],
            }
        return {
            "messages": [AIMessage(content=explanation)],
            "recommended_cards": recommended_cards,
            "last_raw_data": explain_service.to_raw_data(recommended_cards),
        }


    async def answer_qa_node(state: AgentState):
        raw_data = state.get("last_raw_data", "이전 검색 결과 원본이 존재하지 않습니다.")
        messages = state.get("messages") or []
        last_message = messages[-1].content if messages else ""
        try:
            response = await explain_service.answer_qa(raw_data, last_message)
            if not response or not response.strip():
                raise ValueError("LLM이 빈 응답을 반환했습니다.")
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            logger.warning("[answer_qa_node] LLM 실패, error_recovery로 이동: %s", repr(e))
            return {
                "_has_error": True,
                "_error_message": _LLM_FAILURE_MESSAGE,
                "_error_type": "LLM",
                "_fallback": True,
            }

    # -----------------------------------------------------------------------
    # 라우팅 함수
    # -----------------------------------------------------------------------
    def check_filter_result(state: AgentState) -> Literal["calculate", "no_results", "error"]:
        if state.get("_has_error"):
            return "error"
        filtered = state.get("filtered_cards", [])
        return "calculate" if filtered else "no_results"

    def check_calculate_result(state: AgentState) -> Literal["explain", "error"]:
        if state.get("_has_error"):
            return "error"
        return "explain"

    def check_explain_result(state: AgentState) -> Literal["done", "error"]:
        if state.get("_has_error"):
            return "error"
        return "done"

    def check_qa_result(state: AgentState) -> Literal["done", "error"]:
        if state.get("_has_error"):
            return "error"
        return "done"

    # -----------------------------------------------------------------------
    # 그래프 조립
    # -----------------------------------------------------------------------
    workflow = StateGraph(AgentState)
    workflow.add_node("filter_cards", filter_cards_node)
    workflow.add_node("calculate_benefits", calculate_benefits_node)
    workflow.add_node("rank_and_explain", rank_and_explain_node)
    workflow.add_node("answer_qa", answer_qa_node)
    workflow.add_node("error_recovery", error_recovery_node)

    workflow.add_edge(START, "filter_cards")
    workflow.add_conditional_edges(
        "filter_cards",
        check_filter_result,
        {"calculate": "calculate_benefits", "no_results": END, "error": "error_recovery"},
    )
    workflow.add_conditional_edges(
        "calculate_benefits",
        check_calculate_result,
        {"explain": "rank_and_explain", "error": "error_recovery"},
    )
    workflow.add_conditional_edges(
        "rank_and_explain",
        check_explain_result,
        {"done": END, "error": "error_recovery"},
    )
    workflow.add_conditional_edges(
        "answer_qa",
        check_qa_result,
        {"done": END, "error": "error_recovery"},
    )
    workflow.add_edge("error_recovery", END)

    memory = InMemorySaver()
    return workflow.compile(checkpointer=memory)
