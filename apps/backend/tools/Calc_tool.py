"""
BenefitCalculator v2 – Master_Schema_v2.json 기반 최대 할인 산출기

Agent workflow의 tool 노드에서 호출됩니다.
유저가 사전에 선택한 카테고리별 예산을 입력받아
해당 카드의 '이론상 최대 할인/적립 금액(Upper Bound)'을 반환합니다.

입력:
  - user_budgets : dict[str, int]  (예: {"Coffee": 50000, "Traffic": 60000})
  - user_total_spend : int | None  (미입력 시 user_budgets의 합)

출력: dict (카드명, 카테고리별 월 최대 할인 KRW, 연간 혜택 등)
"""

from __future__ import annotations
from collections import defaultdict

# =============================================================================
# 상수
# =============================================================================
DEFAULT_FUEL_PRICE_PER_LITER = 1_600  # 기준 휘발유 가격 (원/리터)
DAYS_PER_MONTH = 30
INF = float("inf")


# =============================================================================
# 유틸리티
# =============================================================================
def _pick(tier: dict | None, key: str, fallback=None):
    """tier 사전에 값이 있으면 사용, 없으면 fallback."""
    if tier is not None:
        val = tier.get(key)
        if val is not None:
            return val
    return fallback


def _effective_days(day_of_week: list[str] | None) -> float:
    """요일 제한이 있을 때 한 달 중 해당 요일 수 추정."""
    if not day_of_week:
        return DAYS_PER_MONTH
    return len(day_of_week) * 4.33  # 약 4.33주/월


