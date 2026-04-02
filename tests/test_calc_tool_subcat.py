import json
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.tools.Calc_tool import BenefitCalculator

def run_tests():
    # ── 테스트 케이스 1: 여러 sub_category 비율이 지정된 경우 ──
    mock_card_1 = {
        "card_meta": {
            "card_id": "test_shopping_traffic",
            "card_name": "Test Shopping & Traffic Card",
            "card_company": "TEST",
            "annual_fee_domestic": 0,
            "annual_fee_international": None,
            "minimum_performance": 0,
            "performance_excluded_categories": [],
        },
        "benefit_groups": [],
        "benefits": [
            {
                "benefit_id": "b_shop_online",
                "category": "Shopping",
                "sub_category": "online",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "tier_conditions": [],
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.10,
                    "monthly_limit": None,
                },
                "transaction_conditions": {},
            },
            {
                "benefit_id": "b_shop_mart",
                "category": "Shopping",
                "sub_category": "mart",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "tier_conditions": [],
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.05,
                    "monthly_limit": None,
                },
                "transaction_conditions": {},
            },
            {
                "benefit_id": "b_traffic_transit",
                "category": "Traffic",
                "sub_category": "transit",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "tier_conditions": [],
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.20,
                    "monthly_limit": None,
                },
                "transaction_conditions": {},
            }
        ]
    }

    input_1 = {
        "Shopping": {
            "total": 100000,
            "online": "70%",
            "mart": "30%"
        },
        "Traffic": {
            "total": 50000,
            "transit": "100%"
        }
    }

    print("=" * 70)
    print("Test 1: Multiple sub_categories parsed from dict")
    calc1 = BenefitCalculator(mock_card_1)
    res1 = calc1.calculate(input_1)
    print(json.dumps(res1["category_breakdown"], indent=2, ensure_ascii=False))


    # ── 테스트 케이스 2: 한도 제한 및 소수점/문자열 비율 처리 ──
    mock_card_2 = {
        "card_meta": {
            "card_id": "test_coffee",
            "card_name": "Test Coffee Card",
            "card_company": "TEST",
            "minimum_performance": 0,
        },
        "benefit_groups": [],
        "benefits": [
            {
                "benefit_id": "b_cafe",
                "category": "Coffee",
                "sub_category": "cafe",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.10,
                    "monthly_limit": 5000, # 한도 걸림 (8만원 * 10% = 8천원이지만 5천원으로)
                },
                "transaction_conditions": {},
            },
            {
                "benefit_id": "b_bakery",
                "category": "Coffee",
                "sub_category": "bakery",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.10,
                    "monthly_limit": 5000, # 한도 안걸림 (2만원 * 10% = 2천원)
                },
                "transaction_conditions": {},
            }
        ]
    }

    input_2 = {
        "Coffee": {
            "total": 100000,
            "cafe": "80%",
            "bakery": "20%"
        }
    }

    print("\n" + "=" * 70)
    print("Test 2: Budget split respects monthly limits")
    calc2 = BenefitCalculator(mock_card_2)
    res2 = calc2.calculate(input_2)
    print(json.dumps(res2["category_breakdown"], indent=2, ensure_ascii=False))


    # ── 테스트 케이스 3: 역호환성 (int 값) 및 sub_category 미매칭 ──
    mock_card_3 = {
        "card_meta": {
            "card_id": "test_backward",
            "card_name": "Test Backward Compatibility",
            "card_company": "TEST",
            "minimum_performance": 0,
        },
        "benefit_groups": [],
        "benefits": [
            {
                "benefit_id": "b_food_general",
                "category": "Food",
                # sub_category 미지정 (또는 null)
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.05,
                    "monthly_limit": None,
                },
                "transaction_conditions": {},
            },
            {
                "benefit_id": "b_travel_airline",
                "category": "Travel",
                "sub_category": "airline",
                "frequency": "MONTHLY",
                "reward_type": "DISCOUNT",
                "reward_unit": {"currency": "KRW", "currency_to_krw_rate": 1.0},
                "calculation_rule": {
                    "calc_method": "RATE",
                    "rate": 0.10,
                    "monthly_limit": None,
                },
                "transaction_conditions": {},
            }
        ]
    }

    input_3 = {
        "Food": 200000, # 구형 인풋 (int)
        "Travel": {
            "total": 300000,
            "hotel": "100%" # airline은 매칭되지 않으므로 0원
        }
    }

    print("\n" + "=" * 70)
    print("Test 3: Backward compatibility (int) & Unmatched sub_cat")
    calc3 = BenefitCalculator(mock_card_3)
    res3 = calc3.calculate(input_3)
    print(json.dumps(res3["category_breakdown"], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_tests()
