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
                    if category and category not in ("All_Domestic", "General"):
                        card_categories.add(category)
                    elif category in ("All_Domestic", "General"):
                        card_categories.add(category)
                adapted["_card_categories"] = card_categories

                all_cards.append(adapted)

        self._cache = all_cards
        return all_cards


class DBCardRepository(CardRepository):
    def __init__(self):
        raise NotImplementedError("DB 연결 구현이 필요합니다.")

    def list_cards(self) -> list[CardData]:
        raise NotImplementedError("DB 연결 구현이 필요합니다.")
