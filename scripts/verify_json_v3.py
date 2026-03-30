"""
JSON v3 검증 스크립트

생성된 json_v3/ 파일들의 스키마 정합성 + 마크다운 원문 대비 누락/오류를 검증합니다.

사용법: python -m scripts.verify_json_v3
옵션:
  --card <키워드>     특정 카드만 검증
  --company <회사명>  특정 카드사만 검증
  --llm              LLM을 사용한 심층 검증 (마크다운 대비 누락 체크)
"""

import os
import json
import argparse
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

JSON_V3_DIR = ROOT / "datasets" / "json_v3"
MD_DIR = ROOT / "datasets" / "markdown_upstage"

# ===========================< 스키마 검증 >============================

VALID_CATEGORIES = {
    "General", "Shopping", "Traffic", "Food", "Coffee", "Dining_FNB",
    "Cultural", "Travel", "Life", "EduHealth", "Streaming",
    "All_Domestic", "Others",
}

VALID_CALC_METHODS = {
    "RATE", "FIXED_AMOUNT", "FIXED_PER_VOLUME",
    "MAX_COVER_UP_TO_LIMIT", "TIERED_RATE_BY_TRANSACTION",
}

VALID_REWARD_TYPES = {"DISCOUNT", "POINT", "CASHBACK", "VOUCHER", "MILEAGE"}
VALID_FREQUENCIES = {"MONTHLY", "QUARTERLY", "ANNUAL", "ONCE"}
VALID_GROUP_TYPES = {"SHARED_LIMIT", "USER_CHOICE_ONE", "AUTO_TOP_N"}


def verify_schema(data: dict, filename: str) -> list[str]:
    """JSON v3 스키마 정합성 검증. 문제 목록을 반환."""
    issues = []

    # --- card_meta ---
    meta = data.get("card_meta")
    if not meta:
        issues.append("[CRITICAL] card_meta 없음")
        return issues

    for field in ["card_id", "card_name", "card_company"]:
        if not meta.get(field):
            issues.append(f"[ERROR] card_meta.{field} 비어 있음")

    if not isinstance(meta.get("annual_fee", 0), (int, float)):
        issues.append(f"[ERROR] annual_fee 타입 오류: {meta.get('annual_fee')}")

    if not isinstance(meta.get("minimum_performance", 0), (int, float)):
        issues.append(f"[ERROR] minimum_performance 타입 오류: {meta.get('minimum_performance')}")

    if meta.get("annual_fee", 0) < 0:
        issues.append(f"[WARN] annual_fee 음수: {meta['annual_fee']}")

    if meta.get("minimum_performance", 0) < 0:
        issues.append(f"[WARN] minimum_performance 음수: {meta['minimum_performance']}")

    # --- benefit_groups ---
    groups = data.get("benefit_groups", [])
    group_ids = set()
    for g in groups:
        gid = g.get("group_id", "")
        if not gid:
            issues.append("[ERROR] benefit_group에 group_id 없음")
        if gid in group_ids:
            issues.append(f"[ERROR] 중복 group_id: {gid}")
        group_ids.add(gid)

        gtype = g.get("group_type", "")
        if gtype not in VALID_GROUP_TYPES:
            issues.append(f"[WARN] 알 수 없는 group_type: {gtype}")

    # --- benefits ---
    benefits = data.get("benefits", [])
    if not benefits:
        issues.append("[CRITICAL] benefits 배열이 비어 있음")

    benefit_ids = set()
    for i, b in enumerate(benefits):
        bid = b.get("benefit_id", "")
        if not bid:
            issues.append(f"[ERROR] benefits[{i}] benefit_id 없음")
        if bid in benefit_ids:
            issues.append(f"[ERROR] 중복 benefit_id: {bid}")
        benefit_ids.add(bid)

        # category 검증
        cat = b.get("category", "")
        if cat not in VALID_CATEGORIES:
            issues.append(f"[ERROR] benefits[{i}] 잘못된 category: {cat}")

        # reward_type 검증
        rtype = b.get("reward_type", "")
        if rtype not in VALID_REWARD_TYPES:
            issues.append(f"[WARN] benefits[{i}] 알 수 없는 reward_type: {rtype}")

        # frequency 검증
        freq = b.get("frequency", "")
        if freq not in VALID_FREQUENCIES:
            issues.append(f"[WARN] benefits[{i}] 알 수 없는 frequency: {freq}")

        # calculation_rule 검증
        rule = b.get("calculation_rule", {})
        method = rule.get("calc_method", "")
        if method not in VALID_CALC_METHODS:
            issues.append(f"[ERROR] benefits[{i}] 잘못된 calc_method: {method}")

        rate = rule.get("rate")
        if rate is not None and isinstance(rate, (int, float)):
            if rate > 1.0:
                issues.append(f"[ERROR] benefits[{i}] rate > 1.0: {rate} (퍼센트를 소수로 변환하지 않음)")
            elif rate < 0:
                issues.append(f"[ERROR] benefits[{i}] rate 음수: {rate}")

        # group_id 참조 검증
        ref_gid = b.get("group_id")
        if ref_gid and ref_gid not in group_ids:
            issues.append(f"[ERROR] benefits[{i}] 참조된 group_id '{ref_gid}'가 benefit_groups에 없음")

        # tier_conditions 검증
        tiers = b.get("tier_conditions", [])
        if tiers:
            prev_perf = -1
            for t in tiers:
                perf = t.get("min_prev_performance", 0)
                if perf < prev_perf:
                    issues.append(f"[WARN] benefits[{i}] tier 정렬 오류: {perf} < {prev_perf}")
                prev_perf = perf

                tier_rate = t.get("reward_rate")
                if tier_rate is not None and isinstance(tier_rate, (int, float)) and tier_rate > 1.0:
                    issues.append(f"[ERROR] benefits[{i}] tier reward_rate > 1.0: {tier_rate}")

    return issues


