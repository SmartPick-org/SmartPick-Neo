"""
카드 혜택 Compact Digest 생성 스크립트 (V4 통합)

JSON v4 데이터를 LLM에 전달하여 마크다운 형식의 요약본을 생성합니다.
추천 엔진의 설명용 LLM(advisor)이 카드의 오프라인/시간 제약이나 부가 혜택 등을 
토큰 효율적으로 이해할 수 있도록 설계된 포맷입니다.

사용법: uv run python -m calc_refactor.generate_digest_v4
옵션:
  --card <키워드>       특정 카드만 변환
  --company <회사명>    특정 카드사만 변환
  --no-sub-category     sub_category 없이 기존 형식으로 생성
"""

import argparse
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from loguru import logger

# ===========================< Setting >============================
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = "solar-pro2"
# MODEL = "gpt-4o"
llm = init_chat_model(model=MODEL, temperature=0.0)

SRC_DIR = ROOT / "datasets" / "json_v4"
DST_DIR = ROOT / "datasets" / "digest_v4"

# ===========================< LLM 프롬프트 >============================

DIGEST_PROMPT_WITH_SUB = """너는 신용카드 혜택 정보(JSON v4)를 간결하고 구조화된 마크다운 요약본으로 변환하는 금융 데이터 요약 전문가이다.

아래의 카드 혜택 JSON 데이터를 읽고, 카드 설명/QnA 시스템의 기반 지식으로 쓰일 Compact Digest 마크다운으로 변환하라.

[출력 형식]

```
# 카드명
연회비: 국내 X원 / 해외 Y원 (또는 단일 금액)
전월 실적: X원 이상 (특이 조건 있으면 괄호 표기)

## 서브카테고리_한글명 (카테고리/sub_category) — 혜택유형 비율/금액
혜택 내용 1줄 요약
- 실적구간별 월 한도 (있으면 기재)
- 연간 한도/제공횟수 (있으면 기재. 예: 연 6회)
⚠ 주의사항: 특별 요일 가중치, 시간 제한(time_of_day), 온/오프라인 전용 여부, 기타 전월실적 제외 유무 등 모든 물리적/정성적 제약을 묶어서 1~2줄로 표기.

## 서브카테고리_한글명 (카테고리/sub_category) — 혜택유형 비율/금액  [통합한도 공유]
(통합 한도를 공유하는 혜택들은 [통합한도 공유] 태그를 붙여서 표시)

## 비경제적/간접 혜택 (기타)
- 라운지 (공항 라운지 무료 연 2회 등)
- 발렛파킹 (호텔 발렛 무료 등)
- 바우처 (10만원권 바우처, 쇼핑/호텔 선택 등)
```

[카테고리 영문 키워드 매핑]
반드시 아래 키워드 중 하나를 괄호 안에 표기할 것:
General, Shopping, Traffic, Food, Coffee, Cultural, Travel, Life, EduHealth, Others

[sub_category 매핑]
JSON의 "sub_category" 필드가 있으면 카테고리 뒤에 슬래시로 구분하여 표기.
예: (Traffic/transit), (Traffic/fuel), (Shopping/mart), (Life/telecom)
해당 필드가 없으면 카테고리만 표기: (General), (Others)

[서브카테고리 한글명]
## 섹션 제목에 해당 혜택의 실질적인 한글 서브카테고리 명칭을 사용.
예: "대중교통", "주유", "택시", "편의점", "공과금", "항공 마일리지"

[V4 기반 변환 규칙 - 매우 중요]
1. 각 혜택을 ## 섹션으로 구분한다.
2. V4 스키마의 "calculation_rule"을 참고하여 혜택 비율(benefit_rate), 정액(flat_discount) 등을 판별해 표기한다.
3. V4 스키마의 "transaction_conditions" 안에 있는 day_of_week 요일 제한, time_of_day 시간 제한 등을 분석하여 반드시 "⚠ 주의사항" 섹션에 통합 기재한다.
4. "indirect_benefit_metadata"가 기재되어 있거나 "reward_type"이 INDIRECT 인 경우 계산 혜택에 넣지 말고 맨 밑의 "## 비경제적/간접 혜택 (기타)" 항목으로 몰아서 간결히 정리한다.
5. 연간 제한 캡(max_count_per_year, annual_benefit_limit)은 절대로 생략하지 말고 명시한다.
6. 복합 혜택(같은 원본 설명을 갖는 여러 카테고리로 분할된 항목들)이 흩어져 있다면, [원문: 전체 혜택 문구] 형식으로 묶어 표기해 준다.
7. 설명이나 주석 없이 마크다운 텍스트만 출력한다.

[입력 데이터]
{card_data}
"""

