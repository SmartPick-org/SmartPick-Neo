from typing import Any, Dict, List, TypedDict


class CardData(TypedDict, total=False):
    card_meta: Dict[str, Any]
    benefit_groups: List[Dict[str, Any]]
    benefits: List[Dict[str, Any]]
    _file_path: str
    _raw_v3: Dict[str, Any]
    _card_categories: set[str]
