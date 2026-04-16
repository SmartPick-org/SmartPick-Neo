"""PII 마스킹 로직 테스트 — 로그/알림에 개인정보가 노출되지 않도록 방어."""
from __future__ import annotations

from app.utils.masking import mask_pii, mask_dict


# ---------------------------------------------------------------------------
# mask_pii — 카드번호
# ---------------------------------------------------------------------------

class TestMaskCardNumber:
    def test_hyphen_separator(self):
        assert mask_pii("카드 1234-5678-9012-3456 입니다") == "카드 1234-****-****-3456 입니다"

    def test_space_separator(self):
        assert mask_pii("1234 5678 9012 3456") == "1234-****-****-3456"

    def test_dot_separator(self):
        assert mask_pii("1234.5678.9012.3456") == "1234-****-****-3456"

    def test_no_separator(self):
        assert mask_pii("1234567890123456") == "1234-****-****-3456"

    def test_multiple_cards_in_text(self):
        result = mask_pii("A=1234-5678-9012-3456, B=9999-8888-7777-6666")
        assert "1234-****-****-3456" in result
        assert "9999-****-****-6666" in result


# ---------------------------------------------------------------------------
# mask_pii — 전화번호
# ---------------------------------------------------------------------------

class TestMaskPhoneNumber:
    def test_010_prefix_hyphen(self):
        assert mask_pii("010-1234-5678") == "010-****-5678"

    def test_011_prefix(self):
        assert mask_pii("011-234-5678") == "011-****-5678"

    def test_016_017_018_019_prefixes(self):
        for prefix in ("016", "017", "018", "019"):
            assert mask_pii(f"{prefix}-1234-5678") == f"{prefix}-****-5678"

    def test_three_digit_middle(self):
        """가운데 자리가 3자리여도 마스킹되어야 함"""
        assert mask_pii("010-123-4567") == "010-****-4567"

    def test_space_separator(self):
        assert mask_pii("010 1234 5678") == "010-****-5678"

    def test_no_separator(self):
        assert mask_pii("01012345678") == "010-****-5678"


# ---------------------------------------------------------------------------
# mask_pii — edge cases
# ---------------------------------------------------------------------------

class TestMaskPiiEdgeCases:
    def test_non_string_input_returns_unchanged(self):
        assert mask_pii(12345) == 12345
        assert mask_pii(None) is None
        assert mask_pii([1, 2, 3]) == [1, 2, 3]

    def test_empty_string(self):
        assert mask_pii("") == ""

    def test_text_without_pii_unchanged(self):
        assert mask_pii("안녕하세요 반갑습니다") == "안녕하세요 반갑습니다"

    def test_card_and_phone_both_masked(self):
        """한 문자열에 카드번호와 전화번호가 모두 있으면 둘 다 마스킹"""
        result = mask_pii("연락처 010-1234-5678, 카드 1234-5678-9012-3456")
        assert "010-****-5678" in result
        assert "1234-****-****-3456" in result


# ---------------------------------------------------------------------------
# mask_dict — 재귀 순회
# ---------------------------------------------------------------------------

class TestMaskDict:
    def test_flat_dict_string_values_masked(self):
        data = {"phone": "010-1234-5678", "name": "홍길동"}
        result = mask_dict(data)
        assert result == {"phone": "010-****-5678", "name": "홍길동"}

    def test_nested_dict_masked_recursively(self):
        data = {"user": {"phone": "010-1234-5678", "meta": {"card": "1234-5678-9012-3456"}}}
        result = mask_dict(data)
        assert result["user"]["phone"] == "010-****-5678"
        assert result["user"]["meta"]["card"] == "1234-****-****-3456"

    def test_list_of_strings_masked(self):
        data = ["010-1234-5678", "hello", "1234-5678-9012-3456"]
        result = mask_dict(data)
        assert result == ["010-****-5678", "hello", "1234-****-****-3456"]

    def test_list_of_dicts_masked(self):
        data = [{"phone": "010-1234-5678"}, {"phone": "011-9999-8888"}]
        result = mask_dict(data)
        assert result == [{"phone": "010-****-5678"}, {"phone": "011-****-8888"}]

    def test_non_string_leaves_preserved(self):
        """int, bool, None, float은 그대로 유지되어야 함"""
        data = {"count": 42, "active": True, "note": None, "rate": 0.5, "phone": "010-1234-5678"}
        result = mask_dict(data)
        assert result == {"count": 42, "active": True, "note": None, "rate": 0.5, "phone": "010-****-5678"}

    def test_empty_containers(self):
        assert mask_dict({}) == {}
        assert mask_dict([]) == []

    def test_does_not_mutate_input(self):
        """원본 dict이 변경되지 않아야 함 (재귀 시 새 dict 반환)"""
        original = {"phone": "010-1234-5678"}
        mask_dict(original)
        assert original == {"phone": "010-1234-5678"}
