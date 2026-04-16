import json
import requests

def test_recalculate_shared_limit():
    url = "http://127.0.0.1:8000/cards/recommend"
    payload = {
        "total_budget": 1000000,
        "category_spending": {
            "Food": {
                "total": 200000,
                "restaurant": "100%"
            },
            "Shopping": {
                "total": 200000,
                "beauty": "100%"
            }
        }
    }
    
    print("--- [1] Initial Recommendation ---")
    res = requests.post(url, json=payload)
    res_data = res.json()
    
    # KB 마이원 카드 찾기
    myone = next((c for c in res_data["recommended_cards"] if c["card_id"] == "kb_myone"), None)
    if not myone:
        print("KB 마이원 카드를 찾을 수 없습니다.")
        return

    print(f"Card: {myone['card_name']}")
    print(f"Total Benefit: {myone['expected_monthly_benefit']}")
    for t in myone["applied_benefits_trace"]:
        print(f"  - {t['benefit_id']}: {t['yielded_discount']} KRW")

    # [2] 재계산 테스트 (B_FAMILYRESTAURANT_001 체크 해제)
    print("\n--- [2] Recalculating (Unchecking Restaurant) ---")
    recalc_url = "http://127.0.0.1:8000/cards/recalculate"
    recalc_payload = {
        "total_budget": payload["total_budget"],
        "category_spending": payload["category_spending"],
        "recommended_cards": [myone],
        "excluded_benefit_ids": ["B_FAMILYRESTAURANT_001"]
    }
    
    res_recalc = requests.post(recalc_url, json=recalc_payload)
    if res_recalc.status_code != 200:
        print(f"API Error ({res_recalc.status_code}): {res_recalc.text}")
        return
        
    recalc_data = res_recalc.json()
    
    updated_myone = recalc_data["recommended_cards"][0]
    print(f"Updated Total Benefit: {updated_myone['expected_monthly_benefit']}")
    for t in updated_myone["applied_benefits_trace"]:
        status = "OFF" if not t["user_choice"] else "ON"
        print(f"  - [{status}] {t['benefit_id']}: {t['yielded_discount']} KRW")

    # 검증 로직
    # 단순 합산이면 1만원이 되어야 함. 
    # Deep Recalculation이면 미용실(B_BEAUTY_001)이 1만원 -> 2만원으로 늘어나서 총액이 2만원 유지되어야 함.
    if updated_myone['expected_monthly_benefit'] == 20000:
        print("\n✅ SUCCESS: Deep recalculation logic verified! Limit redistributed correctly.")
    else:
        print("\n❌ FAILURE: Logic fallback to shallow calculation.")

if __name__ == "__main__":
    try:
        test_recalculate_shared_limit()
    except Exception as e:
        print(f"Error: {e}")
