import json
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from app.core.discord import notify_discord_sync
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
        for json_file in self.datasets_dir.glob("**/*.json"):
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            if not raw.get("card_meta", {}).get("card_name"):
                continue

            # inject card_slug from filename if not already present
            if not raw["card_meta"].get("card_slug"):
                raw["card_meta"]["card_slug"] = json_file.stem

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

    테이블 구조:
      - cards: id, card_slug, card_name, card_company, annual_fee,
               min_performance, reward_currency, currency_rate, image_url
      - card_benefit_groups: id, card_id, group_slug, group_name, group_type, limit_amount
      - card_benefits: id, group_id, benefit_slug, category, content,
                       reward_type, calculation_rule (jsonb), transaction_conditions (jsonb), ui_warnings
    """

    def __init__(self):
        from app.core.database import get_supabase
        self._db = get_supabase()
        self._cache: list[CardData] | None = None

    def list_cards(self) -> list[CardData]:
        if self._cache is not None:
            return self._cache

        cards_rows: list[dict] = self._db.table("cards").select("*").execute().data or []
        groups_rows: list[dict] = self._db.table("card_benefit_groups").select("*").execute().data or []
        benefits_rows: list[dict] = self._db.table("card_benefits").select("*").execute().data or []

        # group_id → benefits
        benefits_by_group: dict[str, list[dict]] = {}
        for b in benefits_rows:
            gid = b.get("group_id", "")
            benefits_by_group.setdefault(gid, []).append(b)

        # card_id → groups
        groups_by_card: dict[str, list[dict]] = {}
        for g in groups_rows:
            cid = g.get("card_id", "")
            groups_by_card.setdefault(cid, []).append(g)

        all_cards: list[CardData] = []
        for row in cards_rows:
            card_id = row.get("id", "")
            card_groups = groups_by_card.get(card_id, [])

            benefit_groups = [
                {
                    "group_id": g["id"],
                    "group_slug": g.get("group_slug"),
                    "group_name": g.get("group_name"),
                    "group_type": g.get("group_type"),
                    "limit_amount": g.get("limit_amount"),
                }
                for g in card_groups
            ]

            benefits = [
                {
                    "group_id": b.get("group_id"),
                    "benefit_id": b.get("benefit_slug"),
                    "benefit_slug": b.get("benefit_slug"),
                    "category": b.get("category"),
                    "content": b.get("content"),
                    "reward_type": b.get("reward_type"),
                    "calculation_rule": b.get("calculation_rule") or {},
                    "transaction_conditions": b.get("transaction_conditions") or {},
                    "ui_warnings": b.get("ui_warnings") or [],
                }
                for g in card_groups
                for b in benefits_by_group.get(g["id"], [])
            ]

            raw: CardData = {
                "card_meta": {
                    "card_id": card_id,
                    "card_slug": row.get("card_slug"),
                    "card_name": row.get("card_name", ""),
                    "card_company": row.get("card_company"),
                    "annual_fee": row.get("annual_fee", 0),
                    "min_performance": row.get("min_performance", 0),
                    "reward_currency": row.get("reward_currency", "KRW"),
                    "currency_to_krw_rate": row.get("currency_rate", 1.0),
                    "image_url": row.get("image_url"),
                },
                "benefit_groups": benefit_groups,
                "benefits": benefits,
            }

            adapted = adapt_v3_for_calculator(raw)
            adapted["_card_categories"] = {
                b.get("category", "")
                for b in benefits
                if b.get("category")
            }
            all_cards.append(adapted)

        self._cache = all_cards
        return all_cards


class FallbackCardRepository(CardRepository):
    """DB를 우선 시도하고, 실패하면 로컬 JSON 파일로 폴백하는 Repository."""

    def __init__(self, datasets_dir: Path):
        self._datasets_dir = datasets_dir
        self._cache: list[CardData] | None = None

    def list_cards(self) -> list[CardData]:
        if self._cache is not None:
            return self._cache

        try:
            db_repo = DBCardRepository()
            cards = db_repo.list_cards()
            if cards:
                logger.info(f"[FallbackCardRepository] DB에서 카드 {len(cards)}개 로드 성공")
                self._cache = cards
                return cards
            exc = RuntimeError("DB에서 카드 0개 반환")
            logger.warning("[FallbackCardRepository] {} → 로컬 데이터셋으로 폴백", exc)
            notify_discord_sync(
                exc,
                context="FallbackCardRepository.list_cards — DB returned 0 cards",
            )
        except Exception as e:
            logger.warning(f"[FallbackCardRepository] DB 조회 실패: {e} → 로컬 데이터셋으로 폴백")
            notify_discord_sync(
                e,
                context="FallbackCardRepository.list_cards — DB fetch failed",
            )

        self._cache = DatasetCardRepository(self._datasets_dir).list_cards()
        return self._cache
