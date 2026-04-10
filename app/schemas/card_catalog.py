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
    card_meta: dict = Field(default_factory=dict, description="원본 card_meta")
    benefits: list[dict] = Field(default_factory=list, description="원본 benefits(어댑팅된 형태)")
    benefit_groups: list[dict] = Field(default_factory=list, description="원본 benefit_groups")
    file_path: Optional[str] = Field(None, description="데이터 파일 경로(있으면)")
