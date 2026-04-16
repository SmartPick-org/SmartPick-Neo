"""v4 스키마 검증 헬퍼(`validate_v4_data`) 테스트.

v3 → v4 이관 후 `adapt_v3_for_calculator`가 `validate_v4_data`로 대체되었습니다.
(이 함수는 계산기에 진입하기 전에 최소 필수 키가 존재하는지만 확인합니다.)
"""
from app.domain.adapters import validate_v4_data


def test_returns_true_when_required_keys_present():
    """card_meta와 benefits가 모두 있으면 True."""
    card = {
        "card_meta": {"card_id": "test", "card_name": "테스트카드"},
        "benefits": [{"benefit_id": "b1"}],
    }
    assert validate_v4_data(card) is True


def test_returns_false_when_card_meta_missing():
    """card_meta 키가 없으면 False."""
    card = {"benefits": [{"benefit_id": "b1"}]}
    assert validate_v4_data(card) is False


def test_returns_false_when_benefits_missing():
    """benefits 키가 없으면 False."""
    card = {"card_meta": {"card_id": "test"}}
    assert validate_v4_data(card) is False


def test_returns_false_for_empty_dict():
    """빈 dict은 두 키가 모두 없으므로 False."""
    assert validate_v4_data({}) is False


def test_returns_true_even_when_values_are_empty():
    """
    키만 존재하면 값이 비어 있어도 통과합니다.
    (이 함수는 스키마의 '존재 여부'만 책임지며, 내용 검증은 다른 레이어 책임)
    """
    card = {"card_meta": {}, "benefits": []}
    assert validate_v4_data(card) is True


def test_returns_true_with_additional_keys():
    """필수 키 외 추가 키가 있어도 통과해야 한다."""
    card = {
        "card_meta": {"card_id": "x"},
        "benefits": [],
        "benefit_groups": [],
        "_file_path": "/tmp/foo.json",
    }
    assert validate_v4_data(card) is True
