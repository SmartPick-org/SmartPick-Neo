def adapt_v3_for_calculator(card_data: dict) -> dict:
    """
    json_v3 스키마를 BenefitCalculator가 기대하는 형식으로 어댑팅합니다.

    주요 변환:
    - FIXED_PER_VOLUME → PER_UNIT + unit_label/unit_amount 추가
    - reward_unit을 card_meta에서 benefit별로 복사
    - 누락된 필드에 기본값 채우기
    """
    meta = card_data.get("card_meta", {})
    currency = meta.get("reward_currency", "KRW")
    krw_rate = meta.get("currency_to_krw_rate", 1.0)

    adapted_benefits = []
    for benefit in card_data.get("benefits", []):
        adapted = dict(benefit)

        if "reward_unit" not in adapted or adapted["reward_unit"] is None:
            adapted["reward_unit"] = {
                "currency": currency,
                "currency_to_krw_rate": krw_rate,
            }

        rule = dict(adapted.get("calculation_rule") or {})
        if rule.get("calc_method") == "FIXED_PER_VOLUME":
            rule["calc_method"] = "PER_UNIT"
            rule.setdefault("unit_label", "liter")
            rule.setdefault("unit_amount", rule.get("fixed_amount", 0))

        rule.setdefault("unit_label", None)
        rule.setdefault("unit_amount", None)
        rule.setdefault("monthly_usage_limit", None)
        rule.setdefault("fallback_reward_rate", 0.0)
        rule.setdefault("transaction_tiers", None)
        adapted["calculation_rule"] = rule

        tc = dict(adapted.get("transaction_conditions") or {})
        tc.setdefault("min_payment_amount", 0)
        tc.setdefault("max_payment_amount_applied", None)
        tc.setdefault("max_count_per_day", None)
        tc.setdefault("max_count_per_month", None)
        tc.setdefault("max_count_per_year", None)
        tc.setdefault("day_of_week", None)
        tc.setdefault("time_of_day", {"start": None, "end": None})
        tc.setdefault("requires_auto_payment", False)
        tc.setdefault("requires_offline", False)
        tc.setdefault("requires_online", False)
        adapted["transaction_conditions"] = tc

        ef = dict(adapted.get("edge_case_flags") or {})
        ef.setdefault("requires_user_selection", False)
        ef.setdefault("excludes_from_performance", False)
        ef.setdefault("category_excludes_from_performance", False)
        ef.setdefault("special_month_bonus", None)
        ef.setdefault("performance_gap_forgiveness", {"enabled": False})
        ef.setdefault("current_month_performance", False)
        ef.setdefault("payment_platform_bonus", {"platform": None, "additional_rate": None})
        ef.setdefault("annual_usage_tiers", [])
        ef.setdefault("annual_voucher", {})
        ef.setdefault("escape_hatch_note", None)
        adapted["edge_case_flags"] = ef

        adapted_benefits.append(adapted)

    return {
        "card_meta": meta,
        "benefit_groups": card_data.get("benefit_groups", []),
        "benefits": adapted_benefits,
    }
