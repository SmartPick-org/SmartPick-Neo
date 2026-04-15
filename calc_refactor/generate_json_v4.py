"""
마크다운 기반 카드 JSON v4 생성 스크립트

markdown_upstage/ 하위의 마크다운 파일들을 카드별로 그룹핑한 뒤,
calc_refactor/Calculator_Schema.json 기반으로 LLM을 통해 v4 JSON을 생성합니다.

사용법: uv run python -m calc_refactor.generate_json_v4
옵션:
  --card <카드명 키워드>   특정 카드만 변환
  --company <회사명>       특정 카드사만 변환
  --dry-run               파일 그룹핑만 확인하고 LLM 호출하지 않음
"""

import os
import re
import json
import time
import argparse
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from loguru import logger

# V3에서 참조하던 유틸리티 및 전역 변수를 그대로 활용
from app.utils.md_table_refine import fix_markdown_text
from scripts.sub_categories import (
    build_prompt_block,
    VALID_CATEGORIES,
    VALID_SUB_CATEGORIES,
)
from scripts.generate_json_v3 import (
    CARD_NAME_MAP,
    COMPANY_MAP,
    HYUNDAI_CARD_ALIASES,
    SHINHAN_CARD_ALIASES,
    normalize_card_key,
    parse_json_response
)

# ===========================< Setting >============================
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = "solar-pro2"
llm = init_chat_model(model=MODEL, temperature=0.0)

MD_DIR = ROOT / "datasets" / "gemini_md"
DST_DIR = ROOT / "datasets" / "json_v4"
SCHEMA_PATH = ROOT / "calc_refactor" / "Calculator_Schema.json"