DIGEST_PROMPT_WITHOUT_SUB = """너는 신용카드 혜택 정보(JSON v4)를 간결하고 구조화된 마크다운 요약본으로 변환하는 금융 데이터 요약 전문가이다.

아래의 카드 혜택 JSON 데이터를 읽고, 카드 설명/QnA 시스템의 기반 지식으로 쓰일 Compact Digest 마크다운으로 변환하라.

[출력 형식]

```
# 카드명
연회비: 국내 X원 / 해외 Y원 (또는 단일 금액)
전월 실적: X원 이상 (특이 조건 있으면 괄호 표기)

## 카테고리 (영문키워드) — 혜택유형 비율/금액
혜택 내용 1줄 요약
- 실적구간별 월 한도 (있으면 기재)
- 연간 한도/제공횟수 (있으면 기재. 예: 연 6회)
⚠ 주의사항: 특별 요일 가중치, 시간 제한(time_of_day), 온/오프라인 전용 여부, 기타 전월실적 제외 유무 등 모든 물리적/정성적 제약을 묶어서 1~2줄로 표기.

## 카테고리 (영문키워드) — 혜택유형 비율/금액  [통합한도 공유]
(통합 한도를 공유하는 혜택들은 [통합한도 공유] 태그를 붙여서 표시)

## 비경제적/간접 혜택 (기타)
- 라운지 (공항 라운지 무료 연 2회 등)
- 발렛파킹 (호텔 발렛 무료 등)
- 바우처 (10만원권 바우처, 쇼핑/호텔 선택 등)
```

[카테고리 영문 키워드 매핑]
반드시 아래 키워드 중 하나를 괄호 안에 표기할 것:
General, Shopping, Traffic, Food, Coffee, Cultural, Travel, Life, EduHealth, Others

[V4 기반 변환 규칙 - 매우 중요]
1. 각 혜택을 ## 섹션으로 구분한다.
2. V4 스키마의 "calculation_rule"을 참고하여 혜택 비율(benefit_rate), 정액(flat_discount) 등을 판별해 표기한다.
3. V4 스키마의 "transaction_conditions" 안에 있는 day_of_week 요일 제한, time_of_day 시간 제한 등을 분석하여 반드시 "⚠ 주의사항" 섹션에 통합 기재한다.
4. "indirect_benefit_metadata"가 기재되어 있거나 "reward_type"이 INDIRECT 인 경우 계산 혜택에 넣지 말고 맨 밑의 "## 비경제적/간접 혜택 (기타)" 항목으로 몰아서 간결히 정리한다.
5. 연간 제한 캡(max_count_per_year, annual_benefit_limit)은 절대로 생략하지 말고 명시한다.
6. 설명이나 주석 없이 마크다운 텍스트만 출력한다.

[입력 데이터]
{card_data}
"""


def generate_digest(src_path: Path, use_sub_category: bool = True) -> str:
    """하나의 카드 v4 JSON을 compact digest 마크다운으로 변환합니다."""
    # 만약 V4 경로에 파일이 없다면 fail-fast
    if not src_path.exists():
        logger.error("JSON 파일을 찾을 수 없습니다: {}", src_path)
        return ""
        
    raw_text = src_path.read_text(encoding="utf-8")
    prompt_template = DIGEST_PROMPT_WITH_SUB if use_sub_category else DIGEST_PROMPT_WITHOUT_SUB
    prompt = prompt_template.format(card_data=raw_text)

    try:
        response = llm.invoke([SystemMessage(content=prompt)]).content
        return response if isinstance(response, str) else str(response)
    except Exception as e:
        logger.error("LLM 다이제스트 변환 실패 ({}): {}", src_path.name, e)
        return ""


def main():
    parser = argparse.ArgumentParser(description="카드 혜택 Compact Digest V4 생성")
    parser.add_argument("--card", type=str, help="특정 카드만 변환 (키워드)")
    parser.add_argument("--company", type=str, help="특정 카드사만 변환")
    parser.add_argument("--no-sub-category", action="store_true", help="sub_category 없이 기존 형식으로 생성")
    parser.add_argument("--dst", type=str, help="출력 디렉토리 (기본: datasets/digest_v4)")
    args = parser.parse_args()

    use_sub = not args.no_sub_category
    dst_dir = Path(args.dst) if args.dst else DST_DIR

    logger.info("=== Digest 작업 시작 ===")
    logger.info("입력 경로 (JSON v4): {}", SRC_DIR)
    logger.info("출력 경로 (Digest v4): {}", dst_dir)
    logger.info("sub_category 여부: {}", '포함' if use_sub else '미포함')

    total_files = 0
    
    if not SRC_DIR.exists():
        logger.warning("지정된 소스 디렉토리가 존재하지 않습니다: {}", SRC_DIR)
        return

    for company_dir in sorted(SRC_DIR.iterdir()):
        if not company_dir.is_dir():
            continue

        if args.company and company_dir.name != args.company:
            continue

        dst_company_dir = dst_dir / company_dir.name
        dst_company_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[진행 상황] 카드사: {}", company_dir.name)

        for json_file in sorted(company_dir.glob("*.json")):
            if args.card and args.card.lower() not in json_file.stem.lower():
                continue

            logger.info("  변환 중: {}", json_file.name)
            digest = generate_digest(json_file, use_sub_category=use_sub)

            if not digest:
                logger.warning("  [SKIP] 변환 빈 값 반환: {}", json_file.name)
                continue

            dst_path = dst_company_dir / f"{json_file.stem}.md"
            dst_path.write_text(digest, encoding="utf-8")

            total_files += 1
            logger.debug("  완료: {}", dst_path.name)

    logger.info("====================================")
    logger.info("총 {}개 파일 변환 완료", total_files)
    logger.info("처리 완료. 결과 경로: {}", dst_dir)

if __name__ == "__main__":
    main()