# =============================================================================
# BenefitCalculator
# =============================================================================
class BenefitCalculator:
    """
    Master Schema v2 카드 데이터를 받아
    유저의 카테고리별 예산 대비 이론상 최대 할인/적립 금액을 산출합니다.
    """

    def __init__(self, card_data: dict):
        self.meta = card_data.get("card_meta", {})
        self.groups = {
            g["group_id"]: g for g in card_data.get("benefit_groups", [])
        }
        self.benefits = card_data.get("benefits", [])
        self._perf_excluded_cats: set[str] = set(
            self.meta.get("performance_excluded_categories") or []
        )

    # -----------------------------------------------------------------
    # 1. 전월 실적(Performance) 보정
    # -----------------------------------------------------------------
    def _adjusted_performance(
        self, user_budgets: dict[str, int], user_total_spend: int
    ) -> int:
        """카드 메타 및 혜택별 실적 제외 로직을 반영한 보정 실적."""
        adjusted = user_total_spend

        # card_meta 레벨 제외 (예: Fuel)
        for cat in self._perf_excluded_cats:
            adjusted -= user_budgets.get(cat, 0)

        # benefit 레벨 제외 (excludes_from_performance / category_excludes_from_performance)
        already_excluded = set(self._perf_excluded_cats)
        for b in self.benefits:
            flags = b.get("edge_case_flags") or {}
            cat = b.get("category")
            if cat and cat not in already_excluded:
                if flags.get("excludes_from_performance") or flags.get(
                    "category_excludes_from_performance"
                ):
                    adjusted -= user_budgets.get(cat, 0)
                    already_excluded.add(cat)

        return max(adjusted, 0)

    # -----------------------------------------------------------------
    # 2. Tier 매칭 (전월 실적 구간)
    # -----------------------------------------------------------------
    @staticmethod
    def _find_best_tier(tier_conditions: list[dict], performance: float) -> dict | None:
        """실적 이상인 구간 중 가장 높은 구간을 반환."""
        if not tier_conditions:
            return None
        applicable = [
            t for t in tier_conditions
            if performance >= t.get("min_prev_performance", 0)
        ]
        if not applicable:
            return None
        return max(applicable, key=lambda t: t.get("min_prev_performance", 0))

    # -----------------------------------------------------------------
    # 3. 단일 혜택 Upper Bound 산출
    # -----------------------------------------------------------------
    def _calc_benefit(
        self,
        benefit: dict,
        budget: float,
        performance: float,
        user_total_spend: float,
    ) -> dict:
        """
        개별 benefit에 대해 주어진 budget으로 얻을 수 있는
        이론상 최대 혜택 금액을 산출합니다 (Upper Bound).
        """
        calc_rule = benefit.get("calculation_rule") or {}
        trans_cond = benefit.get("transaction_conditions") or {}
        tier_conditions = benefit.get("tier_conditions") or []
        edge_flags = benefit.get("edge_case_flags") or {}
        reward_unit = benefit.get("reward_unit") or {}
        freq = benefit.get("frequency", "MONTHLY")

        conversion_rate = reward_unit.get("currency_to_krw_rate", 1.0)

        # --- Tier 결정 ---
        perf_for_tier = performance
        if edge_flags.get("current_month_performance", False):
            perf_for_tier = user_total_spend  # 당월 기준 → 총 소비액 대체

        tier = self._find_best_tier(tier_conditions, perf_for_tier)

        # --- 변수 확정 (tier 우선 → calc_rule fallback) ---
        rate = _pick(tier, "rate", calc_rule.get("rate")) or 0.0
        fixed_amount = _pick(tier, "fixed_amount", calc_rule.get("fixed_amount")) or 0
        unit_amount = _pick(tier, "unit_amount", calc_rule.get("unit_amount")) or 0
        monthly_limit = (
            _pick(tier, "monthly_limit", calc_rule.get("monthly_limit")) or INF
        )
        monthly_usage_limit = (
            _pick(tier, "monthly_usage_limit", calc_rule.get("monthly_usage_limit"))
            or INF
        )
        fallback_rate = calc_rule.get("fallback_reward_rate") or 0.0

        # --- Transaction conditions ---
        min_payment = trans_cond.get("min_payment_amount") or 0
        max_payment_applied = trans_cond.get("max_payment_amount_applied") or INF
        max_count_day = trans_cond.get("max_count_per_day") or INF
        max_count_month = trans_cond.get("max_count_per_month") or INF
        day_of_week = trans_cond.get("day_of_week")

        # 요일 제한 반영 → 일별 횟수 × 해당 요일 수
        eff_days = _effective_days(day_of_week)
        max_monthly_txns = min(max_count_month, max_count_day * eff_days)

        # Platform bonus (추가 적립률)
        platform_bonus = edge_flags.get("payment_platform_bonus") or {}
        add_rate = platform_bonus.get("additional_rate") or 0.0

        # --- Effective budget ---
        eff_budget = min(budget, monthly_usage_limit)

        if eff_budget < min_payment and freq not in ("ANNUAL", "ONCE", "QUARTERLY"):
            return self._empty_record(benefit)

        # --- 계산 ---
        calc_method = calc_rule.get("calc_method", "RATE")
        raw_amount = 0.0
        used_budget = 0.0
        warnings: list[str] = list(benefit.get("ui_warnings") or [])

        if calc_method == "RATE":
            total_rate = rate + add_rate
            cap = max_payment_applied * max_monthly_txns
            eff = min(eff_budget, cap)
            raw_amount = eff * total_rate
            used_budget = eff

        elif calc_method == "FIXED_AMOUNT":
            if max_monthly_txns >= INF and max_count_month >= INF:
                # 월 1회 정액 (횟수 제한 없음 = 월 정액)
                raw_amount = fixed_amount
            else:
                possible = (
                    eff_budget // max(min_payment, 1)
                    if min_payment > 0
                    else max_monthly_txns
                )
                count = min(max_monthly_txns, possible)
                raw_amount = fixed_amount * count
            used_budget = eff_budget

        elif calc_method == "PER_UNIT":
            label = calc_rule.get("unit_label", "")
            if label == "liter":
                liters = eff_budget / DEFAULT_FUEL_PRICE_PER_LITER
                raw_amount = liters * unit_amount
                warnings.append(
                    f"주유 할인은 기준유가 {DEFAULT_FUEL_PRICE_PER_LITER:,}원/L 기반 추정치입니다"
                )
            elif label == "transaction":
                possible = (
                    eff_budget // max(min_payment, 1)
                    if min_payment > 0
                    else max_monthly_txns
                )
                count = min(max_monthly_txns, possible)
                raw_amount = unit_amount * count
            else:
                raw_amount = unit_amount
            used_budget = eff_budget

        elif calc_method == "TIERED_RATE_BY_TRANSACTION":
            txn_tiers = calc_rule.get("transaction_tiers") or []
            if txn_tiers:
                best = max(txn_tiers, key=lambda t: t.get("rate", 0))
                raw_amount = eff_budget * (best["rate"] + add_rate)
            used_budget = eff_budget

        elif calc_method == "MAX_COVER_UP_TO_LIMIT":
            raw_amount = min(eff_budget, monthly_limit)
            used_budget = raw_amount

        # --- 한도 적용 + Fallback ---
        final_amount = min(raw_amount, monthly_limit)

        if raw_amount > monthly_limit and fallback_rate > 0 and (rate + add_rate) > 0:
            consumed = monthly_limit / (rate + add_rate)
            remaining = used_budget - consumed
            if remaining > 0:
                final_amount += remaining * fallback_rate

        # --- KRW 환산 ---
        krw = final_amount * conversion_rate

        # --- 시간대/요일/자동납부 경고 ---
        time_of_day = trans_cond.get("time_of_day") or {}
        if time_of_day.get("start"):
            warnings.append(f"시간대 한정: {time_of_day['start']}~{time_of_day['end']}")
        if day_of_week:
            warnings.append(f"요일 한정: {', '.join(day_of_week)}")
        if trans_cond.get("requires_auto_payment"):
            warnings.append("자동납부(정기결제) 필수")

        return {
            "benefit_id": benefit.get("benefit_id"),
            "category": benefit.get("category"),
            "frequency": freq,
            "reward_type": benefit.get("reward_type"),
            "raw_amount": round(final_amount, 2),
            "amount_krw": round(krw),
            "used_budget": round(used_budget),
            "group_id": benefit.get("group_id"),
            "warnings": warnings,
        }

    @staticmethod
    def _empty_record(benefit: dict) -> dict:
        return {
            "benefit_id": benefit.get("benefit_id"),
            "category": benefit.get("category"),
            "frequency": benefit.get("frequency", "MONTHLY"),
            "reward_type": benefit.get("reward_type"),
            "raw_amount": 0,
            "amount_krw": 0,
            "used_budget": 0,
            "group_id": benefit.get("group_id"),
            "warnings": [],
        }

    # -----------------------------------------------------------------
    # 4. 연간 특수 혜택 산출 (annual_usage_tiers, annual_voucher)
    # -----------------------------------------------------------------
    def _calc_annual_specials(self, user_total_spend: float) -> list[dict]:
        """edge_case_flags 내 연간 캐시백 / 바우처 혜택 산출."""
        items: list[dict] = []
        annual_projection = user_total_spend * 12

        for b in self.benefits:
            flags = b.get("edge_case_flags") or {}

            # 연간 누적 캐시백 (예: X카드 500만당 2만원)
            for at in flags.get("annual_usage_tiers") or []:
                min_spend = at.get("min_annual_spend", 0)
                max_spend = at.get("max_annual_spend") or INF
                cashback = at.get("cashback_amount", 0)
                if annual_projection >= min_spend and min_spend > 0:
                    eligible = min(annual_projection, max_spend)
                    times = int(eligible // min_spend)
                    items.append({
                        "benefit_id": b.get("benefit_id"),
                        "category": b.get("category"),
                        "type": "annual_cashback",
                        "amount_krw": cashback * times,
                        "description": at.get("description", ""),
                    })

            # 연간 바우처 (예: Summit 15만원 바우처)
            voucher = flags.get("annual_voucher") or {}
            val = voucher.get("voucher_value_krw")
            if val:
                items.append({
                    "benefit_id": b.get("benefit_id"),
                    "category": b.get("category"),
                    "type": "voucher",
                    "amount_krw": val,
                    "description": voucher.get("initial_year_condition", ""),
                    "choices": voucher.get("choices"),
                })

        return items

    # -----------------------------------------------------------------
    # 5. 그룹 한도 적용
    # -----------------------------------------------------------------
    def _apply_group_limits(self, results: list[dict]) -> None:
        """SHARED_LIMIT / USER_CHOICE_ONE / AUTO_TOP_N 그룹 한도 적용 (in-place)."""
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in results:
            gid = r.get("group_id")
            if gid:
                buckets[gid].append(r)

        for gid, items in buckets.items():
            group_info = self.groups.get(gid)
            if not group_info:
                continue

            g_type = group_info.get("group_type", "SHARED_LIMIT")
            g_limit = group_info.get("limit_amount") or INF

            if g_type == "SHARED_LIMIT":
                total = sum(r["amount_krw"] for r in items)
                if total > g_limit:
                    ratio = g_limit / total
                    for r in items:
                        r["amount_krw"] = round(r["amount_krw"] * ratio)

            elif g_type == "USER_CHOICE_ONE":
                best = max(items, key=lambda r: r["amount_krw"])
                for r in items:
                    if r["benefit_id"] != best["benefit_id"]:
                        r["amount_krw"] = 0
                        r["warnings"].append("그룹 내 택1 조건으로 인해 제외됨")

            elif g_type == "AUTO_TOP_N":
                n = group_info.get("top_n_count") or 1
                ranked = sorted(items, key=lambda r: r["amount_krw"], reverse=True)
                selected_ids = {r["benefit_id"] for r in ranked[:n]}
                for r in items:
                    if r["benefit_id"] not in selected_ids:
                        r["amount_krw"] = 0
                        r["warnings"].append(f"AUTO_TOP_{n} 미선택으로 제외됨")
                # 선택된 항목에도 그룹 한도 적용
                selected_total = sum(r["amount_krw"] for r in items)
                if selected_total > g_limit:
                    ratio = g_limit / selected_total
                    for r in items:
                        if r["amount_krw"] > 0:
                            r["amount_krw"] = round(r["amount_krw"] * ratio)

    # -----------------------------------------------------------------
    # 6. 메인 산출 로직
    # -----------------------------------------------------------------
    def calculate(
        self,
        user_budgets: dict[str, int],
        user_total_spend: int | None = None,
    ) -> dict:
        """
        유저의 카테고리별 예산을 받아 해당 카드의 이론상 최대 할인 금액을 산출합니다.

        Args:
            user_budgets: 카테고리 → 월 예산(원) 매핑.
                          예: {"Coffee": 50000, "Traffic": 60000}
            user_total_spend: 전체 월 소비액 (미입력 시 user_budgets 합산)

        Returns:
            dict: 카드별 카테고리 할인 내역, 월간/연간 합계 등
        """
        if user_total_spend is None:
            user_total_spend = sum(user_budgets.values())

        # ── 전월 실적 보정 ──
        performance = self._adjusted_performance(user_budgets, user_total_spend)
        min_perf = self.meta.get("minimum_performance", 0)
        performance_met = performance >= min_perf

        # 전월실적 채워드림 (performance_gap_forgiveness)
        gap_applied = False
        if not performance_met:
            for b in self.benefits:
                fg = (b.get("edge_case_flags") or {}).get(
                    "performance_gap_forgiveness"
                ) or {}
                if fg.get("enabled") and (min_perf - performance) <= (
                    fg.get("max_gap_amount") or 0
                ):
                    performance_met = True
                    gap_applied = True
                    break

        result: dict = {
            "card_name": self.meta.get("card_name"),
            "card_id": self.meta.get("card_id"),
            "performance_met": performance_met,
            "adjusted_performance": performance,
            "monthly_total_krw": 0,
            "annual_total_krw": 0,
            "category_breakdown": [],
            "annual_breakdown": [],
            "warnings": [],
        }

        if gap_applied:
            result["warnings"].append("전월실적 채워드림 적용 (연 횟수 제한 있음)")
        if not performance_met:
            result["warnings"].append(
                f"보정된 전월 실적({performance:,.0f}원)이 "
                f"최소 조건({min_perf:,.0f}원)에 미달합니다."
            )
            return result

        # ── 혜택별 계산 (All_Domestic을 마지막에 → Waterfall) ──
        sorted_benefits = sorted(
            self.benefits,
            key=lambda x: (
                1 if x.get("category") == "All_Domestic" else 0,
                x.get("benefit_id", ""),
            ),
        )

        remaining_total = user_total_spend
        monthly_results: list[dict] = []
        quarterly_results: list[dict] = []
        annual_freq_results: list[dict] = []

        for b in sorted_benefits:
            cat = b.get("category")
            freq = b.get("frequency", "MONTHLY")

            # 예산 결정
            if cat == "All_Domestic":
                budget = remaining_total
            else:
                budget = user_budgets.get(cat, 0)

            if budget <= 0 and freq not in ("ANNUAL", "ONCE"):
                continue

            calc_result = self._calc_benefit(b, budget, performance, user_total_spend)

            if calc_result["amount_krw"] <= 0:
                continue

            # Waterfall: 사용된 예산만큼 잔여 총액에서 차감
            if cat != "All_Domestic" and calc_result["used_budget"] > 0:
                remaining_total -= calc_result["used_budget"]
                remaining_total = max(remaining_total, 0)

            if freq == "MONTHLY":
                monthly_results.append(calc_result)
            elif freq == "QUARTERLY":
                quarterly_results.append(calc_result)
            elif freq in ("ANNUAL", "ONCE"):
                annual_freq_results.append(calc_result)

        # ── 그룹 한도 처리 ──
        self._apply_group_limits(monthly_results)

        # ── 카테고리별 합산 ──
        cat_totals: dict[str, dict] = defaultdict(
            lambda: {"monthly_discount_krw": 0, "warnings": []}
        )
        for r in monthly_results:
            cat = r["category"]
            cat_totals[cat]["monthly_discount_krw"] += r["amount_krw"]
            cat_totals[cat]["warnings"].extend(r["warnings"])

        for cat, data in cat_totals.items():
            result["category_breakdown"].append({
                "category": cat,
                "monthly_discount_krw": round(data["monthly_discount_krw"]),
                "warnings": list(set(data["warnings"])),
            })

        # 유저가 선택한 카테고리 순서대로 정렬 (All_Domestic 마지막)
        result["category_breakdown"].sort(
            key=lambda x: (x["category"] == "All_Domestic", x["category"])
        )

        result["monthly_total_krw"] = round(
            sum(r["amount_krw"] for r in monthly_results)
        )

        # ── 연간 혜택 합산 ──
        quarterly_annual = sum(r["amount_krw"] * 4 for r in quarterly_results)
        annual_freq_total = sum(r["amount_krw"] for r in annual_freq_results)
        annual_specials = self._calc_annual_specials(user_total_spend)
        annual_special_total = sum(a["amount_krw"] for a in annual_specials)

        result["annual_total_krw"] = round(
            annual_freq_total + quarterly_annual + annual_special_total
        )
        result["annual_breakdown"] = (
            [
                {
                    "category": r["category"],
                    "amount_krw": r["amount_krw"],
                    "frequency": r["frequency"],
                }
                for r in annual_freq_results + quarterly_results
            ]
            + annual_specials
        )

        return result


# =============================================================================
# 테스트 실행부 (Master Schema v2 Mock Data)
# =============================================================================
if __name__ == "__main__":
    import json

    # ── 테스트 케이스 1: 정률 + 정액 + 그룹 한도 ──
    mock_card_1 = {
        "card_meta": {
            "card_id": "test_discount_card",
            "card_name": "테스트 할인카드 Pro",
            "card_company": "TEST",
            "annual_fee_domestic": 15000,
            "annual_fee_international": 20000,
            "minimum_performance": 300000,
            "performance_excluded_categories": None,
        },
        "benefit_groups": [
            {
                "group_id": "G_TIME_PLAN",
                "group_name": "Time Plan 통합",
                "group_type": "SHARED_LIMIT",
                "limit_amount": 10000,
                "top_n_count": None,
            }
        ],
        "benefits": [
            {
                "benefit_id": "b_coffee",
                "category": "Coffee",
                "content": "커피 전문점 10% 할인, 월 한도 15000원, 한도 초과 시 1% 적립",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "tier_conditions": [],
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.10,
                    "fixed_amount": None,
                    "unit_label": None,
                    "unit_amount": None,
                    "monthly_limit": 15000,
                    "monthly_usage_limit": None,
                    "fallback_reward_rate": 0.01,
                    "transaction_tiers": None,
                },
                "transaction_conditions": {
                    "min_payment_amount": 0,
                    "max_payment_amount_applied": 10000,
                    "max_count_per_day": 1,
                    "max_count_per_month": 4,
                    "max_count_per_year": None,
                    "day_of_week": None,
                    "time_of_day": {"start": None, "end": None},
                    "requires_auto_payment": False,
                    "requires_offline": True,
                    "requires_online": False,
                },
                "group_id": "G_TIME_PLAN",
                "ui_warnings": ["오프라인 매장 한정"],
                "edge_case_flags": {
                    "requires_user_selection": False,
                    "excludes_from_performance": False,
                    "category_excludes_from_performance": False,
                    "special_month_bonus": {
                        "type": None, "multiplier": None,
                        "bonus_limit_add": None, "months": None,
                    },
                    "performance_gap_forgiveness": {
                        "enabled": False, "max_gap_amount": None, "max_count_per_year": None,
                    },
                    "current_month_performance": False,
                    "payment_platform_bonus": {"platform": None, "additional_rate": None},
                    "annual_usage_tiers": [],
                    "annual_voucher": {
                        "voucher_value_krw": None, "initial_year_condition": None,
                        "renewal_year_condition": None, "choices": None,
                    },
                    "escape_hatch_note": None,
                },
            },
            {
                "benefit_id": "b_all_domestic",
                "category": "All_Domestic",
                "content": "전 가맹점 1% 적립",
                "frequency": "MONTHLY",
                "reward_type": "POINT",
                "reward_unit": {"currency": "M_POINT", "currency_to_krw_rate": 0.666},
                "tier_conditions": [],
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.01,
                    "fixed_amount": None,
                    "unit_label": None,
                    "unit_amount": None,
                    "monthly_limit": None,
                    "monthly_usage_limit": None,
                    "fallback_reward_rate": 0.0,
                    "transaction_tiers": None,
                },
                "transaction_conditions": {
                    "min_payment_amount": 0,
                    "max_payment_amount_applied": None,
                    "max_count_per_day": None,
                    "max_count_per_month": None,
                    "max_count_per_year": None,
                    "day_of_week": None,
                    "time_of_day": {"start": None, "end": None},
                    "requires_auto_payment": False,
                    "requires_offline": False,
                    "requires_online": False,
                },
                "group_id": None,
                "ui_warnings": [],
                "edge_case_flags": {
                    "requires_user_selection": False,
                    "excludes_from_performance": False,
                    "category_excludes_from_performance": False,
                    "special_month_bonus": {
                        "type": None, "multiplier": None,
                        "bonus_limit_add": None, "months": None,
                    },
                    "performance_gap_forgiveness": {
                        "enabled": False, "max_gap_amount": None, "max_count_per_year": None,
                    },
                    "current_month_performance": False,
                    "payment_platform_bonus": {"platform": None, "additional_rate": None},
                    "annual_usage_tiers": [],
                    "annual_voucher": {
                        "voucher_value_krw": None, "initial_year_condition": None,
                        "renewal_year_condition": None, "choices": None,
                    },
                    "escape_hatch_note": None,
                },
            },
        ],
    }

    # ── 테스트 케이스 2: PER_UNIT (주유) + 실적 구간별 한도 ──
    mock_card_2 = {
        "card_meta": {
            "card_id": "test_fuel_card",
            "card_name": "테스트 주유카드",
            "card_company": "TEST",
            "annual_fee_domestic": 10000,
            "annual_fee_international": None,
            "minimum_performance": 300000,
            "performance_excluded_categories": ["Fuel"],
        },
        "benefit_groups": [],
        "benefits": [
            {
                "benefit_id": "b_fuel",
                "category": "Fuel",
                "content": "전 주유소 리터당 60원 할인",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "tier_conditions": [
                    {
                        "min_prev_performance": 300000,
                        "rate": None,
                        "fixed_amount": None,
                        "unit_amount": 60,
                        "monthly_limit": None,
                        "monthly_usage_limit": 200000,
                        "description": "30만 이상: 이용금액 20만원 한도",
                    },
                    {
                        "min_prev_performance": 600000,
                        "rate": None,
                        "fixed_amount": None,
                        "unit_amount": 60,
                        "monthly_limit": None,
                        "monthly_usage_limit": 400000,
                        "description": "60만 이상: 이용금액 40만원 한도",
                    },
                ],
                "calculation_rule": {
                    "calc_method": "PER_UNIT",
                    "rate": None,
                    "fixed_amount": None,
                    "unit_label": "liter",
                    "unit_amount": 60,
                    "monthly_limit": None,
                    "monthly_usage_limit": None,
                    "fallback_reward_rate": 0.0,
                    "transaction_tiers": None,
                },
                "transaction_conditions": {
                    "min_payment_amount": 0,
                    "max_payment_amount_applied": 100000,
                    "max_count_per_day": 1,
                    "max_count_per_month": None,
                    "max_count_per_year": None,
                    "day_of_week": None,
                    "time_of_day": {"start": None, "end": None},
                    "requires_auto_payment": False,
                    "requires_offline": True,
                    "requires_online": False,
                },
                "group_id": None,
                "ui_warnings": [],
                "edge_case_flags": {
                    "requires_user_selection": False,
                    "excludes_from_performance": False,
                    "category_excludes_from_performance": True,
                    "special_month_bonus": {
                        "type": None, "multiplier": None,
                        "bonus_limit_add": None, "months": None,
                    },
                    "performance_gap_forgiveness": {
                        "enabled": False, "max_gap_amount": None, "max_count_per_year": None,
                    },
                    "current_month_performance": False,
                    "payment_platform_bonus": {"platform": None, "additional_rate": None},
                    "annual_usage_tiers": [],
                    "annual_voucher": {
                        "voucher_value_krw": None, "initial_year_condition": None,
                        "renewal_year_condition": None, "choices": None,
                    },
                    "escape_hatch_note": None,
                },
            },
        ],
    }

    print("=" * 60)
    print("테스트 1: 정률 + Fallback + 그룹 한도")
    print("=" * 60)
    calc1 = BenefitCalculator(mock_card_1)
    r1 = calc1.calculate({"Coffee": 100_000}, user_total_spend=1_000_000)
    print(json.dumps(r1, indent=2, ensure_ascii=False))

    print()
    print("=" * 60)
    print("테스트 2: 주유 PER_UNIT (리터당 60원) + 실적 제외")
    print("=" * 60)
    calc2 = BenefitCalculator(mock_card_2)
    r2 = calc2.calculate({"Fuel": 200_000}, user_total_spend=800_000)
    print(json.dumps(r2, indent=2, ensure_ascii=False))