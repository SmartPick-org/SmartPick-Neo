import re
import typing

# 카드 번호 (ex. 1234-5678-1234-5678, 1234 5678 1234 5678)
CARD_PATTERN = re.compile(r"(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})")
# 전화 번호 (ex. 010-1234-5678)
PHONE_PATTERN = re.compile(r"(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})")

def mask_pii(text: str) -> str:
    """단순 텍스트 내의 개인정보를 정규식으로 마스킹"""
    if not isinstance(text, str):
        return text
    
    # 카드번호: 앞 4자리, 뒤 4자리만 표시
    text = CARD_PATTERN.sub(r"\1-****-****-\4", text)
    # 전화번호: 가운데 자리 마스킹
    text = PHONE_PATTERN.sub(r"\1-****-\3", text)
    
    return text

def mask_dict(data: typing.Any) -> typing.Any:
    """사전(dict), 리스트(list) 내부의 모든 단말 문자열을 재귀적으로 마스킹"""
    if isinstance(data, dict):
        return {k: mask_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_dict(item) for item in data]
    elif isinstance(data, str):
        return mask_pii(data)
    else:
        return data
