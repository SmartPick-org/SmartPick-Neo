"""Tests for DatasetCardRepository — JSON loading, category extraction, caching."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from app.repositories.card_repo import DatasetCardRepository


def _write_card_json(path: Path, card_id: str, card_name: str, company: str, benefits: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "card_meta": {
            "card_id": card_id,
            "card_name": card_name,
            "card_company": company,
            "reward_currency": "KRW",
            "currency_to_krw_rate": 1.0,
            "annual_fee": 0,
            "minimum_performance": 0,
        },
        "benefits": benefits or [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_list_cards_loads_json_files(tmp_path):
    """Reads all JSON files directly under the datasets dir and returns CardData list."""
    _write_card_json(tmp_path / "hyundai_x.json", "hyundai_x", "현대카드 X", "현대카드")
    _write_card_json(tmp_path / "kb_star.json", "kb_star", "KB스타카드", "KB국민카드")

    repo = DatasetCardRepository(tmp_path)
    cards = repo.list_cards()

    names = {c["card_meta"]["card_name"] for c in cards}
    assert "현대카드 X" in names
    assert "KB스타카드" in names


def test_list_cards_skips_json_without_card_name(tmp_path):
    """Files missing card_meta.card_name are silently skipped."""
    bad = tmp_path / "kb" / "bad.json"
    bad.parent.mkdir(parents=True)
    bad.write_text(json.dumps({"card_meta": {}}), encoding="utf-8")

    repo = DatasetCardRepository(tmp_path)
    assert repo.list_cards() == []


def test_list_cards_attaches_file_path(tmp_path):
    """Each card has a _file_path key pointing to the source JSON."""
    json_path = tmp_path / "hyundai_x.json"
    _write_card_json(json_path, "hyundai_x", "현대카드 X", "현대카드")

    repo = DatasetCardRepository(tmp_path)
    cards = repo.list_cards()

    assert cards[0]["_file_path"] == str(json_path)


# ---------------------------------------------------------------------------
# Category extraction
# ---------------------------------------------------------------------------

def test_list_cards_extracts_benefit_categories(tmp_path):
    """_card_categories is built from the category field of each benefit."""
    benefits = [
        {"category": "Coffee", "calculation_rule": {"calc_method": "RATE"}, "transaction_conditions": {}, "edge_case_flags": {}},
        {"category": "Shopping", "calculation_rule": {"calc_method": "RATE"}, "transaction_conditions": {}, "edge_case_flags": {}},
    ]
    _write_card_json(tmp_path / "card.json", "hyundai_x", "현대카드 X", "현대카드", benefits=benefits)

    repo = DatasetCardRepository(tmp_path)
    card = repo.list_cards()[0]

    assert "Coffee" in card["_card_categories"]
    assert "Shopping" in card["_card_categories"]


def test_list_cards_includes_general_category(tmp_path):
    """General category benefits are included in _card_categories."""
    benefits = [
        {"category": "General", "calculation_rule": {"calc_method": "RATE"}, "transaction_conditions": {}, "edge_case_flags": {}},
    ]
    _write_card_json(tmp_path / "card.json", "hyundai_x", "현대카드 X", "현대카드", benefits=benefits)

    repo = DatasetCardRepository(tmp_path)
    card = repo.list_cards()[0]

    assert "General" in card["_card_categories"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_list_cards_caches_result(tmp_path):
    """Second call returns the same list object without re-reading disk."""
    _write_card_json(tmp_path / "hyundai" / "card.json", "hyundai_x", "현대카드 X", "현대카드")

    repo = DatasetCardRepository(tmp_path)
    first = repo.list_cards()
    second = repo.list_cards()

    assert first is second
