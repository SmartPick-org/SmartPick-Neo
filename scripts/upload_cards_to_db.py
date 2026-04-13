"""
json → Supabase DB 업로더

키 매핑:
  [cards 테이블]
    card_meta.card_id             → card_slug
    card_meta.card_name           → card_name
    card_meta.card_company        → card_company
    card_meta.annual_fee          → annual_fee
    card_meta.minimum_performance → min_performance   ← 키 이름 불일치 수정
    card_meta.reward_currency     → reward_currency
    card_meta.currency_to_krw_rate → currency_rate   ← 키 이름 불일치 수정
    image_url                     → null (JSON에 없음, 별도 처리)
    digest_file_path              → "digest/{card_id}.md" (경로 규칙 기반 추론)
    manual_file_path              → null (JSON에 없음, 별도 처리)

  [card_benefit_groups 테이블]
    benefit_groups[].group_id     → group_slug       ← 키 이름 불일치 수정
    benefit_groups[].group_name   → group_name
    benefit_groups[].group_type   → group_type
    benefit_groups[].limit_amount → limit_amount
    (top_n_count 은 DB 미저장 — 그룹 제한 로직은 group_type으로 이미 표현됨)

  [card_benefits 테이블]
    benefits[].benefit_id         → benefit_slug     ← 키 이름 불일치 수정
    benefits[].category           → category
    benefits[].content            → content
    benefits[].reward_type        → reward_type
    benefits[].calculation_rule   → calculation_rule (jsonb)
    benefits[].transaction_conditions → transaction_conditions (jsonb)
    benefits[].ui_warnings        → ui_warnings
    (frequency, tier_conditions, edge_case_flags 처리는 하단 주석 참고)

사용법:
  python -m scripts.upload_cards_to_db
  python -m scripts.upload_cards_to_db --company hyundai
  python -m scripts.upload_cards_to_db --dry-run
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_V3_DIR = ROOT / "datasets" / "json"


# ---------------------------------------------------------------------------
# 키 매핑 헬퍼
# ---------------------------------------------------------------------------

def map_card_meta(card_id: str, meta: dict) -> dict:
    """card_meta 블록 → cards 테이블 row"""
    return {
        # card_slug: JSON의 card_id 값 그대로 사용 (e.g. "hyundai_digital_lover")
        "card_slug": card_id,
        "card_name": meta.get("card_name", ""),
        "card_company": meta.get("card_company", ""),
        "annual_fee": meta.get("annual_fee", 0),
        # minimum_performance → min_performance (키 이름 불일치 수정)
        "min_performance": meta.get("minimum_performance", 0),
        "reward_currency": meta.get("reward_currency", "KRW"),
        # currency_to_krw_rate → currency_rate (키 이름 불일치 수정)
        "currency_rate": meta.get("currency_to_krw_rate", 1.0),
        # image_url: JSON에 없음. null로 두고 별도 운영 작업으로 채움
        "image_url": None,
        # digest_file_path: Supabase Storage 버킷 경로 규칙에 따라 추론
        #   Digest 버킷 구조: {company}/{card_id}.md
        "digest_file_path": f"digest/{card_id}.md",
        # manual_file_path: JSON에 없음. null로 두고 별도 운영 작업으로 채움
        "manual_file_path": None,
    }


def map_benefit_group(card_uuid: str, group: dict) -> dict:
    """benefit_groups 항목 → card_benefit_groups 테이블 row"""
    return {
        "card_id": card_uuid,
        # group_id → group_slug (키 이름 불일치 수정)
        "group_slug": group.get("group_id", ""),
        "group_name": group.get("group_name", ""),
        "group_type": group.get("group_type", ""),
        "limit_amount": group.get("limit_amount"),
        # top_n_count: DB 미저장 (설계 근거는 README/분석 문서 참고)
    }


def map_benefit(group_uuid: str, benefit: dict) -> dict:
    """benefits 항목 → card_benefits 테이블 row"""
    return {
        "group_id": group_uuid,
        # benefit_id → benefit_slug (키 이름 불일치 수정)
        "benefit_slug": benefit.get("benefit_id", ""),
        "category": benefit.get("category", ""),
        "content": benefit.get("content", ""),
        "reward_type": benefit.get("reward_type", ""),
        # calculation_rule: jsonb — 구조 그대로 저장
        "calculation_rule": benefit.get("calculation_rule"),
        # transaction_conditions: jsonb — 구조 그대로 저장
        "transaction_conditions": benefit.get("transaction_conditions"),
        # ui_warnings: text[] 또는 jsonb — 배열 그대로 저장
        "ui_warnings": benefit.get("ui_warnings", []),
        # --- DB 미저장 필드 (설계 근거는 README/분석 문서 참고) ---
        # frequency:         calculation_rule.calc_method로 충분히 표현됨
        # tier_conditions:   calculation_rule.transaction_tiers으로 통합
        # edge_case_flags:   calculator 런타임 전용, DB 저장 불필요
    }


# ---------------------------------------------------------------------------
# 업로드 로직
# ---------------------------------------------------------------------------

def upload_json_file(db, json_path: Path, dry_run: bool) -> bool:
    """단일 JSON v3 파일을 DB에 upsert합니다."""
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    meta = raw.get("card_meta", {})
    card_id: str = meta.get("card_id", "")

    if not card_id:
        print(f"  [SKIP] card_id 없음: {json_path.name}")
        return False

    # 1. cards 테이블 upsert
    card_row = map_card_meta(card_id, meta)
    print(f"  [cards] upsert → card_slug={card_id}")
    if not dry_run:
        res = db.table("cards").upsert(card_row, on_conflict="card_slug").execute()
        card_uuid = res.data[0]["id"]
    else:
        card_uuid = f"<dry-run-uuid-{card_id}>"

    # 2. card_benefit_groups 테이블 upsert
    for group in raw.get("benefit_groups", []):
        group_row = map_benefit_group(card_uuid, group)
        group_slug = group_row["group_slug"]
        print(f"    [card_benefit_groups] upsert → group_slug={group_slug}")
        if not dry_run:
            g_res = db.table("card_benefit_groups").upsert(
                group_row, on_conflict="card_id,group_slug"
            ).execute()
            group_uuid = g_res.data[0]["id"]
        else:
            group_uuid = f"<dry-run-group-uuid-{group_slug}>"

        # 3. card_benefits 테이블 upsert (해당 그룹 소속 혜택만)
        group_benefits = [b for b in raw.get("benefits", []) if b.get("group_id") == group.get("group_id")]
        for benefit in group_benefits:
            benefit_row = map_benefit(group_uuid, benefit)
            print(f"      [card_benefits] upsert → benefit_slug={benefit_row['benefit_slug']}")
            if not dry_run:
                db.table("card_benefits").upsert(
                    benefit_row, on_conflict="group_id,benefit_slug"
                ).execute()

    return True


def main():
    parser = argparse.ArgumentParser(description="json → Supabase DB 업로더")
    parser.add_argument("--company", type=str, help="특정 카드사만 처리 (e.g. hyundai, kb, shinhan)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 실제로 쓰지 않고 매핑 결과만 출력")
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY-RUN 모드] DB에 실제로 쓰지 않습니다.\n")
        db = None
    else:
        from app.core.database import get_supabase
        db = get_supabase()

    search_dir = JSON_V3_DIR / args.company if args.company else JSON_V3_DIR
    json_files = list(search_dir.rglob("*.json"))

    if not json_files:
        print(f"[INFO] 처리할 JSON 파일이 없습니다: {search_dir}")
        return

    print(f"총 {len(json_files)}개 파일 처리 시작\n")
    success, fail = 0, 0
    for jf in sorted(json_files):
        print(f"[{jf.relative_to(JSON_V3_DIR)}]")
        try:
            ok = upload_json_file(db, jf, dry_run=args.dry_run)
            if ok:
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            fail += 1

    print(f"\n완료 — 성공: {success}건, 실패: {fail}건")


if __name__ == "__main__":
    main()
