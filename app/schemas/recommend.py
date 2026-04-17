from typing import Dict, List, Any, Union

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import CategoryEnum, SubCategoryEnum



class RecommendRequest(BaseModel):
    total_budget: int = Field(..., description="월 총 소비 금액", examples=[500000])

    top_n: int = Field(
        5,
        ge=1,
        le=10,
        description="반환할 추천 카드 수 (기본 5장, 최대 10장)",
        examples=[5],
    )
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


class BenefitTraceItem(BaseModel):
    """
    개별 혜택의 산출 영수증 항목.
    UI에서 혜택 그룹화 및 한글 레이블링을 위해 category/sub_category 포함.
    """
    benefit_id: str = Field(
        ...,
        description="혜택 고유 ID. `/cards/recalculate` 의 `excluded_benefit_ids` 에 이 값을 담아 보내면 해당 혜택이 제외됩니다.",
        examples=["shinhan_mr_life_b_food_restaurant"]
    )
    content: str = Field(
        ...,
        description="혜택 설명 문자열. 영수증 UI에 그대로 표시할 텍스트입니다.",
        examples=["DAY(07~15시) 음식점 10% 할인"]
    )
    category: str = Field(
        ...,
        description="혜택 카테고리. UI 혜택 그룹화 및 한글 레이블 매핑에 사용됩니다.",
        examples=["Food"]
    )
    sub_category: str | None = Field(
        None,
        description="혜택 서브 카테고리. 없을 경우 null 또는 'general'.",
        examples=["restaurant"]
    )
    applied_budget: int = Field(
        ...,
        description="이 혜택 계산에 배정된 유저 예산 (원). 해당 카테고리에서 이 혜택이 소비한 금액입니다.",
        examples=[210000]
    )
    yielded_discount: int = Field(
        ...,
        description="산출된 할인/적립 금액 (원). `user_choice=true` 인 항목들의 합이 `expected_monthly_benefit` 과 일치합니다.",
        examples=[21000]
    )
    user_choice: bool = Field(
        True,
        description="유저 포함 여부. `false` 이면 이 혜택의 `yielded_discount` 가 합산에서 제외됩니다. (기본값: `true`)",
        examples=[True]
    )
    warnings: List[str] | None = Field(
        None,
        description="이 혜택에 한정된 주의사항 (예: 연간 한도 초과 등)",
        examples=[["연간 3회 제한 (월간 0.25회로 안분 계산됨)"]]
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "benefit_id": "shinhan_mr_life_b_food_restaurant",
                    "content": "DAY(07~15시) 음식점 10% 할인",
                    "category": "Food",
                    "sub_category": "restaurant",
                    "applied_budget": 210000,
                    "yielded_discount": 21000,
                    "user_choice": True
                }
            ]
        }
    }


class RecommendCard(BaseModel):
    card_name: str = Field(..., description="카드 이름", examples=["현대카드 T3 Edition2"])
    card_company: str = Field(..., description="카드 회사", examples=["현대카드"])
    card_id: str = Field(..., description="카드 고유 식별자", examples=["shinhan_mr_life"])
    annual_fee: int = Field(..., description="연회비", examples=[10000])
    minimum_performance: int = Field(..., description="전월 실적", examples=[100000])
    expected_monthly_benefit: int = Field(..., description="기대 월 할인/적립 금액", examples=[10000])
    # Backward-compatible: older clients may omit this in payloads (e.g. /recalculate request).
    expected_yearly_benefit: int = Field(
        0,
        description="기대 연간 할인/적립 금액(연회비 차감 전). 누락 시 월*12로 보정됩니다.",
        examples=[120000],
    )
    category_breakdown: List[CategoryBreakdown] = Field(..., description="카테고리별 할인/적립 금액")
    applied_benefits_trace: List[BenefitTraceItem] = Field(
        default_factory=list,
        description="혜택별 산출 영수증 (계산 근거 추적 및 체크박스 토글용)"
    )
    explanation: str = Field(..., description="이 카드의 주요 혜택 및 주의 사항", examples=["[1순위] 신한카드 Mr.Life (신한카드)\n연회비: 15,000원 | 월 예상 할인: 약 99,000원 | 연 순이익 추정: 1,185,000원\n  - Food: 70,000원\n    ⚠ 1회 승인금액 1만원까지 할인 적용(1회 최대 1천원 할인)\n    ⚠ 신규 발급 회원은 카드사용 등록월 익월말까지 실적 상관없이 할인 제공\n"])

    @model_validator(mode="after")
    def _fill_yearly_benefit_if_missing(self) -> "RecommendCard":
        # If the field is missing/0 but monthly is present, infer yearly as monthly*12.
        # This avoids 422 for older payloads while keeping the meaning consistent.
        if (self.expected_yearly_benefit or 0) <= 0 and (self.expected_monthly_benefit or 0) > 0:
            self.expected_yearly_benefit = int(self.expected_monthly_benefit) * 12
        return self


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
    recommended_cards: List[RecommendCard] = Field(..., description="기존 카드보다 혜택이 큰 추천 카드 목록 (혜택 내림차순)")
    recommended_card: RecommendCard = Field(..., description="1순위 추천 카드 (하위 호환성 유지용)")
    monthly_diff: int = Field(..., description="월 혜택 차이 (추천 1순위 - 기존)", examples=[15000])
    yearly_diff: int = Field(..., description="연간 혜택 차이 (추천 1순위 - 기존)", examples=[180000])
    category_comparison: List[CategoryComparison] = Field(..., description="카테고리별 혜택 비교")
    explanation: str = Field(..., description="비교 큐레이션 텍스트")


