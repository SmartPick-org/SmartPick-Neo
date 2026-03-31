import json
from typing import Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from app.prompts import EXPLAIN_PROMPT, QA_PROMPT


class ExplainService:
    def __init__(self, llm):
        self.llm = llm

    def build_user_spending(self, total_budget: int, category_spending: Dict[str, int]) -> str:
        lines = [f"월 총 소비: {total_budget:,}원"]
        for category, amount in category_spending.items():
            lines.append(f"- {category}: 월 {amount:,}원")
        return "\n".join(lines)

    def build_calc_summary(self, top_card: dict) -> str:
        breakdown_lines = []
        for cb in top_card.get("category_breakdown", []):
            breakdown_lines.append(f"  - {cb['category']}: {cb['monthly_discount_krw']:,}원")

        return (
            f"카드: {top_card['card_name']} ({top_card['card_company']})\n"
            f"연회비: {top_card['annual_fee']:,}원\n"
            f"월 예상 할인: {top_card['expected_monthly_benefit']:,}원 | "
            f"연간 예상: {top_card['expected_yearly_benefit']:,}원\n"
            + "\n".join(breakdown_lines)
        )

    def explain(self, total_budget: int, category_spending: Dict[str, int], ranked: List[dict], card_digest: str) -> str:
        if not ranked:
            return "혜택 계산 결과가 없습니다."

        top1 = ranked[0]
        user_spending = self.build_user_spending(total_budget, category_spending)
        calc_summary = self.build_calc_summary(top1)

        explain_prompt = EXPLAIN_PROMPT.format(
            user_spending=user_spending,
            card_digest=card_digest,
            calc_summary=calc_summary,
        )
        return self.llm.invoke([SystemMessage(content=explain_prompt)]).content

    def answer_qa(self, raw_data: str, question: str) -> str:
        qa_prompt = QA_PROMPT.format(raw_data=raw_data)
        response = self.llm.invoke(
            [
                SystemMessage(content=qa_prompt),
                HumanMessage(content=question),
            ]
        )
        return response.content

    @staticmethod
    def build_recommended_cards(ranked: List[dict], explanation: str) -> List[dict]:
        return [
            {
                "card_name": card["card_name"],
                "card_company": card["card_company"],
                "card_id": card["card_id"],
                "annual_fee": card["annual_fee"],
                "minimum_performance": card["minimum_performance"],
                "expected_monthly_benefit": card["expected_monthly_benefit"],
                "category_breakdown": card["category_breakdown"],
                "explanation": explanation if idx == 0 else "",
            }
            for idx, card in enumerate(ranked)
        ]

    @staticmethod
    def to_raw_data(recommended_cards: List[dict]) -> str:
        return json.dumps(recommended_cards, ensure_ascii=False)
