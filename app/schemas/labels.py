"""CategoryEnum / SubCategoryEnum → 한글 라벨 매핑.

백엔드가 영수증 fallback 문자열을 생성할 때 영어 enum 원시값이 사용자에게
그대로 노출(`[EduHealth] hospital 10% 혜택`)되던 문제를 해결하기 위한 단일
매핑 테이블. 향후 응답에 `sub_category_label` 같은 한글 필드를 추가할 때도
이 테이블을 재사용한다.

매핑에 없는 값은 `category_label_ko` / `sub_category_label_ko` 헬퍼가
원본 문자열을 그대로 돌려준다 (fail-open).
"""
from __future__ import annotations


# CategoryEnum 의 `.value` 기준으로 매핑
CATEGORY_LABELS_KO: dict[str, str] = {
    "General": "일반",
    "Shopping": "쇼핑",
    "Traffic": "교통",
    "Food": "외식",
    "Coffee": "커피",
    "Cultural": "문화",
    "Travel": "여행",
    "Life": "생활",
    "EduHealth": "교육/헬스",
    "Others": "기타",
}


# SubCategoryEnum 의 `.value` 기준으로 매핑
SUB_CATEGORY_LABELS_KO: dict[str, str] = {
    # Coffee
    "bakery": "베이커리",
    "cafe": "카페",
    # Cultural
    "books": "도서",
    "cinema": "영화관",
    "leisure_sports": "레저/스포츠",
    "music": "음악",
    "ott": "OTT",
    "performance": "공연",
    "theme_park": "테마파크",
    # EduHealth
    "education": "교육",
    "fitness": "피트니스",
    "hospital": "병원",
    "medical_detail": "의료",
    "pharmacy": "약국",
    # Food
    "delivery": "배달",
    "fast_food": "패스트푸드",
    "restaurant": "음식점",
    # Life
    "daily_service": "생활서비스",
    "housing": "주거",
    "insurance_tax": "보험/세금",
    "office": "사무",
    "telecom": "통신",
    "utility": "공과금",
    # Shopping
    "beauty": "뷰티",
    "convenience": "편의점",
    "daily_goods": "생필품",
    "dept_store": "백화점",
    "duty_free": "면세점",
    "home_shopping": "홈쇼핑",
    "mart": "마트",
    "online": "온라인",
    # Traffic
    "ev_charge": "전기차 충전",
    "express_bus": "고속버스",
    "fuel": "주유",
    "maintenance": "정비",
    "parking": "주차",
    "taxi": "택시",
    "toll": "통행료",
    "transit": "대중교통",
    # Travel
    "airline": "항공",
    "hotel": "호텔",
    "lounge_valet": "라운지/발렛",
    "overseas": "해외",
    "rental": "렌탈",
    "roaming": "로밍",
    "travel_agency": "여행사",
    # General fallback
    "general": "일반",
}


def category_label_ko(value: str) -> str:
    """`CategoryEnum.value` 를 한글 라벨로 변환. 매핑에 없으면 원본 반환."""
    if not value:
        return value
    return CATEGORY_LABELS_KO.get(value, value)


def sub_category_label_ko(value: str) -> str:
    """`SubCategoryEnum.value` 를 한글 라벨로 변환. 매핑에 없으면 원본 반환."""
    if not value:
        return value
    return SUB_CATEGORY_LABELS_KO.get(value, value)
