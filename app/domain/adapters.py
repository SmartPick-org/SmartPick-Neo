def validate_v4_data(card_data: dict) -> bool:
    """
    v4 스키마 데이터의 최소 요구 사항을 검증합니다.
    """
    if "card_meta" not in card_data:
        return False
    if "benefits" not in card_data:
        return False
    return True
