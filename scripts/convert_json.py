"""
카드 JSON 데이터 형식 변환 스크립트

기존 형식 (chunk 기반, 메타 중복) → 새 형식 (카드 단위, 구조화된 혜택)
카드 파일 통째로 LLM에 전달하여 한 번에 변환합니다.

사용법: python -m scripts.convert_json
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage

# ===========================< Setting >============================
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = "solar-pro2"
llm = init_chat_model(model=MODEL, temperature=0.0)

SRC_DIR = ROOT / "datasets" / "json"
DST_DIR = ROOT / "datasets" / "json_v2"

# ===========================< LLM 변환 프롬프트 >============================

CONVERT_PROMPT = """너는 신용카드 혜택 정보를 카드 혜택 계산기에 사용할 수 있는 구조화된 JSON 형태로 변환하는 금융 데이터 파서이다.

너의 역할은 신용카드 혜택 정보의 "content"와 "conditions"를 읽고, 아래 구조 형태로 변환하는 것이다.

[출력 구조]
{{
  "card_name": str,
  "card_company": str,
  "annual_fee": int,
  "minimum_performance": int,
  "card_categories": list,
  "benefits": [
    {{
      "category": str,
      "content": str,
      "benefit_type": str,
      "rate": float,
      "monthly_limit": int 또는 null,
      "condition_prev_month": int 또는 null,
      "conditions": str
    }}
  ],
  "unclear_benefits": [
    {{
      "category": str,
      "content": str,
      "conditions": str
    }}
  ]
}}

[카테고리 매핑 규칙]
category 값은 반드시 아래 항목 중 하나로만 매핑해야 한다.
General, Shopping, Traffic, Food, Coffee, Cultural, Travel, Life, EduHealth, Others

카테고리 매핑 기준:
General: 모든 가맹점, 일반 소비, 어디서나 적립/할인
Shopping: 온라인 쇼핑, 오프라인 쇼핑, 쇼핑몰, 이커머스
Traffic: 주유소, 대중교통, 택시, 모빌리티
Food: 음식점, 배달 앱
Coffee: 카페, 베이커리, 디저트
Cultural: OTT, 구독서비스, 영화, 스포츠, 디지털 콘텐츠
Travel: 항공, 호텔, 면세점, 해외 사용
Life: 공과금, 통신비, 보험료, 월세, 금융 서비스
EduHealth: 교육, 병원, 약국
Others: 어디에도 명확히 속하지 않는 경우

[정보 추출 규칙]

1. benefit_type
   할인 → "discount"
   적립 / 캐시백 / 포인트 → "point"

2. rate
   퍼센트를 소수로 변환
   예: 5% → 0.05

3. monthly_limit
   월 한도 금액을 추출
   한도가 없으면 null

4. condition_prev_month
   혜택을 받기 위해 필요한 전월 최소 사용 금액을 추출

5. 만약 어떤 혜택이
   (카테고리 소비금액 × rate)
   이 계산식으로 계산할 수 없는 혜택이라면,
   그 혜택은 unclear_benefits로 이동시켜라.
   특히 다음은 반드시 unclear_benefits로 분류할 것:
   - 정액 할인 (예: "월 1만원 할인", "3천원 할인" 등 고정 금액 할인)
   - 무이자 할부
   - 연회비 지원/캐시백
   - rate를 퍼센트(0~1.0 범위)로 표현할 수 없는 모든 혜택

마지막으로 결과는 JSON 형식으로만 반환하고, 설명은 출력하지 마라.

[입력 데이터]
{card_data}
"""


def validate_and_fix(converted: dict) -> dict:
    """후처리 검증: rate > 1.0인 혜택을 unclear_benefits로 이동합니다."""
    valid_benefits = []
    unclear = converted.get("unclear_benefits", [])

    for benefit in converted.get("benefits", []):
        rate = benefit.get("rate", 0.0)
        if rate is not None and rate > 1.0:
            print(f"    [FIX] rate={rate} → unclear로 이동: {benefit.get('category')}")
            unclear.append({
                "category": benefit.get("category", ""),
                "content": benefit.get("content", ""),
                "conditions": benefit.get("conditions", ""),
            })
        else:
            valid_benefits.append(benefit)

    converted["benefits"] = valid_benefits
    converted["unclear_benefits"] = unclear
    return converted


def convert_card(src_path: Path) -> dict:
    """하나의 카드 JSON을 통째로 LLM에 전달하여 새 형식으로 변환합니다."""
    raw_text = src_path.read_text(encoding="utf-8")

    prompt = CONVERT_PROMPT.format(card_data=raw_text)

    try:
        response = llm.invoke([SystemMessage(content=prompt)]).content
        response_str = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        cleaned = response_str.replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned)
        return validate_and_fix(result)
    except (json.JSONDecodeError, Exception) as e:
        print(f"    [ERROR] LLM 변환 실패: {e}")
        print(f"    응답 앞 300자: {response_str[:300] if 'response_str' in dir() else 'N/A'}")
        return {}


def main():
    print(f"원본: {SRC_DIR}")
    print(f"출력: {DST_DIR}\n")

    total_files = 0
    total_benefits = 0
    total_unclear = 0

    for company_dir in sorted(SRC_DIR.iterdir()):
        if not company_dir.is_dir():
            continue

        dst_company_dir = DST_DIR / company_dir.name
        dst_company_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{company_dir.name}]")

        for json_file in sorted(company_dir.glob("*.json")):
            print(f"  변환 중: {json_file.name}")
            converted = convert_card(json_file)

            if not converted:
                print(f"    [SKIP] 변환 실패")
                continue

            dst_path = dst_company_dir / json_file.name
            dst_path.write_text(
                json.dumps(converted, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            n_benefits = len(converted.get("benefits", []))
            n_unclear = len(converted.get("unclear_benefits", []))
            total_files += 1
            total_benefits += n_benefits
            total_unclear += n_unclear

            print(f"    완료: benefits {n_benefits}개, unclear {n_unclear}개")

    print(f"\n{'=' * 40}")
    print(f"총 {total_files}개 파일 변환 완료")
    print(f"총 benefits: {total_benefits}개, unclear: {total_unclear}개")
    print(f"출력 위치: {DST_DIR}")


if __name__ == "__main__":
    main()
