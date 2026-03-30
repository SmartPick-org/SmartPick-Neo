from typing import Dict, List

from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액")
    category_spending: Dict[str, int] = Field(..., description="카테고리별 월 소비 금액")


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


class QAResponse(BaseModel):
    answer: str
