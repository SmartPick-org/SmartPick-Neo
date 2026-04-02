"""
확정된 Sub-Category 택소노미 (Single Source of Truth)

generate_json_v3.py, generate_digest.py, verify_json_v3.py 등에서 import하여 사용.
"""

# ── 카테고리별 sub_category 정의 ──
# 각 항목: (sub_category_key, 설명, 예시 키워드들)
# "reserved" 플래그가 True이면 현재 데이터에 해당 benefit이 0건임을 의미.

SUB_CATEGORY_DEFINITIONS: dict[str, list[dict]] = {
    "Traffic": [
        {"key": "transit",      "label": "대중교통",          "desc": "시내버스, 지하철, 철도, KTX, SRT",              "examples": ["후불교통 5% 할인", "버스/지하철 청구할인"],                  "reserved": False},
        {"key": "express_bus",  "label": "고속/시외버스",     "desc": "고속버스, 시외버스",                              "examples": ["고속/시외버스 5% 환급할인"],                               "reserved": False},
        {"key": "taxi",         "label": "택시",              "desc": "택시, 택시 호출앱",                               "examples": ["택시 10% 할인"],                                          "reserved": False},
        {"key": "fuel",         "label": "주유",              "desc": "주유소, LPG, 리터당 할인",                        "examples": ["GS칼텍스 리터당 60원 할인", "정유사 주유 10% 할인"],        "reserved": False},
        {"key": "ev_charge",    "label": "전기차충전",        "desc": "전기차 충전소",                                   "examples": [],                                                        "reserved": True},
        {"key": "parking",      "label": "주차",              "desc": "주차장, 주차 할인",                               "examples": ["전국 주차장 10% 할인", "주말 무료 주차"],                   "reserved": False},
        {"key": "toll",         "label": "통행료",            "desc": "통행료, 하이패스",                                "examples": [],                                                        "reserved": True},
        {"key": "maintenance",  "label": "정비/세차",         "desc": "차량 정비, 세차, 엔진오일",                       "examples": ["정비공임 10% 할인", "엔진오일 교환 2만원 할인"],            "reserved": False},
        {"key": "general",      "label": "교통 전반",         "desc": "특정 교통수단을 한정하지 않고 교통 카테고리 전체에 적용되거나, 복합 혜택 분할 시 교통 부분에 해당하는 혜택", "examples": ["교통/이동 5% 할인"], "reserved": False},
    ],
    "Shopping": [
        {"key": "online",       "label": "온라인쇼핑",        "desc": "온라인쇼핑, 이커머스, 패션앱",                    "examples": ["쿠팡, G마켓 10% 할인", "지그재그, 무신사"],                "reserved": False},
        {"key": "dept_store",   "label": "백화점",            "desc": "백화점, 아울렛",                                  "examples": ["롯데/신세계/현대백화점 5% 할인", "프리미엄아울렛"],         "reserved": False},
        {"key": "mart",         "label": "마트/슈퍼",         "desc": "대형마트, 슈퍼, 식자재",                          "examples": ["이마트, 홈플러스 10% 할인", "하나로식자재"],                "reserved": False},
        {"key": "convenience",  "label": "편의점",            "desc": "편의점 (CU, GS25 등)",                            "examples": ["CU, GS25 10% 할인", "편의점 5% 적립"],                    "reserved": False},
        {"key": "home_shopping","label": "홈쇼핑",            "desc": "홈쇼핑",                                          "examples": [],                                                        "reserved": True},
        {"key": "duty_free",    "label": "면세점",            "desc": "면세점",                                          "examples": ["신라면세점 추가 적립"],                                    "reserved": False},
        {"key": "daily_goods",  "label": "생활용품/잡화",     "desc": "생활용품, 잡화",                                  "examples": [],                                                        "reserved": True},
        {"key": "beauty",       "label": "뷰티/미용",         "desc": "뷰티, 미용, 올리브영, 미용실",                    "examples": ["미용실 10% 할인", "올리브영 3천원 적립"],                  "reserved": False},
        {"key": "general",      "label": "쇼핑 전반",         "desc": "특정 쇼핑 채널을 한정하지 않고 쇼핑 카테고리 전체에 적용되거나, 복합 혜택 분할 시 쇼핑 부분에 해당하는 혜택", "examples": ["쇼핑 5% 할인"], "reserved": False},
    ],
    "Food": [
        {"key": "restaurant",   "label": "외식",              "desc": "음식점, 외식, 레스토랑",                          "examples": ["일반음식점 5% 적립", "아웃백 10% 할인"],                   "reserved": False},
        {"key": "delivery",     "label": "배달",              "desc": "배달앱 (배민, 요기요 등)",                        "examples": ["배달앱 10% 할인"],                                       "reserved": False},
        {"key": "fast_food",    "label": "패스트푸드",        "desc": "패스트푸드, 버거",                                "examples": ["버거/패스트푸드 업종 20% 할인"],                          "reserved": False},
        {"key": "general",      "label": "식음료 전반",       "desc": "특정 식음료 업종을 한정하지 않고 Food 카테고리 전체에 적용되거나, 복합 혜택 분할 시 식음료 부분에 해당하는 혜택", "examples": ["푸드 5% 적립"], "reserved": False},
    ],
    "Coffee": [
        {"key": "cafe",         "label": "카페",              "desc": "카페, 커피전문점",                                "examples": ["스타벅스 50% 할인", "커피빈, 투썸 건당 500원 할인"],       "reserved": False},
        {"key": "bakery",       "label": "디저트/베이커리",   "desc": "디저트, 베이커리",                                "examples": ["곤트란쉐리에 베이커리 할인"],                              "reserved": False},
        {"key": "general",      "label": "카페·디저트 전반",  "desc": "카페와 베이커리를 구분하지 않고 Coffee 카테고리 전체에 적용되거나, 복합 혜택 분할 시 카페/디저트 부분에 해당하는 혜택", "examples": ["카페/디저트 5% 적립"], "reserved": False},
    ],
    "Cultural": [
        {"key": "cinema",         "label": "영화",            "desc": "영화관 (CGV, 메가박스, 롯데시네마)",              "examples": ["CGV 3천원 할인", "롯데시네마 5천원 할인"],                 "reserved": False},
        {"key": "performance",    "label": "공연/전시",       "desc": "공연, 전시",                                      "examples": [],                                                        "reserved": True},
        {"key": "books",          "label": "도서",            "desc": "도서, 서점, 온라인서점",                          "examples": ["교보문고, YES24 5% 할인", "독서실/도서/문구 적립"],        "reserved": False},
        {"key": "music",          "label": "음악",            "desc": "음악 스트리밍 (멜론, 지니 등)",                   "examples": ["멜론, 지니 1만원 할인"],                                  "reserved": False},
        {"key": "ott",            "label": "OTT/구독",        "desc": "OTT, 디지털 구독 (넷플릭스, 유튜브, 디즈니+ 등)","examples": ["넷플릭스 1만원 할인", "OTT 30% 할인", "유튜브 프리미엄"], "reserved": False},
        {"key": "theme_park",     "label": "테마파크",        "desc": "놀이공원, 테마파크",                              "examples": ["에버랜드 50% 할인", "롯데월드 자유이용권 50% 할인"],       "reserved": False},
        {"key": "leisure_sports", "label": "레저/스포츠",     "desc": "레저, 스포츠 (골프, 테니스 등)",                  "examples": ["골프장 그린피 15% 할인"],                                 "reserved": False},
        {"key": "general",        "label": "문화생활 전반",   "desc": "특정 문화 분야를 한정하지 않고 Cultural 카테고리 전체에 적용되거나, 복합 혜택 분할 시 문화 부분에 해당하는 혜택", "examples": ["문화생활 5% 할인"], "reserved": False},
    ],
    "Travel": [
        {"key": "airline",        "label": "항공",            "desc": "항공사 마일리지, 항공권",                         "examples": ["대한항공 마일리지 적립", "1천원당 1마일리지"],             "reserved": False},
        {"key": "hotel",          "label": "숙박",            "desc": "호텔 숙박, 예약 플랫폼",                          "examples": ["메리어트 참여 호텔 5포인트", "IHG 20% 할인"],             "reserved": False},
        {"key": "travel_agency",  "label": "여행사/플랫폼",   "desc": "여행사, 여행 플랫폼 (Trip.com, KKday 등)",        "examples": ["Trip.com 호텔 8%/항공 2% 할인", "KKday 5% 할인"],        "reserved": False},
        {"key": "overseas",       "label": "해외",            "desc": "해외 결제, 해외직구 캐시백",                      "examples": ["해외이용 5% 캐시백", "해외 일시불 1% 추가 적립"],         "reserved": False},
        {"key": "lounge_valet",   "label": "라운지/발레파킹", "desc": "공항 라운지, 발레파킹",                           "examples": ["공항라운지 연 2회 무료", "인천공항 발레파킹 무료"],        "reserved": False},
        {"key": "rental",         "label": "렌터카/카셰어",   "desc": "렌터카, 카셰어링",                                "examples": ["SK렌터카 할인", "Hertz 렌터카 10% 할인"],                 "reserved": False},
        {"key": "roaming",        "label": "로밍/eSIM",       "desc": "로밍, 해외 데이터, eSIM",                         "examples": ["해외데이터 로밍 1일 이용권", "eSIM 15% 할인"],            "reserved": False},
        {"key": "general",        "label": "여행 전반",       "desc": "특정 여행 분야를 한정하지 않고 Travel 카테고리 전체에 적용되거나, 복합 혜택 분할 시 여행 부분에 해당하는 혜택", "examples": ["여행 5% 할인"], "reserved": False},
    ],
    "Life": [
        {"key": "telecom",        "label": "통신",            "desc": "이동통신, 인터넷 요금",                           "examples": ["이동통신요금 10% 할인", "통신요금 자동이체 1천원 할인"],   "reserved": False},
        {"key": "utility",        "label": "공과금",          "desc": "전기, 가스, 수도, 공과금",                        "examples": ["전기요금, 도시가스 10% 할인", "공과금 10% 할인"],          "reserved": False},
        {"key": "housing",        "label": "관리비",          "desc": "아파트 관리비",                                   "examples": [],                                                        "reserved": True},
        {"key": "daily_service",  "label": "생활서비스",      "desc": "세탁, 청소, 정수기렌탈 등",                       "examples": ["세탁비 10% 할인", "정수기렌탈 5% 적립"],                  "reserved": False},
        {"key": "insurance_tax",  "label": "세금/보험/연금",  "desc": "보험료, 국세, 지방세, 연금",                      "examples": ["국세/지방세 7천원 할인", "보험료 2천원 할인"],             "reserved": False},
        {"key": "office",         "label": "사무/업무",       "desc": "문구, 사무용기기, 보안/용역",                     "examples": ["문구 및 사무용기기 5% 적립", "보안 및 용역 5% 적립"],     "reserved": False},
        {"key": "general",        "label": "생활 전반",       "desc": "특정 생활 분야를 한정하지 않고 Life 카테고리 전체에 적용되거나, 복합 혜택 분할 시 생활 부분에 해당하는 혜택", "examples": ["생활요금 정기결제 7% 할인"], "reserved": False},
    ],
    "EduHealth": [
        {"key": "hospital",       "label": "병원",            "desc": "병원, 한의원, 치과, 안과",                        "examples": ["병원/약국 10% 할인"],                                     "reserved": False},
        {"key": "pharmacy",       "label": "약국",            "desc": "약국",                                            "examples": ["약국 5% 적립"],                                          "reserved": False},
        {"key": "education",      "label": "학원/교육",       "desc": "학원, 독서실, 교육",                              "examples": ["학원/피트니스 10% 할인"],                                 "reserved": False},
        {"key": "fitness",        "label": "피트니스",        "desc": "피트니스, 헬스, 요가",                            "examples": ["피트니스 5% 할인"],                                      "reserved": False},
        {"key": "medical_detail", "label": "의료세부",        "desc": "의료 세부 (필요 시 확장)",                        "examples": [],                                                        "reserved": True},
        {"key": "general",        "label": "교육·건강 전반",  "desc": "특정 교육/건강 분야를 한정하지 않고 EduHealth 카테고리 전체에 적용되거나, 복합 혜택 분할 시 교육·건강 부분에 해당하는 혜택", "examples": ["교육/건강 5% 할인"], "reserved": False},
    ],
    # General, Others — sub_category 분리 불필요
}

