"""
마크다운 기반 카드 JSON v3 생성 스크립트

markdown_upstage/ 하위의 마크다운 파일들을 카드별로 그룹핑한 뒤,
LLM(solar-pro2)으로 v3 스키마 JSON을 생성합니다.

사용법: python -m scripts.generate_json_v3
옵션:
  --card <카드명 키워드>   특정 카드만 변환 (예: --card "Mr.Life")
  --company <회사명>       특정 카드사만 변환 (예: --company shinhan)
  --dry-run               파일 그룹핑만 확인하고 LLM 호출하지 않음
"""

import os
import re
import json
import sys
import time
import argparse
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage

# ===========================< Setting >============================
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = "solar-pro2"
llm = init_chat_model(model=MODEL, temperature=0.0)

MD_DIR = ROOT / "datasets" / "markdown_upstage"
DST_DIR = ROOT / "datasets" / "json_v3"

# ===========================< 카드 그룹핑 >============================

# ===========================< 카드명 수동 매핑 >============================
# 그룹 키 → 정확한 card_name, card_id (PDF/마크다운/JSON 간 이름 통일)
CARD_NAME_MAP = {
    # 현대카드
    "hyundai_Digital Lover": {"card_name": "현대카드 DIGITAL LOVER", "card_id": "hyundai_digital_lover"},
    "hyundai_M": {"card_name": "현대카드 M", "card_id": "hyundai_m"},
    "hyundai_SC the Red": {"card_name": "현대카드 the Red (SC제일은행)", "card_id": "hyundai_the_red_sc"},
    "hyundai_Summit": {"card_name": "현대카드 Summit", "card_id": "hyundai_summit"},
    "hyundai_T3 Edition2": {"card_name": "현대카드 T3 Edition2", "card_id": "hyundai_t3_edition2"},
    "hyundai_X": {"card_name": "현대카드 X", "card_id": "hyundai_x"},
    "hyundai_Z family": {"card_name": "현대카드 Z family", "card_id": "hyundai_z_family"},
    "hyundai_ZERO Ed3 포인트형": {"card_name": "현대카드 ZERO Edition3 포인트형 (SC제일은행)", "card_id": "hyundai_zero_ed3_point_sc"},
    "hyundai_the Green Ed3": {"card_name": "현대카드 the Green Edition3", "card_id": "hyundai_the_green_ed3"},
    "hyundai_the Pink Ed2": {"card_name": "현대카드 the Pink Edition2", "card_id": "hyundai_the_pink_ed2"},
    # KB국민카드
    "kb_Easy Pick": {"card_name": "KB국민 Easy pick카드", "card_id": "kb_easy_pick"},
    "kb_FINETECH": {"card_name": "KB국민 FINETECH카드", "card_id": "kb_finetech"},
    "kb_My WESH": {"card_name": "KB국민 My WE:SH카드", "card_id": "kb_my_wesh"},
    "kb_Star": {"card_name": "KB국민 Star카드", "card_id": "kb_star"},
    "kb_The Easy": {"card_name": "KB국민 The Easy카드", "card_id": "kb_the_easy"},
    "kb_국민 굿데이": {"card_name": "KB국민 굿데이올림카드", "card_id": "kb_goodday_olym"},
    "kb_마이원": {"card_name": "KB국민 마이원카드", "card_id": "kb_myone"},
    "kb_직장인 보너스": {"card_name": "KB국민 직장인보너스 체크카드", "card_id": "kb_worker_bonus_check"},
    "kb_청춘대로 톡톡": {"card_name": "KB국민 청춘대로 톡톡카드", "card_id": "kb_youth_toktok"},
    "kb_탄탄대로 MizMr": {"card_name": "KB국민 탄탄대로 Biz카드", "card_id": "kb_tantan_biz"},
    # 신한카드
    "shinhan_Air One": {"card_name": "신한카드 Air One", "card_id": "shinhan_air_one"},
    "shinhan_Deep Oil": {"card_name": "신한카드 Deep Oil", "card_id": "shinhan_deep_oil"},
    "shinhan_Discount Plan+": {"card_name": "신한카드 Discount Plan+", "card_id": "shinhan_discount_plan_plus"},
    "shinhan_Hi-Point": {"card_name": "신한카드 Hi-Point 플래티늄", "card_id": "shinhan_hi_point"},
    "shinhan_Mr.Life": {"card_name": "신한카드 Mr.Life", "card_id": "shinhan_mr_life"},
    "shinhan_Point Plan": {"card_name": "신한카드 Point Plan", "card_id": "shinhan_point_plan"},
    "shinhan_Point Plan+": {"card_name": "신한카드 Point Plan+", "card_id": "shinhan_point_plan_plus"},
    "shinhan_Simple": {"card_name": "신한카드 Simple 플래티늄", "card_id": "shinhan_simple"},
    "shinhan_The CLASSIC-S": {"card_name": "신한카드 The CLASSIC-S", "card_id": "shinhan_the_classic_s"},
    "shinhan_메리어트 본보이": {"card_name": "메리어트 본보이 더 베스트 신한카드", "card_id": "shinhan_marriott_bonvoy"},
    "shinhan_처음": {"card_name": "신한카드 처음", "card_id": "shinhan_first"},
    "shinhan_처음 체크": {"card_name": "신한카드 처음 체크", "card_id": "shinhan_first_check"},
}

