"""
카드 혜택 Compact Digest 생성 스크립트

기존 JSON 데이터를 LLM에 전달하여 마크다운 형식의 요약본을 생성합니다.
LLM 프롬프트 입력용으로, 카드 혜택 정보를 토큰 효율적으로 전달하기 위한 포맷입니다.

사용법: python3 -m scripts.generate_digest
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
DST_DIR = ROOT / "datasets" / "digest"

# ===========================< LLM 프롬프트 >============================

DIGEST_PROMPT = """너는 신용카드 혜택 정보를 간결하고 구조화된 마크다운 요약본으로 변환하는 금융 데이터 요약 전문가이다.

아래의 카드 혜택 JSON 데이터를 읽고, 카드 추천 시스템의 LLM이 빠르게 이해할 수 있는 Compact Digest 마크다운으로 변환하라.

[출력 형식]

```
# 카드명
연회비: 국내 X원 / 해외 Y원 (또는 단일 금액)
전월 실적: X원 이상 (특이 조건 있으면 괄호로 표기)

## 카테고리 (영문키워드) — 혜택유형 비율/금액
혜택 내용 1줄 요약
- 실적구간별 한도 (있으면)
⚠ 주의사항/제외조건 (있으면)

## 카테고리 (영문키워드) — 혜택유형 비율/금액  [통합한도 공유]
(통합 한도를 공유하는 혜택들은 [통합한도 공유]로 표시)
```

[카테고리 영문 키워드 매핑]
반드시 아래 키워드 중 하나를 괄호 안에 표기할 것:
General, Shopping, Traffic, Food, Coffee, Cultural, Travel, Life, EduHealth, Others

[규칙]
1. 각 혜택을 ## 섹션으로 구분한다.
2. 혜택유형은 "청구할인", "포인트적립", "캐시백" 등 원문 그대로 간결하게 표기한다.
3. 할인율/적립률이 있으면 퍼센트로 표기한다. 정액이면 금액을 표기한다.
4. 실적 구간별로 한도가 다르면 구간별로 나열한다.
5. 통합 한도를 공유하는 혜택들은 [통합한도 공유]로 명시한다.
6. 계산 불가능한 혜택(라운지, 이벤트, 선지급 등)은 맨 아래 "기타 혜택"으로 묶어 1줄씩 표기한다.
7. 원문에 없는 정보는 절대 추가하지 마라.
8. 설명 없이 마크다운만 출력하라. 코드블록(```)으로 감싸지 마라.

[입력 데이터]
{card_data}
"""


def generate_digest(src_path: Path) -> str:
    """하나의 카드 JSON을 compact digest 마크다운으로 변환합니다."""
    raw_text = src_path.read_text(encoding="utf-8")
    prompt = DIGEST_PROMPT.format(card_data=raw_text)

    try:
        response = llm.invoke([SystemMessage(content=prompt)]).content
        return response if isinstance(response, str) else str(response)
    except Exception as e:
        print(f"    [ERROR] LLM 변환 실패: {e}")
        return ""


def main():
    print(f"원본: {SRC_DIR}")
    print(f"출력: {DST_DIR}\n")

    total_files = 0

    for company_dir in sorted(SRC_DIR.iterdir()):
        if not company_dir.is_dir():
            continue

        dst_company_dir = DST_DIR / company_dir.name
        dst_company_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{company_dir.name}]")

        for json_file in sorted(company_dir.glob("*.json")):
            print(f"  변환 중: {json_file.name}")
            digest = generate_digest(json_file)

            if not digest:
                print(f"    [SKIP] 변환 실패")
                continue

            dst_path = dst_company_dir / f"{json_file.stem}.md"
            dst_path.write_text(digest, encoding="utf-8")

            total_files += 1
            print(f"    완료: {dst_path.name}")

    print(f"\n{'=' * 40}")
    print(f"총 {total_files}개 파일 변환 완료")
    print(f"출력 위치: {DST_DIR}")


if __name__ == "__main__":
    main()
