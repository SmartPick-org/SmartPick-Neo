from app.domain.adapters import adapt_v3_for_calculator


def test_adapt_v3_for_calculator_fills_defaults_and_converts_method():
    card = {
        "card_meta": {"reward_currency": "KRW", "currency_to_krw_rate": 1.0},
        "benefits": [
            {
                "calculation_rule": {
                    "calc_method": "FIXED_PER_VOLUME",
                    "fixed_amount": 3,
                },
                "transaction_conditions": {},
                "edge_case_flags": {},
            }
        ],
    }

    adapted = adapt_v3_for_calculator(card)
    benefit = adapted["benefits"][0]

    assert benefit["reward_unit"]["currency"] == "KRW"
    assert benefit["calculation_rule"]["calc_method"] == "PER_UNIT"
    assert benefit["calculation_rule"]["unit_label"] == "liter"
    assert benefit["calculation_rule"]["unit_amount"] == 3
    assert benefit["transaction_conditions"]["min_payment_amount"] == 0
    assert benefit["edge_case_flags"]["requires_user_selection"] is False


def test_adapt_v3_preserves_existing_values_and_handles_none_sections():
    card = {
        "card_meta": {"reward_currency": "USD", "currency_to_krw_rate": 1300.0},
        "benefits": [
            {
                "reward_unit": {"currency": "EUR", "currency_to_krw_rate": 1400.0},
                "calculation_rule": {
                    "calc_method": "RATE",
                    "unit_label": "custom",
                    "unit_amount": 7,
                    "monthly_usage_limit": 5,
                },
                "transaction_conditions": None,
                "edge_case_flags": None,
            }
        ],
    }

    adapted = adapt_v3_for_calculator(card)
    benefit = adapted["benefits"][0]

    assert benefit["reward_unit"]["currency"] == "EUR"
    assert benefit["reward_unit"]["currency_to_krw_rate"] == 1400.0
    assert benefit["calculation_rule"]["calc_method"] == "RATE"
    assert benefit["calculation_rule"]["unit_label"] == "custom"
    assert benefit["calculation_rule"]["unit_amount"] == 7
    assert benefit["calculation_rule"]["monthly_usage_limit"] == 5
    assert benefit["transaction_conditions"]["min_payment_amount"] == 0
    assert benefit["transaction_conditions"]["time_of_day"] == {"start": None, "end": None}
    assert benefit["edge_case_flags"]["performance_gap_forgiveness"] == {"enabled": False}
