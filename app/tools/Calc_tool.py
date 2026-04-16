"""
BenefitCalculator v4 – JSON_v4 스키마 기반 최대 혜택 산출기

유저의 카테고리별 예산을 입력받아 신규 Calculator_Schema.json에 정의된
공간별/그룹별 통합 한도와 티어(Tier) 조건을 반영하여 이론상 최대 혜택을 계산합니다.
"""

from __future__ import annotations
from collections import defaultdict
from loguru import logger

# =============================================================================
# 상수 및 유틸리티
# =============================================================================
DEFAULT_FUEL_PRICE_PER_LITER = 1_600
DAYS_PER_MONTH = 30
INF = float("inf")

def _pick(tier: dict | None, keys: str | list[str], fallback=None):
    """Tier 조건에 해당 필드가 있으면 반환, 없으면 기본값(fallback) 반환."""
    if tier is not None:
        if isinstance(keys, str):
            keys = [keys]
        for key in keys:
            val = tier.get(key)
            if val is not None:
                return val
    return fallback

def _effective_days(day_of_week: list[str] | None) -> float:
    """요일 제한이 있을 시 월간 유효 일수 계산."""
    if not day_of_week:
        return DAYS_PER_MONTH
    return len(day_of_week) * 4.33

# =============================================================================
# BenefitCalculator (v4)
# =============================================================================
class BenefitCalculator:
    def __init__(self, card_data: dict):
        self.meta = card_data.get("card_meta", {})
        self.groups = {g["group_id"]: g for g in card_data.get("benefit_groups", [])}
        self.benefits = card_data.get("benefits", [])

    @staticmethod
    def _find_best_tier(tier_conditions: list[dict], performance: float) -> dict | None:
        """전월 실적에 부합하는 가장 높은 티어 조건을 선별."""
        if not tier_conditions:
            return None
        applicable = [t for t in tier_conditions if performance >= t.get("min_prev_performance", 0)]
        if not applicable:
            return None
        return max(applicable, key=lambda t: t.get("min_prev_performance", 0))

    def _calc_single_benefit(self, benefit: dict, budget: float, performance: float) -> dict:
        """
        [1. 혜택 유형별 공식] 적용.
        개별 혜택에 대해 주어진 예산으로 산출 가능한 이론상 최대 금액을 반환.
        """
        rule = benefit.get("calculation_rule", {})
        cond = benefit.get("transaction_conditions", {})
        tiers = benefit.get("tier_conditions", [])
        reward_unit = benefit.get("reward_unit", {})
        
        # 1. 티어 결정 및 변수 확정 (Override)
        tier = self._find_best_tier(tiers, performance)
        
        rate = _pick(tier, "benefit_rate", rule.get("benefit_rate")) or 0.0
        flat = _pick(tier, "flat_discount", rule.get("flat_discount")) or 0
        unit_amount = _pick(tier, "discount_per_unit", rule.get("discount_per_unit")) or 0
        limit = _pick(tier, "monthly_benefit_limit", rule.get("monthly_benefit_limit")) or INF
        fallback_rate = rule.get("fallback_rate") or 0.0
        conv_rate = reward_unit.get("currency_to_krw_rate", 1.0)

        # Transaction 제약
        min_pay = cond.get("min_payment_amount") or 0
        max_spend_tx = cond.get("max_tx_spend_allowed") or INF
        max_cnt_month = cond.get("max_count_per_month") or INF
        max_cnt_year = cond.get("max_count_per_year") or INF
        day_of_week = cond.get("day_of_week")

        # 연간 한도/횟수 월간 안분
        if max_cnt_year < INF:
            max_cnt_month = min(max_cnt_month, max_cnt_year / 12.0)
        
        eff_days = _effective_days(day_of_week)
        max_monthly_txns = min(max_cnt_month, (cond.get("max_count_per_day") or INF) * (eff_days / DAYS_PER_MONTH * 30))

        # 2. 공식 적용
        reward_type = benefit.get("reward_type", "DIRECT_FINANCIAL")
        calc_type = rule.get("calc_type", "PERCENTAGE")
        raw_benefit = 0.0
        used_budget = 0.0
        
        if reward_type == "INDIRECT":
            # [바우처/간접 혜택] 액면가 기반 계산
            ind_meta = benefit.get("indirect_benefit_metadata", {})
            v_val = ind_meta.get("voucher_value") or 0
            
            # 바우처는 보통 실적 충족 시 1회성으로 제공되므로, 
            # 횟수 제한(월간 안분됨)을 곱하여 월평균 가치 도출
            raw_benefit = v_val * min(max_monthly_txns, 1.0)
            used_budget = 0 # 바우처는 보통 카테고리 예산을 소진하지 않음
            
        else:
            # [직접 할인/적립]
            if calc_type == "PERCENTAGE":
                # 1-1 공식: min(spend, max_spend_per_tx * count) * rate
                cap_spend = max_spend_tx * max_monthly_txns
                eff_spend = min(budget, cap_spend)
                raw_benefit = eff_spend * rate
                used_budget = eff_spend
                
                # 1-4 Fallback 공식 연동
                if budget > cap_spend and fallback_rate > 0:
                    raw_benefit += (budget - cap_spend) * fallback_rate

            elif calc_type == "FLAT_RATE":
                # 1-2 공식: min(spend/min_pay, count) * flat
                if budget < min_pay:
                    raw_benefit = 0
                else:
                    optimal_uses = budget // max(min_pay, 1)
                    count = min(optimal_uses, max_monthly_txns)
                    raw_benefit = count * flat
                    used_budget = count * min_pay

            elif calc_type == "UNIT_BASED":
                # 1-3 공식: (spend / unit_price) * unit_discount
                label = rule.get("unit_label", "")
                if label == "liter":
                    liters = budget / DEFAULT_FUEL_PRICE_PER_LITER
                    raw_benefit = liters * unit_amount
                    used_budget = budget
                else:
                    raw_benefit = unit_amount # 기본값
                    used_budget = budget

            elif calc_type == "FULL_COVER":
                raw_benefit = budget
                used_budget = budget

        # 3. 개별 한도 캡 적용
        final_benefit = min(raw_benefit * conv_rate, limit)
        
        # 1-4 Fallback 보정 (비율 할인이나 실효 사용금액 기반인 경우 한도 초과분 처리)
        if raw_benefit * conv_rate > limit and fallback_rate > 0 and rate > 0:
            excess_spend = (raw_benefit * conv_rate - limit) / (rate * conv_rate)
            final_benefit += (excess_spend * fallback_rate * conv_rate)

        return {
            "benefit_id": benefit.get("benefit_id"),
            "content": benefit.get("content", ""),
            "category": benefit.get("category"),
            "sub_category": benefit.get("sub_category", "general"),
            "group_id": benefit.get("group_id"),
            "selective_group_id": (benefit.get("selective_choice") or {}).get("group_id"),
            "choice_id": (benefit.get("selective_choice") or {}).get("choice_id"),
            "yielded_discount": round(final_benefit * conv_rate),
            "applied_budget": round(used_budget),
            "tier_applied": tier.get("min_prev_performance") if tier else None,
            "warnings": benefit.get("conditional_metadata", {}).get("warnings", [])
        }

    def _apply_complex_logic(self, results: list[dict], performance: float) -> list[dict]:
        """[2. 복합 조건 공식] 적용 (SHARED_LIMIT, SELECTIVE_GROUP, AUTO_TOP_N)."""
        # 1. SELECTIVE_GROUP 처리 (패키지 중 하나 선택)
        sel_groups = defaultdict(lambda: defaultdict(list))
        for r in results:
            if r["selective_group_id"]:
                sel_groups[r["selective_group_id"]][r["choice_id"]].append(r)

        for sg_id, choices in sel_groups.items():
            # 각 choice(패키지)별 합산 금액 계산
            choice_totals = []
            for c_id, g_items in choices.items():
                total = sum(i["yielded_discount"] for i in g_items)
                choice_totals.append((c_id, total))
            
            if not choice_totals: continue
            best_c_id, _ = max(choice_totals, key=lambda x: x[1])
            
            # 나머지 패키지 무효화
            for c_id, g_items in choices.items():
                if c_id != best_c_id:
                    for i in g_items:
                        i["yielded_discount"] = 0
                        i["applied_budget"] = 0

        # 2. SHARED_LIMIT / AUTO_TOP_N 처리
        group_buckets = defaultdict(list)
        for r in results:
            if r["group_id"]:
                group_buckets[r["group_id"]].append(r)

        for gid, items in group_buckets.items():
            g_info = self.groups.get(gid)
            if not g_info: continue
            
            g_type = g_info.get("group_type", "SHARED_LIMIT")
            
            # 티어별 그룹 한도 확인 (가변 한도)
            # 여기서는 편의상 혜택들 중 하나(첫번째)의 티어 조건을 대표로 사용하거나 
            # 그룹용 티어 검색을 별도로 수행할 수 있음. 
            # 스키마 구조상 혜택별 tier_conditions 에 group_monthly_limit 이 있음.
            g_limit = g_info.get("monthly_limit") or INF
            
            # 해당 그룹에 속한 혜택들 중 적용된 티어가 있다면 그룹 한도를 Override
            for r in items:
                # 혜택 객체를 다시 찾아 티어 정보를 가져옴
                matching_benefit = next((b for b in self.benefits if b["benefit_id"] == r["benefit_id"]), None)
                if matching_benefit:
                    tier = self._find_best_tier(matching_benefit.get("tier_conditions", []), performance)
                    if tier and tier.get("group_monthly_limit") is not None:
                        g_limit = tier["group_monthly_limit"]
                        break

            if g_type == "AUTO_TOP_N":
                # 2-5 공식: 상위 N개 혜택만 합산
                n = g_info.get("top_n_count") or 1
                sorted_items = sorted(items, key=lambda x: x["yielded_discount"], reverse=True)
                for idx, r in enumerate(sorted_items):
                    if idx >= n:
                        r["yielded_discount"] = 0
                        r["applied_budget"] = 0
            
            # 2-1 공식: 그룹 통합 한도 캡 적용
            total_g_benefit = sum(r["yielded_discount"] for r in items)
            if total_g_benefit > g_limit:
                ratio = g_limit / total_g_benefit
                for r in items:
                    r["yielded_discount"] = round(r["yielded_discount"] * ratio)

        return results

    def calculate(self, user_budgets: dict, user_total_spend: int | None = None) -> dict:
        """메인 계산 시퀀스."""
        # 1. 실적 확정 (User 피드백 반영: 보정 없이 총 소비액을 실적으로 간주)
        if user_total_spend is None:
            user_total_spend = sum((v.get("total", 0) if isinstance(v, dict) else v) for v in user_budgets.values())
        
        performance = user_total_spend
        min_perf = self.meta.get("minimum_performance", 0)
        performance_met = performance >= min_perf

        result = {
            "card_name": self.meta.get("card_name"),
            "card_id": self.meta.get("card_id"),
            "performance_met": performance_met,
            "monthly_total_krw": 0,
            "category_breakdown": [],
            "applied_benefits_trace": []
        }
        if not performance_met:
            return result

        # 2. 개별 혜택 1차 계산
        intermediate_results = []
        for b in self.benefits:
            cat = b.get("category")
            sub_cat = b.get("sub_category", "general")
            
            # 소비 데이터에서 해당 카테고리/서브카테고리 예산 추출
            cat_data = user_budgets.get(cat, 0)
            if isinstance(cat_data, dict):
                total_cat_budget = cat_data.get("total", 0)
                if sub_cat == "general":
                    budget = total_cat_budget
                else:
                    ratio_str = str(cat_data.get(sub_cat, "0%")).replace("%", "")
                    budget = total_cat_budget * (float(ratio_str) / 100.0)
            else:
                budget = float(cat_data)
            
            if budget <= 0: continue
            
            res = self._calc_single_benefit(b, budget, performance)
            if res["yielded_discount"] > 0:
                intermediate_results.append(res)

        # 3. 그룹 및 복합 로직 적용
        final_results = self._apply_complex_logic(intermediate_results, performance)

        # 4. 결과 집계
        cat_agg = defaultdict(lambda: {"monthly_discount_krw": 0, "discount_info": defaultdict(int), "warnings": set()})
        for r in final_results:
            if r["yielded_discount"] <= 0: continue
            
            cat_agg[r["category"]]["monthly_discount_krw"] += r["yielded_discount"]
            cat_agg[r["category"]]["discount_info"][r["sub_category"]] += r["yielded_discount"]

            # 혜택별 경고(warnings)가 있으면 카테고리 레벨로 수집
            if r.get("warnings"):
                cat_agg[r["category"]]["warnings"].update(r["warnings"])
            
            result["applied_benefits_trace"].append({
                "benefit_id": r["benefit_id"],
                "content": r["content"],
                "applied_budget": r["applied_budget"],
                "yielded_discount": r["yielded_discount"],
                "user_choice": True,
                "warnings": r.get("warnings", [])
            })

        for cat, data in cat_agg.items():
            result["category_breakdown"].append({
                "category": cat,
                "monthly_discount_krw": data["monthly_discount_krw"],
                "discount_info": dict(data["discount_info"]),
                "warnings": sorted(list(data["warnings"]))
            })

        result["monthly_total_krw"] = sum(r["yielded_discount"] for r in final_results)
        result["annual_total_krw"] = result["monthly_total_krw"] * 12

        return result

