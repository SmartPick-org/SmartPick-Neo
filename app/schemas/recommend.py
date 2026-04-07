from typing import Dict, List, Any, Union

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import CategoryEnum, SubCategoryEnum


class RecommendRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액")
    category_spending: Dict[CategoryEnum, Union[int, Dict[str, Union[int, str]]]] = Field(
        ..., 
        description="카테고리별 월 소비 금액 (단일 금액 또는 서브 카테고리 비율 표기)", 
        examples=[
        {
            "Coffee": {
                "total": 50000,
                "cafe": "75%",
                "bakery": "25%"
            },
            "Traffic": {
                "total": 100000,
                "transit": "100%"
            },
            "Shopping": 150000,
        },
        {
            "Food": 200000,
            "Life": 120000,
            "Cultural": {"total": 80000, "cinema": "50%", "ott": "50%"},
            "Others": 30000,
        },
    ])

    @model_validator(mode="after")
    def validate_sub_categories(self) -> 'RecommendRequest':
        if not self.category_spending:
            return self
            
        for cat, amount_info in self.category_spending.items():
            if isinstance(amount_info, dict):
                if "total" not in amount_info:
                    raise ValueError(f"Category '{cat.value}' must contain a 'total' key.")
                
                for sub_key in amount_info.keys():
                    if sub_key == "total":
                        continue
                    try:
                        SubCategoryEnum(sub_key)
                    except ValueError:
                        raise ValueError(f"Invalid sub_category '{sub_key}' in category '{cat.value}'.")
        return self

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
    category: str = Field(..., description="카테고리", examples=["Coffee"])
    monthly_discount_krw: int = Field(..., description="월 할인 금액", examples=[10000])
    discount_info: Dict[SubCategoryEnum, int] = Field(
        default_factory=dict, 
        description="서브 카테고리별 할인 금액", 
        json_schema_extra={
            "examples": [
                {SubCategoryEnum.CAFE: 3000, SubCategoryEnum.BAKERY: 2000}
            ]
        }
    )
    warnings: List[str] | None = Field(None, description="주의사항", examples=[["전월 실적 미달"]])


class RecommendCard(BaseModel):
    card_name: str = Field(..., description="카드 이름", examples=["현대카드 T3 Edition2"])
    card_company: str = Field(..., description="카드 회사", examples=["현대카드"])
    card_id: str = Field(..., description="카드 고유 식별자", examples=["shinhan_mr_life"])
    annual_fee: int = Field(..., description="연회비", examples=[10000])
    minimum_performance: int = Field(..., description="전월 실적", examples=[100000])
    expected_monthly_benefit: int = Field(..., description="기대 월 할인/적립 금액", examples=[10000])
    category_breakdown: List[CategoryBreakdown] = Field(..., description="카테고리별 할인/적립 금액")
    explanation: str = Field(..., description="이 카드가 1순위로 추천된 이유", examples=["이 카드는 커피, 교통, 쇼핑에서 높은 할인 혜택을 제공합니다."])


class RecommendResponse(BaseModel):
    recommended_cards: List[RecommendCard] = Field(..., description="추천 카드 목록")
    explanation: str = Field(..., description="이 카드가 1순위로 추천된 이유", examples=["이 카드는 커피, 교통, 쇼핑에서 높은 할인 혜택을 제공합니다."])


class QARequest(BaseModel):
    raw_data: str = Field(..., description="추천 결과 원본 JSON 문자열")
    question: str = Field(..., description="유저 질문")

    def masked_dict(self) -> dict:
        data = self.model_dump()
        # raw_data는 내용이 길고 사용자 예산을 포함할 수 있으므로 절삭/마스킹
        data["raw_data"] = "[MASKED_JSON_DATA]" 
        return data


class QAResponse(BaseModel):
    answer: str = Field(..., description="답변")