# ── 유효한 카테고리 목록 ──
VALID_CATEGORIES = {
    "General", "Shopping", "Traffic", "Food", "Coffee",
    "Cultural", "Travel", "Life", "EduHealth",
    "All_Domestic", "Others",
}

# ── sub_category가 있는 카테고리의 유효한 키 목록 ──
VALID_SUB_CATEGORIES: dict[str, set[str]] = {
    cat: {item["key"] for item in items}
    for cat, items in SUB_CATEGORY_DEFINITIONS.items()
}


def get_active_sub_categories(category: str) -> list[dict]:
    """reserved가 아닌 활성 sub_category 목록 반환."""
    items = SUB_CATEGORY_DEFINITIONS.get(category, [])
    return [item for item in items if not item.get("reserved", False)]


def build_prompt_block() -> str:
    """LLM 프롬프트에 삽입할 카테고리 + sub_category 매핑 규칙 텍스트를 생성."""
    lines = [
        "[카테고리 + 서브카테고리 매핑 규칙]",
        "각 benefit에 category와 sub_category를 반드시 지정할 것.",
        "sub_category가 정의된 카테고리는 아래 목록에서 선택. 미정의 카테고리(General, Others 등)는 sub_category를 null로 지정.",
        "",
    ]
    for cat, items in SUB_CATEGORY_DEFINITIONS.items():
        lines.append(f"- {cat}:")
        for item in items:
            examples_str = ""
            if item["examples"]:
                examples_str = " (예: " + ", ".join(f'"{e}"' for e in item["examples"]) + ")"
            reserved_tag = " [RESERVED]" if item.get("reserved") else ""
            lines.append(f"  · {item['key']}: {item['desc']}{examples_str}{reserved_tag}")
        lines.append("")

    lines.extend([
        "- General: 모든 가맹점, 전 가맹점 적립/할인 → sub_category: null",
        "- All_Domestic: 국내 전 가맹점 → sub_category: null",
        "- Others: 위에 해당하지 않는 경우 → sub_category: null",
        "",
        "[RESERVED] 표시된 항목은 현재 데이터에 해당 혜택이 없으나, 해당하는 혜택 발견 시 사용 가능.",
        "",
        "[general sub_category 사용 기준]",
        "각 카테고리의 general은 다음 경우에만 사용:",
        "1. 해당 카테고리 전체에 걸쳐 적용되어 특정 세부 분류로 한정할 수 없는 혜택",
        "   예: '생활요금 정기결제 7% 할인' → Life/general (통신, 공과금, 보험 등을 구분하지 않고 Life 전반 대상)",
        "2. 복합 카테고리 혜택을 분할할 때, 분할된 각 항목이 해당 카테고리 내에서 특정 세부 분류에 대응하지 않는 경우",
        "   예: '편의점, 푸드, 카페 5%' 분할 시 → Food 부분은 Food/general (외식도 배달도 아닌 '푸드 전반')",
        "⚠ 특정 세부 분류에 명확히 대응 가능한 혜택은 반드시 해당 sub_category를 사용할 것. general을 남용하지 마라.",
    ])
    return "\n".join(lines)
