import json
from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.adapters import adapt_v3_for_calculator
from app.domain.models import CardData


class CardRepository(ABC):
    @abstractmethod
    def list_cards(self) -> list[CardData]:
        raise NotImplementedError


class DatasetCardRepository(CardRepository):
    def __init__(self, datasets_dir: Path):
        self.datasets_dir = datasets_dir
        self._cache: list[CardData] | None = None

    def list_cards(self) -> list[CardData]:
        if self._cache is not None:
            return self._cache

        all_cards: list[CardData] = []
        for company_dir in self.datasets_dir.iterdir():
            if not company_dir.is_dir():
                continue
            for json_file in company_dir.rglob("*.json"):
                raw = json.loads(json_file.read_text(encoding="utf-8"))
                if not raw.get("card_meta", {}).get("card_name"):
                    continue

                adapted = adapt_v3_for_calculator(raw)
                adapted["_file_path"] = str(json_file)
                adapted["_raw_v3"] = raw

                card_categories: set[str] = set()
                for benefit in adapted.get("benefits", []):
                    category = benefit.get("category", "")
                    if category and category != "General":
                        card_categories.add(category)
                    elif category == "General":
                        card_categories.add(category)
                adapted["_card_categories"] = card_categories

                all_cards.append(adapted)

        self._cache = all_cards
        return all_cards


class DBCardRepository(CardRepository):
    """Supabase DB에서 카드 데이터를 조회하는 Repository.

    테이블 구조 (Mk2 스키마 기준):
      - cards: card_id, card_name, card_company, annual_fee_domestic,
               annual_fee_foreign, brand, file_path, ...
      - card_benefits: card_id, category, merchant, discount_rate,
                       max_discount, min_spend, ...
    """

    def __init__(self):
        from app.core.database import get_supabase
        self._db = get_supabase()
        self._cache: list[CardData] | None = None

    def list_cards(self) -> list[CardData]:
        if self._cache is not None:
            return self._cache

        # 카드 기본 정보 조회
        cards_res = self._db.table("cards").select("*").execute()
        cards_rows: list[dict] = cards_res.data or []

        # 카드 혜택 정보 조회
        benefits_res = self._db.table("card_benefits").select("*").execute()
        benefits_rows: list[dict] = benefits_res.data or []

        # card_id 기준으로 혜택 그룹핑
        benefits_by_card: dict[str, list[dict]] = {}
        for b in benefits_rows:
            cid = b.get("card_id", "")
            benefits_by_card.setdefault(cid, []).append(b)

        all_cards: list[CardData] = []
        for row in cards_rows:
            card_id = row.get("card_id", "")
            card_data: CardData = {
                "card_meta": {
                    "card_id": card_id,
                    "card_name": row.get("card_name", ""),
                    "card_company": row.get("card_company", ""),
                    "annual_fee_domestic": row.get("annual_fee_domestic", 0),
                    "annual_fee_foreign": row.get("annual_fee_foreign", 0),
                    "brand": row.get("brand", ""),
                    "file_path": row.get("file_path", ""),
                },
                "benefits": benefits_by_card.get(card_id, []),
                "file_path": row.get("file_path", ""),
            }
            all_cards.append(card_data)

        self._cache = all_cards
        return all_cards