# ===========================< 카드 그룹핑 (v4 종속) >========================
def group_markdown_files() -> dict[str, dict]:
    """
    MD_DIR 하위 파일들을 카드 키별로 그룹핑합니다.
    (pipeline.py 등에서 MD_DIR을 동적으로 덮어씌울 수 있도록 자체 함수 선언)
    """
    groups: dict[str, dict] = {}
    for company_dir in sorted(MD_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        company = company_dir.name
        company_kr = COMPANY_MAP.get(company, company)

        for md_file in sorted(company_dir.rglob("*.md")):
            card_key = normalize_card_key(company, md_file.name)
            if card_key not in groups:
                groups[card_key] = {"company": company, "company_kr": company_kr, "files": []}
            groups[card_key]["files"].append(md_file)
    return groups

# ===========================< LLM 변환 프롬프트 >============================

CONVERT_V4_PROMPT_TEMPLATE = """너는 신용카드 약관/설명서 마크다운을 읽고, 금융 계산 엔진에서 사용할 구조화된 JSON을 생성하는 금융 데이터 파서이다.

[필수 사항] 반드시 아래의 <출력 스키마 v4> 구조를 100% 준수하여 JSON을 생성해야 한다.
해당이 없는 필드(조건)나 제약이 명시되지 않은 필드는 임의로 누락하거나 삭제하지 말고, 반드시 "null" 로 채워 넣어야 한다 (이유: 시스템 구조화를 위해 스키마의 형태를 동일하게 유지해야 하기 때문).

<출력 스키마 v4>
{output_schema}

[서브 카테고리 매핑 규칙]
{sub_category_rules}

[변환 가이드라인]
0. 엄격한 카테고리 매핑 원칙 (절대 위반 금지):
   - 빈번한 오분류 사례 (이 지시를 무조건 따를 것):
     * 골프장/골프연습장: Travel이 아닌 Cultural (sub_category: leisure_sports)
     * 면세점: Travel이 아닌 Shopping (sub_category: duty_free)
     * 렌터카/카셰어링: Traffic이 아닌 Travel (sub_category: rental)
     * 놀이공원/테마파크: Travel이 아닌 Cultural (sub_category: theme_park)
     * 기차(KTX/SRT): Travel이 아닌 Traffic (sub_category: transit)

1. calculation_rule 작성 지침:
   - "비율 할인/적립(예: 10%)" → PERCENTAGE (benefit_rate = 0.10)
   - "정액 할인(예: 5천원 할인)" → FLAT_RATE (flat_discount = 5000)
   - "리터당 N원 할인" 또는 "리터당 N점 적립" → UNIT_BASED (discount_per_unit = 60, unit_label = "liter")
   - "한도 초과 시 1.5% 기본 적립" → fallback_rate: 0.015

2. transaction_conditions (제약 조건 추출):
   - "1회 승인금액 5만원까지 할인" → max_tx_spend_allowed: 50000
   - "건당 1만원 이상 결제시" → min_payment_amount: 10000
   - "연 6회" → max_count_per_year: 6
   - "주말 결제 건 한정" → day_of_week: ["SAT", "SUN"]

3. indirect_benefit_metadata (비경제적 혜택 처리):
   - 공항 라운지 무료, 발레파킹 무료, 바우처 등 직접적인 할인액/포인트 적립이 아닌 혜택은 reward_type: "INDIRECT" 로 할당하고 해당 메타데이터 필드를 채울 것.

4. 복합 카테고리 혜택 분할 및 그룹 한도(SHARED_LIMIT) 분리 지침:
   - 동일한 혜택(행)이 여러 성격이 다른 카테고리(예: 배달, 커피)에 적용될 경우 카테고리마다 benefits 배열 요소를 분할하여 작성하라.
   - 이렇게 하나의 혜택 항목(행)이 여러 카테고리로 분리될 경우, 분리된 혜택들은 한도를 공유하므로 반드시 하나의 통합 `group_id`로 묶어야 한다.
   - 반면 서로 다른 별개의 혜택 항목들(각자의 행)은 한도 부분에 명시적으로 "5천원 (통합)", "통합 1만원" 처럼 서로 공유함이 적혀있는 경우에만 같은 `group_id`로 묶어라.
   - "(위와 동일)", "건당 한도" 수준의 단순 텍스트는 개별 한도라는 의미이므로 같은 그룹으로 묶지 말고 개별 한도(`group_id = null` 내지 각자의 고유 그룹)로 분리하라.

5. 범용 포인트 명칭 및 단위 사용 지침 (환각 방지 원칙 - 절대 위반 금지):
   - reward_unit의 currency는 원문에 기재된 현금/포인트 이름(예: 마이신한포인트, 포인트리 등)을 사용하되, 가장 일반적인 "점/원", "마일리지" 등의 단위는 무조건 "POINT", "KRW", "MILEAGE" 등으로 작성하며 currency_to_krw_rate는 1.0으로 고정한다.
   - 현대카드의 전용 혜택임이 원문에서 명확히 드러나는 상황("M포인트 적립")에서만 M_POINT 및 원문에 명시된 환산비율(예: 0.666)을 사용하라. 
   - 다른 카드사(KB국민카드, 신한카드 등) 문서에서 점수(점)를 마주치더라도 절대 M_POINT를 넣지 마라. (환각 금지)

6. 패키지형 선택 혜택 및 공유 한도의 직교 태그(Orthogonal Tags) 파싱 지침 (최우선순위 적용):
   - 마크다운 원문에 `[그룹이름:선택지명]` (예: `[선택그룹1:선택지A]`) 처럼 배타적 패키지 선택을 지시하는 태그가 존재할 경우:
     * `benefit_groups`에 `group_type: "SELECTIVE_GROUP"` 객체를 만들고 하위 `choices` 배열에 구조화된 패키지 정보(choice_id, choice_name)를 구성하라.
     * 매칭되는 해당 `benefits` 항목 내부에 `selective_choice: {{ "group_id": "생성된 그룹 ID", "choice_id": "선택지의 ID" }}` 를 반드시 부여하라.
     * 절대! 이 배타적 선택형 패키지 혜택들을 `tier_conditions` (전월실적 구간 등) 로 오해하여 병합해서는 안 된다. 서로 철저히 다른 스키마 객체로 분리하여야 한다.
   - 원문에 `[한도공유_이름]` 처럼 공유 한도를 특정하는 직교 태그가 병행 표기되어 있을 경우:
     * 관련된 혜택들의 `group_id` 필드(공유 한도 ID)를 똑같이 부여하여 강제로 한도를 공유시키고, `benefit_groups` 에 `SHARED_LIMIT` 객체를 별도로 등록하라.

결과는 설명이나 주석 없이 오로지 JSON만 반환하라.

[카드사]
{company}

[마크다운 원문]
{markdown_content}
"""

UPDATE_JSON_PROMPT_TEMPLATE = """이전에 파싱한 JSON 결과물이 존재한다.
새로운 마크다운 텍스트를 읽고, 기존 JSON에 누락된 혜택(benefits)이 있거나, 새롭게 갱신해야 할 제약 정보가 있다면 원본 JSON 구조(배열)에 합쳐서(Merge) 단일 JSON으로 반환하라.
새로운 혜택이 발견되었다면 benefits 배열에 추가해주면 된다. 
동일한 구조 포맷을 따르되 설명 없이 JSON만 반환하라.

[기존 JSON 상태]
{previous_json}

[마크다운 원문 파트 (이어서)]
{markdown_content}
"""

# ===========================< 후처리 검증 >============================

def validate_v4(data: dict) -> dict:
    """v4 JSON 후처리 검증."""
    meta = data.get("card_meta", {})
    if not meta.get("card_name"):
        logger.warning("card_name이 비어 있습니다.")
    if not meta.get("card_id"):
        logger.warning("card_id가 비어 있습니다.")

    for b in data.get("benefits", []):
        rule = b.get("calculation_rule", {})
        rate = rule.get("benefit_rate")
        if rate is not None and isinstance(rate, (int, float)) and rate > 1.0:
            logger.info("benefit_rate={} 비정상 교정 (소수점) → {}", rate, b.get('benefit_id'))
            rule["benefit_rate"] = rate / 100.0
            
        fallback = rule.get("fallback_rate")
        if fallback is not None and isinstance(fallback, (int, float)) and fallback > 1.0:
            rule["fallback_rate"] = fallback / 100.0

        cat = b.get("category", "")
        sub = b.get("sub_category", "")
        if sub and sub != "general":
            correct_cat = None
            for parent_cat, subs in VALID_SUB_CATEGORIES.items():
                if sub in subs:
                    correct_cat = parent_cat
                    break
            if correct_cat and correct_cat != cat:
                b["category"] = correct_cat

    if "benefit_groups" not in data:
        data["benefit_groups"] = []

    return data


# ===========================< 변환 실행 >============================

def convert_card(card_key: str, group: dict) -> dict | None:
    """마크다운을 묶어서(또는 분할하여) LLM에게 v4 변환을 요청합니다. (pipeline.py 연동 규격)"""
    
    schema_content = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else "{}"
    
    # 1. 파일별로 문자열 로드
    md_parts = []
    for md_file in group["files"]:
        content = md_file.read_text(encoding="utf-8")
        content = fix_markdown_text(content)
        rel_path = md_file.relative_to(MD_DIR)
        md_parts.append((str(rel_path), content))

    # 2. Chunking 로직 (글자수 제한 비교 후 분할)
    MAX_CHARS = 15000  # 여유분 고려
    chunks = []
    current_chunk = ""
    
    for rel_path, content in md_parts:
        block = f"--- 파일: {rel_path} ---\n{content}\n\n"
        # 현재 청크에 추가했을 때 제한을 넘는다면
        if len(current_chunk) + len(block) > MAX_CHARS:
            if current_chunk:
                chunks.append(current_chunk)
            # 만일 단일 파일 자체가 MAX_CHARS를 넘는다면 (예외처리)
            if len(block) > MAX_CHARS:
                # 어쩔 수 없이 분리해야 하지만 보통 카드는 1만자가 안 넘음
                chunks.append(block[:MAX_CHARS])
                block = block[MAX_CHARS:]
                while len(block) > MAX_CHARS:
                    chunks.append(block[:MAX_CHARS])
                    block = block[MAX_CHARS:]
                current_chunk = block
            else:
                current_chunk = block
        else:
            current_chunk += block
            
    if current_chunk:
        chunks.append(current_chunk)

    # 3. LLM Request Process
    name_info = CARD_NAME_MAP.get(card_key)
    name_hint = ""
    if name_info:
        name_hint = f"\\n\\n[중요] 이 카드의 이름은 '{name_info['card_name']}', card_id는 '{name_info['card_id']}'이다."

    final_result = None
    
    for i, chunk in enumerate(chunks):
        if i == 0:
            prompt = CONVERT_V4_PROMPT_TEMPLATE.format(
                output_schema=schema_content,
                sub_category_rules=build_prompt_block(),
                company=group["company_kr"],
                markdown_content=chunk
            ) + name_hint
        else:
            print(f"    [INFO] 글자수 오버. 청크 {i+1}/{len(chunks)} 추가 파싱 실행 중 (누적 모드)")
            prompt = UPDATE_JSON_PROMPT_TEMPLATE.format(
                previous_json=json.dumps(final_result, ensure_ascii=False, indent=2),
                markdown_content=chunk
            )

        try:
            start = time.time()
            response = llm.invoke([SystemMessage(content=prompt)]).content
            elapsed = time.time() - start
            print(f"    LLM 응답 (chunk {i+1}): {elapsed:.1f}초")

            chunk_result = parse_json_response(response if isinstance(response, str) else str(response))
            final_result = chunk_result  # 누적 업데이트된 결과를 사용
            
        except Exception as e:
            print(f"    [ERROR] 변환 실패 (chunk {i+1}): {e}")
            return final_result  # 실패 시 지금까지 모은 거라도 반환

    # 4. 검증 및 반환
    if final_result:
        final_result = validate_v4(final_result)
        # card_meta 강제 보호
        if name_info:
            final_result.setdefault("card_meta", {})
            final_result["card_meta"]["card_name"] = name_info["card_name"]
            final_result["card_meta"]["card_id"] = name_info["card_id"]

    return final_result


def main():
    parser = argparse.ArgumentParser(description="마크다운 → JSON v4 변환")
    parser.add_argument("--card", type=str, help="특정 카드만 변환 (키워드)")
    parser.add_argument("--company", type=str, help="특정 카드사만 변환 (kb/shinhan/hyundai)")
    parser.add_argument("--dry-run", action="store_true", help="그룹핑만 확인")
    args = parser.parse_args()
    
    logger.info("=== 마크다운 파일 그룹핑 시작 ===")
    groups = group_markdown_files()

    if args.company:
        groups = {k: v for k, v in groups.items() if v["company"] == args.company}
    if args.card:
        keyword = args.card.lower()
        groups = {k: v for k, v in groups.items() if keyword in k.lower()}

    logger.info("총 {}개 카드 그룹 발견", len(groups))
    for key, group in sorted(groups.items()):
        logger.debug("[{}] ({}) — 파일 {}개", key, group['company_kr'], len(group['files']))

    if args.dry_run:
        logger.info("[DRY RUN] LLM 호출 없이 종료합니다.")
        return

    logger.info("=== JSON v4 변환 시작 ({}개 카드) ===", len(groups))
    success = 0
    fail = 0

    for card_key, group in sorted(groups.items()):
        company = group["company"]
        logger.info("변환 진행 중: {}", card_key)

        result = convert_card(card_key, group)
        if not result:
            fail += 1
            logger.warning("결과값이 반환되지 않음: {}", card_key)
            continue

        out_dir = DST_DIR / company
        out_dir.mkdir(parents=True, exist_ok=True)

        card_id = result.get("card_meta", {}).get("card_id", card_key)
        safe_name = re.sub(r"[^\w\-]", "_", card_id)
        out_path = out_dir / f"{safe_name}.json"

        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("저장 성공: {}", out_path.relative_to(ROOT))
        success += 1

    logger.info("=== 완료: 성공 {}개, 실패 {}개 ===", success, fail)

if __name__ == "__main__":
    main()
