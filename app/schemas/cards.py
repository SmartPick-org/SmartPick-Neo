from typing import List

from pydantic import BaseModel


class CardListItem(BaseModel):
    card_id: str
    card_name: str
    card_company: str
    annual_fee: int
    minimum_performance: int
    categories: List[str]
    digest_summary: str = ""


class CardListResponse(BaseModel):
    cards: List[CardListItem]