COMPANY_MAP = {
    "kb": "KB국민카드",
    "shinhan": "신한카드",
    "hyundai": "현대카드",
}

# ===========================< 카드명 정규화 >============================

# 현대카드 수동 매핑: 파일명 키워드 → 통합 카드 키
HYUNDAI_CARD_ALIASES = {
    "T3": "hyundai_T3 Edition2",
    "T3+Edition2": "hyundai_T3 Edition2",
    "T3 Edition2": "hyundai_T3 Edition2",
    "M": "hyundai_M",
    "M_V1": "hyundai_M",
    "현대카드M": "hyundai_M",
    "X": "hyundai_X",
    "Summit": "hyundai_Summit",
    "the Green Ed3": "hyundai_the Green Ed3",
    "the Green ed3": "hyundai_the Green Ed3",
    "the Pink Ed2": "hyundai_the Pink Ed2",
    "the Pink ed2": "hyundai_the Pink Ed2",
    "the Red": "hyundai_SC the Red",
    "SC_the Red": "hyundai_SC the Red",
    "SC제일은행 the Red": "hyundai_SC the Red",
    "Z family": "hyundai_Z family",
    "Z family Ed2": "hyundai_Z family",
    "ZERO Ed3 포인트형": "hyundai_ZERO Ed3 포인트형",
    "ZERO Ed3_포인트형": "hyundai_ZERO Ed3 포인트형",
    "SC제일은행 ZERO Ed3 포인트형": "hyundai_ZERO Ed3 포인트형",
    "DIGITAL LOVER": "hyundai_Digital Lover",
    "Digital Lover": "hyundai_Digital Lover",
    "Digital Lover 신용카드 설명서": "hyundai_Digital Lover",
}

# 신한카드 수동 매핑
SHINHAN_CARD_ALIASES = {
    "Air One": "shinhan_Air One",
    "Air": "shinhan_Air One",
    "Deep Oil": "shinhan_Deep Oil",
    "Deep": "shinhan_Deep Oil",
    "Mr.Life": "shinhan_Mr.Life",
    "Discount Plan+": "shinhan_Discount Plan+",
    "Discount": "shinhan_Discount Plan+",
    "Hi-Point": "shinhan_Hi-Point",
    "Point Plan+": "shinhan_Point Plan+",
    "Point Plan": "shinhan_Point Plan",
    "Simple": "shinhan_Simple",
    "The CLASSIC-S": "shinhan_The CLASSIC-S",
    "The": "shinhan_The CLASSIC-S",
    "메리어트": "shinhan_메리어트 본보이",
    "처음": "shinhan_처음",
    "처음 체크": "shinhan_처음 체크",
}