# ===========================< LLM 심층 검증 >============================

def verify_with_llm(json_data: dict, md_files: list[Path]) -> list[str]:
    """LLM을 사용하여 마크다운 원문 대비 JSON 누락/오류를 검증합니다."""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import SystemMessage

    llm = init_chat_model(model="solar-pro2", temperature=0.0)

    # 마크다운 합치기
    md_parts = []
    for f in md_files:
        content = f.read_text(encoding="utf-8")
        md_parts.append(content)
    combined_md = "\n\n---\n\n".join(md_parts)
    if len(combined_md) > 12000:
        combined_md = combined_md[:12000] + "\n... (이하 생략)"

    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
    if len(json_str) > 8000:
        json_str = json_str[:8000] + "\n... (이하 생략)"

    prompt = f"""너는 신용카드 JSON 데이터의 정확성을 검증하는 QA 전문가이다.

아래 [마크다운 원문]과 [생성된 JSON]을 비교하여 문제점을 찾아라.

검증 항목:
1. 누락된 혜택: 마크다운에 있지만 JSON benefits에 없는 혜택
2. 잘못된 수치: 할인율, 한도, 연회비, 전월실적 등이 마크다운과 다른 경우
3. 카테고리 오류: 혜택의 category가 부적절한 경우
4. 구조 오류: benefit_groups와 benefits의 group_id 참조가 맞지 않는 경우

결과를 아래 JSON 형식으로만 반환:
{{
  "missing_benefits": ["누락된 혜택 설명1", ...],
  "wrong_values": ["잘못된 값 설명1", ...],
  "category_errors": ["카테고리 오류 설명1", ...],
  "other_issues": ["기타 문제1", ...],
  "accuracy_score": 0~100 (정확도 점수)
}}

[마크다운 원문]
{combined_md}

[생성된 JSON]
{json_str}
"""

    try:
        response = llm.invoke([SystemMessage(content=prompt)]).content
        # JSON 파싱
        import re
        cleaned = re.sub(r"```json\s*", "", response)
        cleaned = re.sub(r"```\s*", "", cleaned).strip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            result = json.loads(m.group())
        else:
            return [f"[LLM] 응답 파싱 실패"]

        issues = []
        score = result.get("accuracy_score", "?")
        issues.append(f"[LLM] 정확도 점수: {score}/100")

        for item in result.get("missing_benefits", []):
            issues.append(f"[LLM-누락] {item}")
        for item in result.get("wrong_values", []):
            issues.append(f"[LLM-수치오류] {item}")
        for item in result.get("category_errors", []):
            issues.append(f"[LLM-카테고리] {item}")
        for item in result.get("other_issues", []):
            issues.append(f"[LLM-기타] {item}")

        return issues

    except Exception as e:
        return [f"[LLM] 검증 실패: {e}"]


