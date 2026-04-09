from typing import Dict, List, Any
from loguru import logger

from langchain_core.messages import HumanMessage, SystemMessage

from app.prompts import EXPLAIN_PROMPT, QA_PROMPT


class ExplainService:
    """
    ExplainService: 추천된 카드들의 혜택 계산 결과(RAG 데이터)를 바탕으로 
    추천 사유를 요약하고, 사용자의 추가 질문에 답변하는 서비스입니다.
    """
    def __init__(self, llm):
        from app.core.resilience import with_resilience
        self.llm = llm
        # LLM 호출부에 회복력 래퍼 적용 (비동기 처리 고려)
        self._resilient_invoke = with_resilience(self.llm.ainvoke)

    def build_user_spending(self, total_budget: int, category_spending: Dict[str, Any]) -> str:
        lines = [f"월 총 소비: {total_budget:,}원"]
        for category, amount_info in category_spending.items():
            if isinstance(amount_info, dict):
                lines.append(f"- {category}: 월 {amount_info.get('total', 0):,}원")
                for sub, ratio in amount_info.items():
                    if sub != "total":
                        lines.append(f"  └ {sub}: {ratio}")
            else:
                lines.append(f"- {category}: 월 {amount_info:,}원")
        return "\n".join(lines)

    def build_calc_summary(self, top_card: dict) -> str:
        breakdown_lines = []
        for cb in top_card.get("category_breakdown", []):
            breakdown_lines.append(f"  - {cb['category']}: {cb['monthly_discount_krw']:,}원")
            discount_info = cb.get("discount_info")
            if discount_info:
                for sub, amt in discount_info.items():
                    sub_name = sub.replace("sub_category_", "")
                    breakdown_lines.append(f"    └ {sub_name}: {amt:,}원")

        return (
            f"카드: {top_card['card_name']} ({top_card['card_company']})\n"
            f"연회비: {top_card['annual_fee']:,}원\n"
            f"월 예상 할인: {top_card['expected_monthly_benefit']:,}원 | "
            f"연간 예상: {top_card['expected_yearly_benefit']:,}원\n"
            + "\n".join(breakdown_lines)
        )

    async def explain(self, total_budget: int, category_spending: Dict[str, Any], ranked: List[dict], card_digest: str) -> str:
        if not ranked:
            return "혜택 계산 결과가 없습니다."

        top1 = ranked[0]
        user_spending = self.build_user_spending(total_budget, category_spending)
        calc_summary = self.build_calc_summary(top1)

        logger.info(f"[ExplainService] explain 시작 | 카드: {top1.get('card_name')} | 세부내역 길이: {len(card_digest)} chars")

        explain_prompt = EXPLAIN_PROMPT.format(
            user_spending=user_spending,
            card_digest=card_digest,
            calc_summary=calc_summary,
        )
        try:
            response = await self._resilient_invoke([SystemMessage(content=explain_prompt)])
            logger.info(f"[ExplainService] explain 완료 | 답변 길이: {len(str(response.content))} chars")
            return response.content
        except Exception as e:
            logger.exception(f"[ExplainService] explain 처리 중 오류 발생: {e}")
            raise

    async def answer_qa(self, raw_data: str, question: str) -> str:
        """
        추천 결과 JSON 데이터(raw_data)를 바탕으로 사용자의 자유 질문에 답변합니다.
        상세 약관이나 수수료 등 데이터에 없는 내용은 답변하지 않고 안내 멘트를 반환합니다.
        """
        logger.info(f"[ExplainService] answer_qa 시작 | 질문: {question[:50]}... | 원본 데이터 길이: {len(raw_data)} chars")
        qa_prompt = QA_PROMPT.format(raw_data=raw_data)
        try:
            response = await self._resilient_invoke(
                [
                    SystemMessage(content=qa_prompt),
                    HumanMessage(content=question),
                ]
            )
            logger.info(f"[ExplainService] answer_qa 완료 | 답변 길이: {len(str(response.content))} chars")
            return response.content
        except Exception as e:
            logger.exception(f"[ExplainService] answer_qa 처리 중 오류 발생: {e}")
            raise

    @staticmethod
    def _round_to_thousands(amount: int) -> str:
        """100원 단위에서 반올림하여 1,000원 단위로 표기 (예: 28500 -> 약 29,000)"""
        if amount == 0:
            return "0원"
        rounded = int(round(amount / 1000) * 1000)
        return f"약 {rounded:,}원"

    def _format_card_detail(self, card: dict, rank: int) -> str:
        """개별 카드의 상세 내역(Trace/Category Breakdown)을 포맷팅"""
        lines = []
        # 헤더: [N순위] 카드명 (카드사)
        prefix = f"[{rank}순위] "
        lines.append(f"{prefix}{card['card_name']} ({card['card_company']})")
        
        # 기본 정보: 연회비 | 월 예상 할인 | 연 순이익 추정
        annual_fee = f"{card['annual_fee']:,}원"
        # 월 예상 할인은 1000원 단위 반올림 적용
        monthly_benefit = self._round_to_thousands(card['expected_monthly_benefit'])
        # 연간 혜택은 이미 원 단위이므로 콤마 포맷팅만 (회원님 예시 참고)
        yearly_benefit = f"{card['expected_yearly_benefit']:,}원"
        
        lines.append(f"연회비: {annual_fee} | 월 예상 할인: {monthly_benefit} | 연 순이익 추정: {yearly_benefit}")
        
        # 카테고리별 상세 내역
        for cb in card.get("category_breakdown", []):
            cat_benefit = f"{cb['monthly_discount_krw']:,}원"
            lines.append(f"  - {cb['category']}: {cat_benefit}")
            
            # 주의사항(Warnings) 추가
            for warning in cb.get("warnings", []):
                lines.append(f"    ⚠ {warning}")
        
        return "\n".join(lines)

    def build_recommended_cards(self, ranked: List[dict], explanation: str, card_digests: List[str]) -> List[dict]:
        """
        모든 추천 카드에 대해 explanation 필드를 상세화합니다.
        각 카드의 explanation 필드에는 해당 카드의 상세 내역(detail_text)만 포함됩니다.
        (바깥 공통 explanation은 중복 방지를 위해 포함하지 않음)
        """
        results = []
        for idx, card in enumerate(ranked):
            rank = idx + 1
            final_explanation = self._format_card_detail(card, rank)
            
            results.append({
                "card_name": card["card_name"],
                "card_company": card["card_company"],
                "card_id": card["card_id"],
                "annual_fee": card["annual_fee"],
                "minimum_performance": card["minimum_performance"],
                "expected_monthly_benefit": card["expected_monthly_benefit"],
                "category_breakdown": card["category_breakdown"],
                "explanation": final_explanation,
            })
        return results

    @staticmethod
    def to_raw_data(recommended_cards: List[dict]) -> str:
        import json
        return json.dumps(recommended_cards, ensure_ascii=False)