def normalize_card_key(company: str, filename: str) -> str:
    """파일명에서 카드 식별 키를 추출합니다."""
    stem = Path(filename).stem

    if company == "kb":
        m = re.search(r"KB_KB\s+(.+?)\s*(?:카드|체크카드)?(?:_|$)", stem)
        if m:
            name = re.sub(r"\s+", " ", m.group(1).strip())
            return f"kb_{name}"
        return f"kb_{stem[:30]}"

    elif company == "shinhan":
        # 1) 파일명에서 카드명 추출
        extracted = None
        for pattern in [
            r"신한카드\s+(.+?)$",          # "신한카드 Mr.Life"
            r"Shinhan_(.+?)_",              # "Shinhan_Air One_..."
            r"^(.+?)$",                     # "Deep Oil", "메리어트..."
        ]:
            m = re.search(pattern, stem)
            if m:
                extracted = m.group(1).strip()
                if extracted and len(extracted) > 1:
                    break

        # 2) 별칭 매핑 시도 (긴 키부터 매칭)
        if extracted:
            for alias_key in sorted(SHINHAN_CARD_ALIASES, key=len, reverse=True):
                if alias_key in extracted:
                    return SHINHAN_CARD_ALIASES[alias_key]
            return f"shinhan_{extracted}"
        return f"shinhan_{stem[:30]}"

    elif company == "hyundai":
        # 0) 전처리: 공통 접미사 제거
        cleaned_stem = re.sub(r"\s*신용카드\s*설명서\s*", "", stem).strip()

        # 1) 파일명에서 카드명 추출
        extracted = None
        for pattern in [
            r"현대카드\s*(.+?)(?:\s+상품|\s+가이드|$)",
            r"가이드북[_\s]*(.+?)(?:_V\d|_\d{6}|$)",
            r"금소법[_\s]*(?:SC제일은행\s*)?(.+?)(?:_V\d|_\d{6}|$)",
            r"신용카드설명서[_\s]*(.+?)(?:$)",
            r"^(\d+)[_\s]*신용카드설명서[_\s]*(.+?)$",
        ]:
            m = re.search(pattern, stem)
            if m:
                extracted = m.group(m.lastindex).strip().rstrip("_")
                if extracted and len(extracted) > 0:
                    break

        # 2) 별칭 매핑 시도 (긴 키부터 매칭)
        if extracted:
            for alias_key in sorted(HYUNDAI_CARD_ALIASES, key=len, reverse=True):
                if alias_key in extracted:
                    return HYUNDAI_CARD_ALIASES[alias_key]
            return f"hyundai_{extracted}"

        # 2.5) cleaned_stem으로 별칭 매핑 재시도
        if cleaned_stem and cleaned_stem != stem:
            for alias_key in sorted(HYUNDAI_CARD_ALIASES, key=len, reverse=True):
                if alias_key in cleaned_stem:
                    return HYUNDAI_CARD_ALIASES[alias_key]
            return f"hyundai_{cleaned_stem}"

        # 3) 날짜만 있는 파일명 (예: "20260107_X") → X 추출
        m = re.search(r"^\d+[_\s]*(.+?)$", stem)
        if m:
            name = m.group(1).strip()
            for alias_key in sorted(HYUNDAI_CARD_ALIASES, key=len, reverse=True):
                if alias_key in name:
                    return HYUNDAI_CARD_ALIASES[alias_key]
            return f"hyundai_{name}"

        return f"hyundai_{stem[:30]}"

    return f"{company}_{stem[:30]}"