# ===========================< 메인 >============================

def find_md_files_for_card(card_id: str, company: str) -> list[Path]:
    """card_id에 해당하는 마크다운 파일들을 찾습니다."""
    company_dir = MD_DIR / company
    if not company_dir.exists():
        return []
    return list(company_dir.rglob("*.md"))


def main():
    parser = argparse.ArgumentParser(description="JSON v3 검증")
    parser.add_argument("--card", type=str, help="특정 카드만 검증 (키워드)")
    parser.add_argument("--company", type=str, help="특정 카드사만 검증")
    parser.add_argument("--llm", action="store_true", help="LLM 심층 검증 활성화")
    args = parser.parse_args()

    print("=== JSON v3 검증 시작 ===\n")

    json_files = list(JSON_V3_DIR.rglob("*.json"))
    if not json_files:
        print("[ERROR] json_v3/ 디렉토리에 JSON 파일이 없습니다.")
        return

    # 필터링
    if args.company:
        json_files = [f for f in json_files if f.parent.name == args.company]
    if args.card:
        keyword = args.card.lower()
        json_files = [f for f in json_files if keyword in f.stem.lower()]

    total = len(json_files)
    print(f"검증 대상: {total}개 JSON 파일\n")

    summary = {
        "total": total,
        "pass": 0,
        "warn": 0,
        "fail": 0,
        "details": [],
    }

    for json_file in sorted(json_files):
        rel = json_file.relative_to(ROOT)
        data = json.loads(json_file.read_text(encoding="utf-8"))
        card_name = data.get("card_meta", {}).get("card_name", json_file.stem)
        company = json_file.parent.name

        print(f"── {card_name} ({rel}) ──")

        # 1) 스키마 검증
        issues = verify_schema(data, json_file.name)

        # 2) LLM 심층 검증 (옵션)
        if args.llm:
            print("    LLM 검증 중...")
            # generate_json_v3의 그룹핑을 재사용하기 어려우므로
            # 간단히 해당 카드사 전체 마크다운에서 카드명으로 필터링
            from scripts.generate_json_v3 import group_markdown_files
            groups = group_markdown_files()
            # card_id로 매칭되는 그룹 찾기
            card_id = data.get("card_meta", {}).get("card_id", "")
            matched_files = []
            for key, group in groups.items():
                if group["company"] == company:
                    # 키 또는 card_id가 포함되면 매칭
                    if card_id and card_id.replace("_", " ") in key.replace("_", " "):
                        matched_files = group["files"]
                        break
                    if json_file.stem.replace("_", " ") in key.replace("_", " "):
                        matched_files = group["files"]
                        break

            if matched_files:
                start = time.time()
                llm_issues = verify_with_llm(data, matched_files)
                elapsed = time.time() - start
                print(f"    LLM 검증 완료: {elapsed:.1f}초")
                issues.extend(llm_issues)
            else:
                issues.append("[WARN] 매칭되는 마크다운 파일을 찾지 못함")

        # 결과 출력
        errors = [i for i in issues if i.startswith("[ERROR]") or i.startswith("[CRITICAL]")]
        warns = [i for i in issues if i.startswith("[WARN]")]
        llm_items = [i for i in issues if i.startswith("[LLM")]

        benefits_count = len(data.get("benefits", []))
        groups_count = len(data.get("benefit_groups", []))

        if errors:
            status = "FAIL"
            summary["fail"] += 1
        elif warns:
            status = "WARN"
            summary["warn"] += 1
        else:
            status = "PASS"
            summary["pass"] += 1

        print(f"    상태: {status} | 혜택: {benefits_count}개 | 그룹: {groups_count}개")
        for issue in issues:
            print(f"    {issue}")
        print()

        summary["details"].append({
            "card_name": card_name,
            "file": str(rel),
            "status": status,
            "benefits_count": benefits_count,
            "groups_count": groups_count,
            "issues": issues,
        })

    # 요약
    print("=" * 50)
    print(f"검증 결과 요약:")
    print(f"  PASS: {summary['pass']}개")
    print(f"  WARN: {summary['warn']}개")
    print(f"  FAIL: {summary['fail']}개")
    print(f"  총: {summary['total']}개")

    # 검증 결과 저장
    report_path = ROOT / "test_logs" / "json_v3_verify_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[LOG] 검증 리포트 저장: {report_path}")


if __name__ == "__main__":
    main()
