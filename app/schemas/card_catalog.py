from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CardCatalogItem(BaseModel):
    card_id: str = Field(..., description="카드 고유 식별자", examples=["kb_star"])
    card_name: str = Field(..., description="카드 이름", examples=["KB국민 Star카드"])
    card_company: str = Field(..., description="카드 회사", examples=["KB국민카드"])
    annual_fee: int = Field(0, description="연회비", examples=[7000])
    minimum_performance: int = Field(0, description="전월 실적", examples=[500000])
    categories: List[str] = Field(default_factory=list, description="카드 혜택 카테고리 목록")


class CardCatalogResponse(BaseModel):
    cards: List[CardCatalogItem] = Field(..., description="카드 목록")
    total: int = Field(..., description="필터 적용 후 총 개수", examples=[123])
    offset: int = Field(0, description="오프셋", examples=[0])
    limit: int = Field(50, description="페이지 크기", examples=[50])


class CardDetailResponse(BaseModel):
    """
    프론트에서 '선택한 기존 카드' 상세를 띄우거나,
    비교/설명 화면에서 추가 정보를 필요로 할 때 사용합니다.
    """

    card_id: str
    card_name: str
    card_company: str
    annual_fee: int = 0
    minimum_performance: int = 0
    categories: List[str] = Field(default_factory=list)
    card_meta: dict = Field(
        default_factory=dict,
        description="원본 card_meta — 카드 기본 메타데이터",
        examples=[
            {
                "card_id": "shinhan_deep_oil",
                "card_name": "신한카드 Deep Oil",
                "card_company": "SHINHAN",
                "card_slug": "shinhan_deep_oil",
                "annual_fee_domestic": 10000,
                "annual_fee_international": 13000,
                "annual_fee": 10000,
                "minimum_performance": 300000,
                "performance_excluded_categories": ["Fuel", "Tax"],
                "reward_currency": "KRW",
                "currency_to_krw_rate": 1.0,
            }
        ],
    )
    benefits: list[dict] = Field(
        default_factory=list,
        description="원본 benefits(어댑팅된 형태) — 카드의 개별 혜택 목록",
        examples=[
            [
                {
                    "benefit_id": "B_FUEL_10",
                    "group_id": "G_SHARED_LIMIT_FUEL",
                    "category": "Traffic",
                    "sub_category": "fuel",
                    "reward_type": "DIRECT_FINANCIAL",
                    "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                    "calculation_rule": {
                        "calc_type": "PERCENTAGE",
                        "benefit_rate": 0.1,
                        "fallback_rate": 0.0,
                        "monthly_benefit_limit": None,
                        "annual_benefit_limit": None,
                    },
                    "transaction_conditions": {
                        "min_payment_amount": 0,
                        "max_count_per_month": None,
                    },
                    "tier_conditions": [
                        {
                            "min_prev_performance": 300000,
                            "benefit_rate": 0.1,
                            "monthly_benefit_limit": 150000,
                        }
                    ],
                    "conditional_metadata": {
                        "warnings": [
                            "휘발유, 등유, 경유에 대해서만 할인이 제공되며, LPG는 할인 제외됩니다."
                        ],
                        "excludes_from_performance": True,
                    },
                }
            ]
        ],
    )
    benefit_groups: list[dict] = Field(
        default_factory=list,
        description="원본 benefit_groups — 혜택들이 공유하는 한도/선택 그룹",
        examples=[
            [
                {
                    "group_id": "G_SHARED_LIMIT_FUEL",
                    "group_name": "주유 서비스 공유 한도",
                    "group_type": "SHARED_LIMIT",
                    "group_type_description": "SHARED_LIMIT: 그룹 내 혜택들이 한도를 공유 (2-1 공식)",
                    "choices": None,
                    "monthly_limit": 150000,
                    "annual_limit": None,
                    "top_n_count": None,
                },
                {
                    "group_id": "G_SELECTIVE_FUEL",
                    "group_name": "주유 서비스 선택 그룹",
                    "group_type": "SELECTIVE_GROUP",
                    "group_type_description": "SELECTIVE_GROUP: 필수 선택형 (2-3 공식)",
                    "choices": [
                        {"choice_id": "CHOICE_GS", "choice_name": "GS칼텍스"},
                        {"choice_id": "CHOICE_SK", "choice_name": "SK에너지"},
                    ],
                    "monthly_limit": None,
                    "annual_limit": None,
                    "top_n_count": None,
                },
            ]
        ],
    )
    file_path: Optional[str] = Field(None, description="데이터 파일 경로(있으면)")
