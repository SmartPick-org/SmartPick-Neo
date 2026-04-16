"""Tests for DatasetCardRepository — JSON loading, category extraction, caching.

v4 이관 후 DatasetCardRepository는 `<datasets_dir>/<company>/*.json` 두 단계 구조를
가정합니다. test fixture도 이 구조를 따라 회사 서브디렉토리 안에 JSON 파일을 씁니다.
"""
from __future__ import annotations

import json
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
    """회사 서브디렉토리 안의 JSON을 모두 로드해서 CardData list로 반환."""
    _write_card_json(tmp_path / "hyundai" / "hyundai_x.json", "hyundai_x", "현대카드 X", "현대카드")
    _write_card_json(tmp_path / "kb" / "kb_star.json", "kb_star", "KB스타카드", "KB국민카드")

    repo = DatasetCardRepository(tmp_path)
    cards = repo.list_cards()

    names = {c["card_meta"]["card_name"] for c in cards}
    assert "현대카드 X" in names
    assert "KB스타카드" in names


def test_list_cards_skips_json_without_card_name(tmp_path):
    """card_meta.card_name이 비어 있으면 조용히 skip."""
    bad = tmp_path / "kb" / "bad.json"
    bad.parent.mkdir(parents=True)
    bad.write_text(json.dumps({"card_meta": {}}), encoding="utf-8")

    repo = DatasetCardRepository(tmp_path)
    assert repo.list_cards() == []


def test_list_cards_ignores_flat_json_outside_company_dir(tmp_path):
    """v4 구조상 회사 서브디렉토리가 아닌 위치의 JSON은 무시되어야 한다."""
    # 회사 dir 없이 바로 placed
    flat = tmp_path / "orphan.json"
    flat.write_text(
        json.dumps({"card_meta": {"card_name": "고아카드", "card_id": "orphan"}, "benefits": []}),
        encoding="utf-8",
    )

    repo = DatasetCardRepository(tmp_path)
    assert repo.list_cards() == []


def test_list_cards_attaches_file_path(tmp_path):
    """각 카드에 _file_path가 원본 JSON 경로를 가리키도록 설정됨."""
    json_path = tmp_path / "hyundai" / "hyundai_x.json"
    _write_card_json(json_path, "hyundai_x", "현대카드 X", "현대카드")

    repo = DatasetCardRepository(tmp_path)
    cards = repo.list_cards()

    assert cards[0]["_file_path"] == str(json_path)


# ---------------------------------------------------------------------------
# Category extraction
# ---------------------------------------------------------------------------

def test_list_cards_extracts_benefit_categories(tmp_path):
    """_card_categories는 각 benefit의 category 필드에서 추출."""
    benefits = [
        {"category": "Coffee", "calculation_rule": {"calc_type": "PERCENTAGE"}, "transaction_conditions": {}},
        {"category": "Shopping", "calculation_rule": {"calc_type": "PERCENTAGE"}, "transaction_conditions": {}},
    ]
    _write_card_json(tmp_path / "hyundai" / "card.json", "hyundai_x", "현대카드 X", "현대카드", benefits=benefits)

    repo = DatasetCardRepository(tmp_path)
    card = repo.list_cards()[0]

    assert "Coffee" in card["_card_categories"]
    assert "Shopping" in card["_card_categories"]


def test_list_cards_includes_general_category(tmp_path):
    """General 카테고리도 _card_categories에 포함되어야 한다."""
    benefits = [
        {"category": "General", "calculation_rule": {"calc_type": "PERCENTAGE"}, "transaction_conditions": {}},
    ]
    _write_card_json(tmp_path / "hyundai" / "card.json", "hyundai_x", "현대카드 X", "현대카드", benefits=benefits)

    repo = DatasetCardRepository(tmp_path)
    card = repo.list_cards()[0]

    assert "General" in card["_card_categories"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_list_cards_caches_result(tmp_path):
    """두 번째 호출은 디스크를 다시 읽지 않고 같은 list 객체를 반환."""
    _write_card_json(tmp_path / "hyundai" / "card.json", "hyundai_x", "현대카드 X", "현대카드")

    repo = DatasetCardRepository(tmp_path)
    first = repo.list_cards()
    second = repo.list_cards()

    assert first is second
