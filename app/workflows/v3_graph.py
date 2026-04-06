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


def build_graph(
    recommend_service: CardRecommendService,
    explain_service: ExplainService,
    digest_repo: DigestRepository,
):
    def filter_cards_node(state: AgentState):
        total_budget = state.get("total_budget", 0)
        category_spending = state.get("category_spending", {})
        filtered = recommend_service.filter_cards(total_budget, category_spending)
        if not filtered:
            return {
                "messages": [AIMessage(content=f"월 소비 {total_budget:,}원 기준으로 조건을 충족하는 카드가 없습니다.")],
                "filtered_cards": [],
            }
        return {"filtered_cards": filtered}

    def calculate_benefits_node(state: AgentState):
        filtered_cards = state.get("filtered_cards", [])
        category_spending = state.get("category_spending", {})
        total_budget = state.get("total_budget", 0)
        calc_results = recommend_service.calculate_benefits(filtered_cards, total_budget, category_spending)
        return {"calc_results": calc_results}

    def rank_and_explain_node(state: AgentState):
        calc_results = state.get("calc_results", [])
        category_spending = state.get("category_spending", {})
        total_budget = state.get("total_budget", 0)

        ranked = recommend_service.rank_top(calc_results, top_n=3)
        card_digest = digest_repo.get_digest(ranked[0].get("_card_data", {})) if ranked else ""
        explanation = explain_service.explain(total_budget, category_spending, ranked, card_digest)
        recommended_cards = explain_service.build_recommended_cards(ranked, explanation)

        return {
            "messages": [AIMessage(content=explanation)],
            "recommended_cards": recommended_cards,
            "last_raw_data": explain_service.to_raw_data(recommended_cards),
        }

    def answer_qa_node(state: AgentState):
        raw_data = state.get("last_raw_data", "이전 검색 결과 원본이 존재하지 않습니다.")
        last_message = state["messages"][-1].content if state.get("messages") else ""
        response = explain_service.answer_qa(raw_data, last_message)
        return {"messages": [AIMessage(content=response)]}

    def check_filter_result(state: AgentState) -> Literal["calculate", "no_results"]:
        filtered = state.get("filtered_cards", [])
        return "calculate" if filtered else "no_results"

    workflow = StateGraph(AgentState)
    workflow.add_node("filter_cards", filter_cards_node)
    workflow.add_node("calculate_benefits", calculate_benefits_node)
    workflow.add_node("rank_and_explain", rank_and_explain_node)
    workflow.add_node("answer_qa", answer_qa_node)

    workflow.add_edge(START, "filter_cards")
    workflow.add_conditional_edges(
        "filter_cards",
        check_filter_result,
        {"calculate": "calculate_benefits", "no_results": END},
    )
    workflow.add_edge("calculate_benefits", "rank_and_explain")
    workflow.add_edge("rank_and_explain", END)
    workflow.add_edge("answer_qa", END)

    memory = InMemorySaver()
    return workflow.compile(checkpointer=memory)