def group_markdown_files() -> dict[str, dict]:
    """
    markdown_upstage/ 하위 파일들을 카드 키별로 그룹핑합니다.

    Returns:
        {card_key: {"company": str, "company_kr": str, "files": [Path, ...]}}
    """
    groups: dict[str, dict] = {}

    for company_dir in sorted(MD_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        company = company_dir.name  # kb, shinhan, hyundai
        company_kr = COMPANY_MAP.get(company, company)

        for md_file in sorted(company_dir.rglob("*.md")):
            card_key = normalize_card_key(company, md_file.name)

            if card_key not in groups:
                groups[card_key] = {
                    "company": company,
                    "company_kr": company_kr,
                    "files": [],
                }
            groups[card_key]["files"].append(md_file)

    return groups


# ===========================< LLM 변환 프롬프트 >============================

CONVERT_V3_PROMPT = """너는 신용카드 약관/설명서 마크다운을 읽고, 카드 혜택 계산 엔진에서 사용할 구조화된 JSON을 생성하는 금융 데이터 파서이다.

[출력 스키마 v3]
{{
  "card_meta": {{
    "card_id": "카드 고유 식별자 (예: shinhan_mr_life)",
    "card_name": "카드 상품명",
    "card_company": "카드사 이름",
    "annual_fee": 기본 연회비 (원, 정수. 여러 브랜드가 있으면 가장 낮은 것),
    "minimum_performance": 혜택을 받기 위한 최소 전월 실적 (원, 정수),
    "reward_currency": "KRW 또는 MY_SHINHAN_POINT, M_POINT, MILEAGE 등",
    "currency_to_krw_rate": 1단위당 원화 환산 (KRW이면 1.0)
  }},

  "benefit_groups": [
    {{
      "group_id": "그룹 식별자 (예: G_MRLIFE_WEEKEND)",
      "group_name": "그룹명 (UI 노출용)",
      "group_type": "SHARED_LIMIT | USER_CHOICE_ONE | AUTO_TOP_N",
      "limit_amount": 그룹 통합 한도 (원) 또는 null,
      "top_n_count": AUTO_TOP_N일 때 상위 개수 또는 null
    }}
  ],

  "benefits": [
    {{
      "benefit_id": "개별 혜택 고유 식별자 (예: b_mrlife_utility_10pct)",
      "category": "표준 카테고리 (아래 목록 참조)",
      "content": "약관 원문 요약 (LLM 추론 근거용)",
      "frequency": "MONTHLY | ANNUAL | ONCE",
      "reward_type": "DISCOUNT | POINT | CASHBACK | VOUCHER",

      "tier_conditions": [
        {{
          "min_prev_performance": 해당 구간 적용을 위한 전월 실적 하한 (원),
          "monthly_limit": 이 구간에서의 월 한도 (원),
          "reward_rate": 할인/적립률 (예: 0.1 = 10%) 또는 null,
          "fixed_amount": 정액 금액 (원) 또는 null
        }}
      ],

      "calculation_rule": {{
        "calc_method": "RATE | FIXED_AMOUNT | FIXED_PER_VOLUME | MAX_COVER_UP_TO_LIMIT | TIERED_RATE_BY_TRANSACTION",
        "rate": 기본 할인/적립률 또는 null,
        "fixed_amount": 정액 혜택 금액 또는 null,
        "monthly_limit": 해당 혜택 단독 월 한도 (원) 또는 null,
        "fallback_reward_rate": 한도 초과 시 적용 기본 적립률 (없으면 0.0),
        "transaction_tiers": null 또는 [{{ "min_amount": int, "rate": float }}]
      }},

      "transaction_conditions": {{
        "min_payment_amount": 건당 최소 결제 요구 금액 (원, 없으면 0),
        "max_payment_amount_applied": 1회 결제 시 혜택 적용 최대 금액 또는 null,
        "max_count_per_month": 월 최대 혜택 제공 횟수 또는 null
      }},

      "group_id": "benefit_groups의 group_id 참조 또는 null",

      "ui_warnings": ["사용자에게 고지해야 할 예외 사항"],

      "edge_case_flags": {{
        "requires_user_selection": false,
        "excludes_from_performance": false,
        "special_month_bonus": null,
        "escape_hatch_note": null
      }}
    }}
  ]
}}

[카테고리 매핑 규칙]
반드시 아래 중 하나만 사용:
- General: 모든 가맹점, 일반 소비, 어디서나 적립/할인
- Shopping: 온라인/오프라인 ���핑, 마트, 백화점, 이커머스
- Traffic: 주유소, 대중교통, 택시
- Food: 음식점, 배달앱
- Coffee: 카페, 베이커리, 디저트
- Dining_FNB: 식음료 전체 (레스토랑, 카페, 음식점 통합)
- Cultural: OTT, 구독, 영화, 공연
- Travel: 항공, 호텔, 면세점, 해외
- Life: 공과금, 통신비, 보험료, 편의점, 세탁
- EduHealth: 교육, 병원, 약국
- Streaming: 스트리밍 서비스
- All_Domestic: 국내 전 가맹점
- Others: 위에 해당하지 않는 경우

[변환 규칙]

1. calc_method 판단:
   - "XX% 할인/적립" → RATE (rate = 소수, 예: 10% → 0.1)
   - "N천원 할인", "N만원 적립" → FIXED_AMOUNT
   - "리터당 N원 할인" → FIXED_PER_VOLUME
   - "N만원까지 전액 할인" → MAX_COVER_UP_TO_LIMIT
   - "결제 금액별 차등 비율" → TIERED_RATE_BY_TRANSACTION

2. tier_conditions: 전월 실적 구간별 한도가 다르면 각 구간을 배열로 기재

3. benefit_groups:
   - "월납/주말/Time 할인한도 통합" → SHARED_LIMIT
   - "택1 선택" → USER_CHOICE_ONE
   - "상위 N개 자동 적용" → AUTO_TOP_N

4. transaction_conditions:
   - "1회 승인금액 5만원까지 할인" → max_payment_amount_applied: 50000
   - "일 1회" → 해당 내용을 ui_warnings에 기재
   - "월 5회" → max_count_per_month: 5

5. edge_case_flags:
   - 사용자가 선호영역을 선택해야 하면 requires_user_selection: true
   - 특정 월 보너스가 있으면 special_month_bonus에 기재

6. reward_currency:
   - 포인트리 → "POINTREE" (currency_to_krw_rate: 1.0)
   - My신한포인트 → "MY_SHINHAN_POINT" (currency_to_krw_rate: 1.0)
   - M포인트 → "M_POINT" (currency_to_krw_rate: 0.666)
   - 마일리지 → "MILEAGE" (currency_to_krw_rate: 15.0)
   - 청구할인 → "KRW" (currency_to_krw_rate: 1.0)

7. card_id 형식: {{company}}_{{card_name_snake_case}} (예: shinhan_mr_life, kb_easy_pick)

결과는 JSON만 반환하고, 설명이나 주석은 출력하지 마라.

[카드사]
{company}

[마크다운 원문]
{markdown_content}
"""


# ===========================< JSON 파서 >============================

def parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON을 추출합니다. 3단계 시도."""
    # 1단계: 코드블록 제거
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    # 직접 파싱 시도
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2단계: 첫 번째 { ... 마지막 } 추출
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # 3단계: depth 기반 추출
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("JSON 객체를 찾을 수 없음")

    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    break

    raise ValueError(f"JSON 파싱 실패. 앞 300자: {cleaned[:300]}")


# ===========================< 후처리 검증 >============================

def validate_v3(data: dict) -> dict:
    """v3 JSON 후처리 검증."""
    # card_meta 필수 필드 확인
    meta = data.get("card_meta", {})
    if not meta.get("card_name"):
        print("    [WARN] card_name이 비어 있습니다")
    if not meta.get("card_id"):
        print("    [WARN] card_id가 비어 있습니다")

    # benefits 검증
    for b in data.get("benefits", []):
        rule = b.get("calculation_rule", {})
        rate = rule.get("rate")
        if rate is not None and isinstance(rate, (int, float)) and rate > 1.0:
            print(f"    [FIX] rate={rate} 비정상 → {b.get('benefit_id')}")
            rule["rate"] = rate / 100.0  # 퍼센트를 소수로 보정

    # benefit_groups가 없으면 빈 배열
    if "benefit_groups" not in data:
        data["benefit_groups"] = []

    return data


# ===========================< 변환 실행 >============================

def convert_card(card_key: str, group: dict) -> dict | None:
    """카드 그룹의 마크다운들을 합쳐 LLM으로 v3 JSON을 생성합니다."""
    # 마크다운 합치기
    md_parts = []
    for md_file in group["files"]:
        content = md_file.read_text(encoding="utf-8")
        rel_path = md_file.relative_to(MD_DIR)
        md_parts.append(f"--- 파일: {rel_path} ---\n{content}")

    combined_md = "\n\n".join(md_parts)

    # 너무 길면 앞부분만 (토큰 제한 고려)
    MAX_CHARS = 15000
    if len(combined_md) > MAX_CHARS:
        combined_md = combined_md[:MAX_CHARS] + "\n\n... (이하 생략)"
        print(f"    [INFO] 마크다운 {len(combined_md)}자 → {MAX_CHARS}자로 잘림")

    # 카드명 매핑 힌트
    name_info = CARD_NAME_MAP.get(card_key)
    name_hint = ""
    if name_info:
        name_hint = f"\n\n[중요] 이 카드의 정확한 이름은 '{name_info['card_name']}'이고, card_id는 '{name_info['card_id']}'입니다. card_meta에 이 값을 그대로 사용하세요."

    prompt = CONVERT_V3_PROMPT.format(
        company=group["company_kr"],
        markdown_content=combined_md,
    ) + name_hint

    try:
        start = time.time()
        response = llm.invoke([SystemMessage(content=prompt)]).content
        elapsed = time.time() - start
        print(f"    LLM 응답: {elapsed:.1f}초")

        result = parse_json_response(response if isinstance(response, str) else str(response))
        result = validate_v3(result)

        # 매핑된 card_name/card_id로 강제 덮어쓰기
        if name_info and result:
            result["card_meta"]["card_name"] = name_info["card_name"]
            result["card_meta"]["card_id"] = name_info["card_id"]

        return result

    except Exception as e:
        print(f"    [ERROR] 변환 실패: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="마크다운 → JSON v3 변환")
    parser.add_argument("--card", type=str, help="특정 카드만 변환 (키워드)")
    parser.add_argument("--company", type=str, help="특정 카드사만 변환 (kb/shinhan/hyundai)")
    parser.add_argument("--dry-run", action="store_true", help="그룹핑만 확인")
    args = parser.parse_args()

    print("=== 마크다운 파일 그룹핑 ===")
    groups = group_markdown_files()

    # 필터링
    if args.company:
        groups = {k: v for k, v in groups.items() if v["company"] == args.company}
    if args.card:
        keyword = args.card.lower()
        groups = {k: v for k, v in groups.items() if keyword in k.lower()}

    print(f"\n총 {len(groups)}개 카드 그룹 발견:\n")
    for key, group in sorted(groups.items()):
        print(f"  [{key}] ({group['company_kr']}) — 파일 {len(group['files'])}개")
        for f in group["files"]:
            print(f"    - {f.relative_to(MD_DIR)}")

    if args.dry_run:
        print("\n[DRY RUN] LLM 호출 없이 종료합니다.")
        return

    # 변환 실행
    print(f"\n=== JSON v3 변환 시작 ({len(groups)}개 카드) ===\n")
    success = 0
    fail = 0

    for card_key, group in sorted(groups.items()):
        company = group["company"]
        print(f"[{card_key}] 변환 중...")

        result = convert_card(card_key, group)
        if not result:
            fail += 1
            continue

        # 저장
        out_dir = DST_DIR / company
        out_dir.mkdir(parents=True, exist_ok=True)

        # card_id 기반 파일명
        card_id = result.get("card_meta", {}).get("card_id", card_key)
        safe_name = re.sub(r"[^\w\-]", "_", card_id)
        out_path = out_dir / f"{safe_name}.json"

        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"    → 저장: {out_path.relative_to(ROOT)}")
        success += 1

    print(f"\n=== 완료: 성공 {success}개, 실패 {fail}개 ===")


if __name__ == "__main__":
    main()
