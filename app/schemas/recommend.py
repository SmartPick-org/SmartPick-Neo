from typing import Dict, List

from pydantic import BaseModel, Field

from app.schemas.enums import CategoryEnum


class RecommendRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액")
    category_spending: Dict[CategoryEnum, int] = Field(..., description="카테고리별 월 소비 금액", examples=[
        {
            "Coffee": 50000,
            "Traffic": 100000,
            "Shopping": 150000,
        },
        {
            "Food": 200000,
            "Life": 120000,
            "Cultural": 80000,
            "Others": 30000,
        },
    ])

    def masked_dict(self) -> dict:
        """
        로깅 및 알림 전송용 마스킹 필터.
        민감한 예산 데이터 노출을 방지합니다.
        """
        data = self.model_dump()
        data["total_budget"] = "***"
        data["category_spending"] = {k: "***" for k in data["category_spending"].keys()}
        return data


class CategoryBreakdown(BaseModel):
    category: str
    monthly_discount_krw: int
    warnings: List[str] | None = None


class RecommendCard(BaseModel):
    card_name: str
    card_company: str
    card_id: str
    annual_fee: int
    minimum_performance: int
    expected_monthly_benefit: int
    category_breakdown: List[CategoryBreakdown]
    explanation: str = ""


class RecommendResponse(BaseModel):
    recommended_cards: List[RecommendCard]
    explanation: str


class QARequest(BaseModel):
    raw_data: str = Field(..., description="추천 결과 원본 JSON 문자열")
    question: str = Field(..., description="유저 질문")

    def masked_dict(self) -> dict:
        data = self.model_dump()
        # raw_data는 내용이 길고 사용자 예산을 포함할 수 있으므로 절삭/마스킹
        data["raw_data"] = "[MASKED_JSON_DATA]" 
        return data


class QAResponse(BaseModel):
    answer: str
