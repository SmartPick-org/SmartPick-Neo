#!/usr/bin/env python3
"""
PDF Parsing Optimization Pipeline — Calculation Comparison Script

Loads every JSON file produced by generate_json_versions.py, runs
BenefitCalculator with a fixed test spending pattern, then compares
results across versions to surface discrepancies.

Flags:
  • Outlier versions  — monthly benefit deviates >1.5 SD from the group mean
  • Large spread      — max − min spread > 30% of mean

Output: results/calc_comparison_{timestamp}.{json,md}

Usage:
    python compare_calculations.py                  # all cards, all versions
    python compare_calculations.py --card "Mr.Life"
    python compare_calculations.py --versions 1 5 6
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parents[1]

sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from app.tools.Calc_tool import BenefitCalculator

JSON_DIR = BASE_DIR / "json"
RESULTS_DIR = BASE_DIR / "results"

VERSION_LABELS: dict[int, str] = {
    1: "Upstage → Markdown",
    2: "Datalab → Markdown",
    3: "Upstage → HTML → Markdown",
    4: "Datalab → HTML → Markdown",
    5: "Upstage → HTML + LLM tables → Markdown",
    6: "Hand-crafted",
}

# ─────────────────────────────────────────────────────────────
# Test consumption pattern
# Total: 500,000원/month — clears most standard performance thresholds.
#
# Subcategory names must match scripts/sub_categories.py exactly.
# ─────────────────────────────────────────────────────────────

TEST_SPENDING: dict = {
    "Shopping": {
        "total": 200_000,
        "mart":         "40%",   # 80,000원 — 이마트·롯데마트·홈플러스 등 대형마트
        "online":       "40%",   # 80,000원 — 쿠팡·네이버쇼핑·11번가 등 온라인쇼핑
        "convenience":  "20%",   # 40,000원 — CU·GS25·세븐일레븐 등 편의점
    },
    "Traffic": {
        "total": 150_000,
        "fuel":    "40%",        # 60,000원 — SK에너지·GS칼텍스 등 주유소
        "transit": "40%",        # 60,000원 — 지하철·버스 등 대중교통
        "taxi":    "20%",        # 30,000원 — 일반·카카오택시 등
    },
    "Food": {
        "total": 100_000,
        "restaurant": "50%",     # 50,000원 — 한식·양식·중식 등 일반 음식점
        "delivery":   "30%",     # 30,000원 — 배달의민족·쿠팡이츠 등 배달앱
        "fast_food":  "20%",     # 20,000원 — 맥도날드·버거킹·KFC 등
    },
    "Coffee": {
        "total": 50_000,
        "cafe":   "80%",         # 40,000원 — 스타벅스·투썸·메가커피 등 카페
        "bakery": "20%",         # 10,000원 — 파리바게뜨·뚜레쥬르 등 베이커리
    },
}

TOTAL_MONTHLY_SPEND = sum(v["total"] for v in TEST_SPENDING.values())  # 500,000원


# ─────────────────────────────────────────────────────────────
# JSON discovery & grouping
# ─────────────────────────────────────────────────────────────

def _normalise_card_name(name: str) -> str:
    """
    Strip company prefixes so the same card groups together even when
    different versions include or omit the issuer name.
    e.g. "신한카드 Discount Plan+" and "Discount Plan+" → "Discount Plan+"
    """
    prefixes = ["신한카드 ", "KB국민카드 ", "현대카드 ", "삼성카드 ",
                "롯데카드 ", "우리카드 ", "하나카드 ", "NH농협카드 "]
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _load_all_jsons(
    version_filter: list[int] | None,
) -> dict[str, dict[int, dict]]:
    """
    Returns: {card_name → {version_num → card_json}}
    Groups by card_meta.card_name so the same physical card across versions
    is compared, even if file slugs differ.
    """
    grouped: dict[str, dict[int, dict]] = {}

    for ver_dir in sorted(JSON_DIR.glob("version*")):
        try:
            ver_num = int(ver_dir.name.replace("version", ""))
        except ValueError:
            continue
        if version_filter and ver_num not in version_filter:
            continue

        for jf in sorted(ver_dir.glob("*.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            card_name = _normalise_card_name(
                data.get("card_meta", {}).get("card_name") or jf.stem
            )
            grouped.setdefault(card_name, {})[ver_num] = data

    return grouped


# ─────────────────────────────────────────────────────────────
# Calculation
# ─────────────────────────────────────────────────────────────

def _calculate(card_json: dict) -> dict:
    """Run BenefitCalculator; returns result dict (may contain 'error' key)."""
    try:
        return BenefitCalculator(card_json).calculate(
            TEST_SPENDING, user_total_spend=TOTAL_MONTHLY_SPEND
        )
    except Exception as exc:
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────

def _stats(scores: dict[int, int | None]) -> dict:
    valid = {v: s for v, s in scores.items() if s is not None}
    if len(valid) < 2:
        return {
            "mean": valid[next(iter(valid))] if valid else None,
            "std": 0, "spread_pct": 0,
            "min_ver": None, "max_ver": None,
            "min_val": None, "max_val": None,
            "outliers": [],
        }

    vals = list(valid.values())
    mean = statistics.mean(vals)
    std  = statistics.pstdev(vals)       # population std — stable for small N

    outliers = []
    if std > 0:
        for ver, val in valid.items():
            z = abs(val - mean) / std
            if z > 1.5:
                outliers.append({"version": ver, "value": val, "z_score": round(z, 2)})

    min_ver = min(valid, key=valid.__getitem__)
    max_ver = max(valid, key=valid.__getitem__)
    spread  = (valid[max_ver] - valid[min_ver]) / mean * 100 if mean else 0

    return {
        "mean": round(mean),
        "std":  round(std),
        "spread_pct": round(spread, 1),
        "min_ver": min_ver, "min_val": valid[min_ver],
        "max_ver": max_ver, "max_val": valid[max_ver],
        "outliers": outliers,
    }


# ─────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────

def _md_report(all_data: dict, timestamp: str) -> str:
    lines: list[str] = []
    lines.append("# Calculation Comparison Report\n\n")
    lines.append(f"**Generated:** {timestamp}\n\n")
    lines.append(f"**Test monthly spend:** {TOTAL_MONTHLY_SPEND:,}원\n\n")
    lines.append("**Spending breakdown:**\n\n")
    lines.append("| Category | Subcategory | Amount |\n")
    lines.append("|----------|-------------|-------:|\n")
    for cat, val in TEST_SPENDING.items():
        total = val["total"]
        subcats = {k: v for k, v in val.items() if k != "total"}
        first = True
        for sub, pct in subcats.items():
            amt = int(total * int(pct.rstrip("%")) / 100)
            cat_col = cat if first else ""
            lines.append(f"| {cat_col} | {sub} ({pct}) | {amt:,}원 |\n")
            first = False
        lines.append(f"| **{cat} total** | | **{total:,}원** |\n")
    lines.append("\n---\n\n")

    for card_name, card_data in sorted(all_data.items()):
        lines.append(f"## {card_name}\n\n")

        calc_results: dict[int, dict] = card_data["calc_results"]
        monthly:      dict[int, int | None] = card_data["monthly"]
        st = card_data["stats"]

        # Summary table
        # monthly_total_krw  = recurring monthly discounts/cashback
        # annual_total_krw   = extra annual-only perks (vouchers, ONCE benefits)
        # total annual value = monthly × 12 + annual_total_krw
        vers = sorted(calc_results.keys())
        lines.append("| Ver | Description | Monthly benefit | Annual extras | Total annual value | Perf met | |\n")
        lines.append("|-----|-------------|:---------------:|:-------------:|:------------------:|:--------:|---|\n")
        for v in vers:
            label  = VERSION_LABELS.get(v, f"v{v}")
            r      = calc_results[v]
            mon    = monthly.get(v)
            is_err = "error" in r

            if is_err or mon is None:
                mon_s, ann_s, total_s = "—", "—", "—"
            else:
                ann = r.get("annual_total_krw", 0)
                total_annual = mon * 12 + ann
                mon_s   = f"{mon:,}원"
                ann_s   = f"{ann:,}원" if ann else "—"
                total_s = f"{total_annual:,}원"

            perf_s = ("✅" if r.get("performance_met") else "❌") if not is_err else "—"
            flag   = "⚠ outlier" if any(o["version"] == v for o in st["outliers"]) else ""

            lines.append(f"| v{v} | {label} | {mon_s} | {ann_s} | {total_s} | {perf_s} | {flag} |\n")

        lines.append("\n")

        # Stats row
        if st["mean"] is not None and st["min_val"] is not None:
            lines.append(
                f"**Stats (monthly):** "
                f"mean={st['mean']:,}원 · std={st['std']:,}원 · "
                f"spread={st['spread_pct']}% "
                f"(v{st['min_ver']}={st['min_val']:,} → v{st['max_ver']}={st['max_val']:,}원)\n\n"
            )
            if st["outliers"]:
                lines.append("**⚠ Outliers:**\n")
                for o in st["outliers"]:
                    lines.append(
                        f"- v{o['version']}: {o['value']:,}원  "
                        f"(z={o['z_score']})\n"
                    )
                lines.append("\n")
            if st["spread_pct"] > 30:
                lines.append(
                    f"**⚠ Large spread ({st['spread_pct']}%)** — versions produce "
                    "very different reward totals, likely due to parsing errors.\n\n"
                )

        # Category totals across versions
        valid_results = {v: r for v, r in calc_results.items() if "error" not in r}
        if valid_results:
            all_cats = sorted({
                bd["category"]
                for r in valid_results.values()
                for bd in r.get("category_breakdown", [])
                if bd.get("monthly_discount_krw", 0) > 0
            })
            if all_cats:
                ver_list = sorted(valid_results.keys())
                lines.append("**Category totals — monthly (원):**\n\n")
                lines.append("| Category | " + " | ".join(f"v{v}" for v in ver_list) + " |\n")
                lines.append("|----------|" + "|".join([":------:"] * len(ver_list)) + "|\n")
                for cat in all_cats:
                    row = [cat]
                    for v in ver_list:
                        bd_list = valid_results[v].get("category_breakdown", [])
                        total = sum(
                            bd["monthly_discount_krw"]
                            for bd in bd_list
                            if bd["category"] == cat
                        )
                        row.append(f"{total:,}" if total else "—")
                    lines.append("| " + " | ".join(row) + " |\n")
                lines.append("\n")

        # Per-version individual benefit breakdown
        if valid_results:
            lines.append("**Individual benefit breakdown per version:**\n\n")
            for v in sorted(valid_results.keys()):
                r = valid_results[v]
                label = VERSION_LABELS.get(v, f"v{v}")
                lines.append(f"<details><summary>v{v} — {label}</summary>\n\n")
                lines.append("| Category | Sub-category | Benefit | Amount/mo |\n")
                lines.append("|----------|-------------|---------|----------:|\n")

                details = sorted(
                    (d for d in r.get("benefit_details", []) if d.get("amount_krw", 0) > 0),
                    key=lambda d: (d.get("category", ""), -d.get("amount_krw", 0)),
                )
                if details:
                    for d in details:
                        cat  = d.get("category", "—")
                        sub  = d.get("sub_category") or "—"
                        cont = (d.get("content") or d.get("benefit_id") or "—")[:60]
                        amt  = d.get("amount_krw", 0)
                        lines.append(f"| {cat} | {sub} | {cont} | {amt:,}원 |\n")
                else:
                    lines.append("| — | — | no benefit details available | — |\n")

                lines.append("\n</details>\n\n")

        # Errors
        errs = {v: r["error"] for v, r in calc_results.items() if "error" in r}
        if errs:
            lines.append("**Calculation errors:**\n")
            for v, msg in errs.items():
                lines.append(f"- v{v}: `{msg}`\n")
            lines.append("\n")

        lines.append("---\n\n")

    return "".join(lines)


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def run(
    card_filter: str | None = None,
    version_filter: list[int] | None = None,
) -> None:
    grouped = _load_all_jsons(version_filter)
    if not grouped:
        print("No JSON files found in json/. Run generate_json_versions.py first.")
        sys.exit(1)

    if card_filter:
        grouped = {
            k: v for k, v in grouped.items()
            if card_filter.lower() in k.lower()
        }
        if not grouped:
            print(f"No cards match filter '{card_filter}'.")
            sys.exit(1)

    all_data: dict = {}

    for card_name, ver_jsons in sorted(grouped.items()):
        print(f"\n{'='*60}")
        print(f"Card: {card_name}  ({len(ver_jsons)} version(s))")
        print("=" * 60)

        calc_results: dict[int, dict] = {}
        monthly:      dict[int, int | None] = {}

        for ver, card_json in sorted(ver_jsons.items()):
            label = VERSION_LABELS.get(ver, f"v{ver}")
            print(f"  v{ver} ({label}) ... ", end="", flush=True)

            result = _calculate(card_json)
            calc_results[ver] = result

            if "error" in result:
                monthly[ver] = None
                print(f"CALC ERROR: {result['error']}")
            else:
                mon = result.get("monthly_total_krw", 0)
                ann = result.get("annual_total_krw", 0)
                total_annual = mon * 12 + ann
                perf = "✓" if result.get("performance_met") else "✗ perf"
                monthly[ver] = mon
                print(f"{mon:>10,}원/mo  +{ann:>8,}원 extras  ={total_annual:>10,}원/yr  [{perf}]")

                # Individual benefits grouped by category
                details = sorted(
                    (d for d in result.get("benefit_details", []) if d.get("amount_krw", 0) > 0),
                    key=lambda d: (d.get("category", ""), -d.get("amount_krw", 0)),
                )
                if details:
                    cur_cat = None
                    for d in details:
                        cat = d.get("category", "?")
                        if cat != cur_cat:
                            print(f"    [{cat}]")
                            cur_cat = cat
                        sub  = d.get("sub_category") or ""
                        sub_s = f"({sub}) " if sub else ""
                        cont = (d.get("content") or d.get("benefit_id") or "")[:55]
                        amt  = d.get("amount_krw", 0)
                        print(f"      {sub_s}{cont}  →  {amt:,}원")

        st = _stats(monthly)
        all_data[card_name] = {
            "calc_results": calc_results,
            "monthly": monthly,
            "stats": st,
        }

        if st["outliers"]:
            print(
                f"\n  ⚠ OUTLIER: "
                + ", ".join(f"v{o['version']} ({o['value']:,}원, z={o['z_score']})" for o in st["outliers"])
            )
        if st["spread_pct"] and st["spread_pct"] > 30:
            print(f"  ⚠ Large spread: {st['spread_pct']}%")

    # Persist results
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = RESULTS_DIR / f"calc_comparison_{ts}.json"
    json_path.write_text(
        json.dumps(all_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    report = _md_report(all_data, datetime.now().isoformat(timespec="seconds"))
    md_path = RESULTS_DIR / f"calc_comparison_{ts}.md"
    md_path.write_text(report, encoding="utf-8")

    print(f"\nSaved → {json_path.name}  |  {md_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare BenefitCalculator results across JSON versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--card", metavar="FILTER", help="Filter by card name substring")
    parser.add_argument(
        "--versions",
        nargs="+",
        type=int,
        choices=range(1, 7),
        metavar="N",
        help="Version numbers to compare (default: all available)",
    )
    args = parser.parse_args()
    run(card_filter=args.card, version_filter=args.versions)


if __name__ == "__main__":
    main()