class RecalculateRequest(BaseModel):
    """
    체크박스 재계산 요청 스키마입니다.
    사용자가 영수증 항목에서 특정 혜택을 제외(체크 해제)했을 때,
    해당 혜택의 할인액을 합산에서 제외하는 '단순 재계산(Shallow Recalculation)'을 수행합니다.
    한도 재배분은 없으며, 다른 혜택의 yielded_discount는 변경되지 않습니다.
    """
    total_budget: int = Field(..., description="월 총 소비 금액 (원). 정밀 한도 재계산에 필수입니다.", examples=[500000])
    category_spending: Dict[CategoryEnum, Any] = Field(
        ...,
        description="최초 추천 시 사용했던 소비 내역 데이터를 그대로 전달합니다. 정밀 재계산 시 한도 재분배에 사용됩니다.",
        examples=[{
            "Coffee": {"total": 50000, "cafe": "75%", "bakery": "25%"},
            "Food": {"total": 300000, "restaurant": "70%", "delivery": "30%"},
            "Shopping": 150000,
            "Traffic": {"total": 100000, "transit": "100%"}
        }]
    )
    recommended_cards: List[RecommendCard] = Field(
        ...,
        description="전 단계인 `/cards/recommend` 응답으로 받은 `recommended_cards` 배열 전체를 그대로 전달합니다."
    )
    excluded_benefit_ids: List[str] = Field(
        ...,
        description="사용자가 체크 해제한 혜택의 `benefit_id` 목록입니다. 이 혜택들의 `yielded_discount`가 `expected_monthly_benefit` 합산에서 제외됩니다.",
        examples=[["B_BEAUTY_001"]]
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_budget": 500000,
                    "category_spending": {"Food": 300000, "Shopping": 200000},
                    "recommended_cards": [
                        {
                            "card_name": "신한카드 Mr.Life",
                            "card_company": "신한카드",
                            "card_id": "shinhan_mr_life",
                            "annual_fee": 15000,
                            "minimum_performance": 300000,
                            "expected_monthly_benefit": 99000,
                            "category_breakdown": [
                                {"category": "Food", "monthly_discount_krw": 70000, "discount_info": {}, "warnings": []}
                            ],
                            "applied_benefits_trace": [
                                {
                                    "benefit_id": "shinhan_mr_life_b_food_restaurant",
                                    "content": "DAY(07~15시) 음식점 10% 할인",
                                    "applied_budget": 210000,
                                    "yielded_discount": 21000,
                                    "user_choice": True,
                                }
                            ],
                            "explanation": "[1순위] 신한카드 Mr.Life (신한카드)\n연회비: 15,000원 | ...",
                        }
                    ],
                    "excluded_benefit_ids": ["B_BEAUTY_001"],
                }
            ]
        }
    }


class RecalculateResponse(BaseModel):
    """
    체크박스 재계산 응답.
    `expected_monthly_benefit` 이 선택된 혜택들의 합으로 갱신되며,
    카드 순위가 재조정됩니다.
    """
    recommended_cards: List[RecommendCard] = Field(
        ...,
        description="순위 재조정된 카드 목록. `applied_benefits_trace` 의 `user_choice` 필드가 갱신된 상태입니다."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "recommended_cards": [
                        {
                            "card_name": "신한카드 Mr.Life",
                            "card_company": "신한카드",
                            "card_id": "shinhan_mr_life",
                            "annual_fee": 15000,
                            "minimum_performance": 300000,
                            "expected_monthly_benefit": 84000,
                            "category_breakdown": [
                                {"category": "Food", "monthly_discount_krw": 70000, "discount_info": {}, "warnings": []}
                            ],
                            "applied_benefits_trace": [
                                {
                                    "benefit_id": "shinhan_mr_life_b_food_restaurant",
                                    "content": "DAY(07~15시) 음식점 10% 할인",
                                    "applied_budget": 210000,
                                    "yielded_discount": 21000,
                                    "user_choice": True,
                                },
                                {
                                    "benefit_id": "B_BEAUTY_001",
                                    "content": "뷰티 5% 할인",
                                    "applied_budget": 150000,
                                    "yielded_discount": 15000,
                                    "user_choice": False,
                                },
                            ],
                            "explanation": "[1순위] 신한카드 Mr.Life (신한카드)\n...",
                        }
                    ]
                }
            ]
        }
    }


class QARequest(BaseModel):
    raw_data: str = Field(..., description="추천 결과 원본 JSON 문자열")
    question: str = Field(
        ...,
        description="유저 질문 (자연어)",
        examples=["왜 이 카드가 1순위야?"],
    )

    def masked_dict(self) -> dict:
        data = self.model_dump()
        # raw_data는 내용이 길고 사용자 예산을 포함할 수 있으므로 절삭/마스킹
        data["raw_data"] = "[MASKED_JSON_DATA]"
        return data


class QAResponse(BaseModel):
    answer: str = Field(
        ...,
        description="LLM이 raw_data를 참고해 생성한 자연어 답변",
        examples=["1순위 카드인 신한카드 Mr.Life는 식비(restaurant) 비중이 큰 소비 패턴에서 ..."],
    )