# =============================================================================
# 직접 실행/테스트부
# =============================================================================
if __name__ == "__main__":
    import json
    import os

    # 1. 샘플 데이터 로드 (현대카드 Z family Ed2 활용)
    # 실제 환경에서는 datasets/json_v4 에서 읽어옴
    sample_json_path = "c:/Users/vs501/Documents/workspace/SmartPick-Neo/datasets/json_v4/hyundai/hyundai_z_family_ed2.json"
    
    if os.path.exists(sample_json_path):
        with open(sample_json_path, "r", encoding="utf-8") as f:
            card_data = json.load(f)
        
        calc = BenefitCalculator(card_data)
        
        # 2. 샘플 페이로드 (dummy_20s_male 기반)
        payload = {
            "Traffic": {"total": 100000, "fuel": "100%"},
            "Shopping": {"total": 150000, "online": "100%"},
            "EduHealth": {"total": 200000, "hospital": "50%", "education": "50%"}
        }
        
        # 실적 100만원 가정 (한도 1만원 증가 확인용)
        res_100 = calc.calculate(payload, user_total_spend=1000000)
        print(f"--- {res_100['card_name']} (실적 100만) ---")
        print(f"월 총 혜택: {res_100['monthly_total_krw']:,}원")
        for cb in res_100["category_breakdown"]:
            print(f" - {cb['category']}: {cb['monthly_discount_krw']:,}원")

        # 실적 50만원 가정 (한도 6천원 확인용)
        res_50 = calc.calculate(payload, user_total_spend=500000)
        print(f"\n--- {res_50['card_name']} (실적 50만) ---")
        print(f"월 총 혜택: {res_50['monthly_total_krw']:,}원")
    else:
        print(f"파일을 찾을 수 없습니다: {sample_json_path}")