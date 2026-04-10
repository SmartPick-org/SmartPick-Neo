from typing import Dict, List, Any, Union

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import CategoryEnum, SubCategoryEnum


class RecommendRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액", examples=[500000])
    category_spending: Dict[CategoryEnum, Union[int, Dict[str, Union[int, str]]]] = Field(
        ..., 
        description="""카테고리별 월 소비 금액 데이터입니다.
- **키**: `CategoryEnum` 값 (예: 'Food', 'Shopping', 'Coffee' 등)
- **값 형식**:
    1. **단일 숫자 (int)**: 해당 카테고리의 전체 소비 금액 (예: `150000`)
    2. **상세 객체 (dict)**: 특정 업종별 비중을 포함한 상세 내역
        - `total`: 해당 카테고리의 총 소비 금액 (**필수**, int)
        - 그 외 키: `SubCategoryEnum` 값 (예: 'cafe', 'delivery' 등). 값은 해당 카테고리 내 비중(예: `"75%"`) 또는 금액(int)을 입력합니다.
        - *참고*: 서브 카테고리는 가급적 해당 부모 카테고리에 속하는 항목을 사용하세요.""", 
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
            "Food": {
                "total": 300000,
                "delivery": "30%",
                "restaurant": "70%"
            }
        }
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
        description="""서브 카테고리별 할인 금액 상세 내역입니다.
- **키**: `SubCategoryEnum` 값 (예: 'cafe', 'transit' 등)
- **값**: 해당 업종에서 할인받은 원화(KRW) 금액""", 
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
    explanation: str = Field(..., description="이 카드의 주요 혜택 및 주의 사항", examples=["[1순위] 신한카드 Mr.Life (신한카드)\n연회비: 15,000원 | 월 예상 할인: 약 99,000원 | 연 순이익 추정: 1,185,000원\n  - Food: 70,000원\n    ⚠ 1회 승인금액 1만원까지 할인 적용(1회 최대 1천원 할인)\n    ⚠ 신규 발급 회원은 카드사용 등록월 익월말까지 실적 상관없이 할인 제공\n"])


class RecommendResponse(BaseModel):
    recommended_cards: List[RecommendCard] = Field(..., description="추천 카드 목록")
    explanation: str = Field(..., description="이 카드가 1순위로 추천된 이유", examples=["이 카드는 커피, 교통, 쇼핑에서 높은 할인 혜택을 제공합니다."])


class CompareRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액", examples=[500000])
    category_spending: Dict[CategoryEnum, Union[int, Dict[str, Union[int, str]]]] = Field(
        ...,
        description="카테고리별 월 소비 금액 (RecommendRequest와 동일한 형식)",
        examples=[{"Coffee": 50000, "Traffic": 100000}],
    )
    current_card_id: str = Field(..., description="비교할 기존 카드 ID", examples=["shinhan_mr_life"])

    @model_validator(mode="after")
    def validate_sub_categories(self) -> 'CompareRequest':
        if not self.category_spending:
            return self

        for cat, amount_info in self.category_spending.items():
            if isinstance(amount_info, dict):
                if "total" not in amount_info:
                    raise ValueError(f"Category '{cat.value}' must contain a 'total' key.")

                from app.schemas.enums import SubCategoryEnum
                for sub_key in amount_info.keys():
                    if sub_key == "total":
                        continue
                    try:
                        SubCategoryEnum(sub_key)
                    except ValueError:
                        raise ValueError(f"Invalid sub_category '{sub_key}' in category '{cat.value}'.")
        return self


class CategoryComparison(BaseModel):
    category: str = Field(..., description="카테고리명", examples=["Coffee"])
    current_benefit: int = Field(..., description="기존 카드 월 혜택 금액", examples=[2000])
    recommended_benefit: int = Field(..., description="추천 카드 월 혜택 금액", examples=[5000])
    diff: int = Field(..., description="추천 카드 혜택 - 기존 카드 혜택", examples=[3000])


class CompareResponse(BaseModel):
    current_card: RecommendCard = Field(..., description="기존 카드 혜택 계산 결과")
    recommended_card: RecommendCard = Field(..., description="1순위 추천 카드")
    monthly_diff: int = Field(..., description="월 혜택 차이 (추천 - 기존)", examples=[15000])
    yearly_diff: int = Field(..., description="연간 혜택 차이 (추천 - 기존)", examples=[180000])
    category_comparison: List[CategoryComparison] = Field(..., description="카테고리별 혜택 비교")
    explanation: str = Field(..., description="비교 큐레이션 텍스트")


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
