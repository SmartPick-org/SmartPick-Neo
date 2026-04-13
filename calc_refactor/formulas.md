# 카드 혜택 계산용 표준 공식 (Formulas)

이 문서는 사용자의 소비 데이터(`user_spend`)를 기반으로 카드의 실질적인 금전적 혜택(원화 단위)을 도출하기 위한 **표준화된 계산 공식**을 정의합니다.

사용자에게 상세한 결제 건수(`usage_count`)나 건당 금액(`per_usage_spend`)을 묻지 않고, **주어진 예산 내에서 가장 최적으로 혜택을 수령했다는 가정** 하에 계산이 이루어집니다.

---

## 1. 혜택 유형별 월간 계산 기본 공식

### 1-1. 비율 할인 및 적립 (Percentage Discount / Accumulation)
가장 일반적인 형태의 혜택으로, 사용 금액에 비례하여 혜택을 제공하며 월 최대 한도가 존재할 수 있습니다.

* **입력 변수**: `spend_amount` (해당 업종 소비액)
* **카드 변수**: `benefit_rate` (혜택 비율, 예: 10% = 0.1), `max_monthly_limit` (월 혜택 한도)
* **공식**:
  $$ Monthly\_Benefit = \min(spend\_amount \times benefit\_rate,\ max\_monthly\_limit) $$

### 1-2. 정액 할인 (Flat-Rate Discount)
"1만원 이상 결제 시 5천원 할인"과 같이 건당 결제액 조건을 만족할 때 고정 금액을 할인해 주는 형태입니다.
최적화 가정을 적용하여, 주어진 총액이 혜택 요건(건당 최소 금액)을 얼마나 최대로 달성할 수 있는지 산출합니다.

* **입력 변수**: `spend_amount`
* **카드 변수**: `min_payment_amount` (요구되는 최소 1회 결제 금액, 조건 없으면 0이나 일상적 결제액 추정치 활용), `flat_discount` (할인 정액), `max_count_per_month` (월 제공 가능 횟수)
* **최적 사용 횟수 추정**:
  $$ Optimal\_Uses = \lfloor \frac{spend\_amount}{min\_payment\_amount} \rfloor $$
* **공식**:
  $$ Monthly\_Benefit = \min(Optimal\_Uses,\ max\_count\_per\_month) \times flat\_discount $$

### 1-3. 리터당 할인 (Per Liter Discount - 주유 업종 전용)
주유소 혜택에서 주로 쓰이며, 평균 유가를 외부 환경 변수로 받아 계산합니다.

* **입력 변수**: `spend_amount` (주유 비), `avg_gas_price` (리터당 평균 유가)
* **카드 변수**: `discount_per_liter` (리터당 할인액), `max_monthly_limit` (월 혜택 한도)
* **공식**:
  $$ Estimated\_Liters = \frac{spend\_amount}{avg\_gas\_price} $$
  $$ Monthly\_Benefit = \min(Estimated\_Liters \times discount\_per\_liter,\ max\_monthly\_limit) $$

---

## 2. 복합 조건 (상위 레이어 계산 공식)

### 2-1. 통합 한도 (Shared Limit)
여러 세부 카테고리가 하나의 통합 한도 풀(Pool)을 공유할 때, 개별 한도를 산출한 후 합산 과정에서 캡(Cap)을 씌웁니다.

* **가정**: 같은 `shared_limit_group`에 속한 카테고리들 ($C_1, C_2, ... C_n$)
* **공식**:
  $$ Group\_Benefit = \min( \sum_{i=1}^{n} Monthly\_Benefit(C_i),\ Shared\_Monthly\_Limit ) $$

### 2-2. 포인트 환산 (Point to Cash Conversion)
M포인트, 마이신한포인트 등 쌓인 포인트를 실질적인 현금 가치로 변환합니다.

* **가정**: 1포인트가 원화로 온전히 1:1 대응되지 않는 경우
* **공식**:
  $$ Fiat\_Value = Total\_Points \times point\_conv\_rate $$

### 2-3. 필수 선택형 그룹 내결정 (Selective Group Optimization)
A, B, C 그룹 중 택1 해야 하는 혜택의 경우, 각 그룹별 시뮬레이션 결과 중 최댓값을 반환합니다.

* **공식**:
  $$ Ultimate\_Benefit = \max( Group\_Benefit\_A,\ Group\_Benefit\_B,\ Group\_Benefit\_C ) $$

---

## 3. 연간 혜택 확장 (Annual Extension)

도출된 1개월 치의 최적 혜택액(`Monthly_Benefit`)을 1년 단위 혜택으로 확장합니다. 이 과정에서 연간 제한 횟수나 연간 한도 변수가 존재하면 이를 적용하고, **관련 변수가 명시되어 있지 않은 혜택은 자동으로 12배수 처리**를 수행합니다.

* **카드 변수**: `max_limit_per_year` (연간 한도액), `max_count_per_year` (연간 횟수 제한 - 정액 할인 등의 횟수에 적용)
* **연간 한도 공식 (금액 캡)**:
  $$ Annual\_Benefit = 
  \begin{cases} 
  \min(Monthly\_Benefit \times 12, max\_limit\_per\_year) & \text{if } max\_limit\_per\_year \text{ exists} \\
  Monthly\_Benefit \times 12 & \text{otherwise}
  \end{cases} $$

*(예: 월 1회, 연 6회 스타벅스 5천원 할인 혜택이라면, 월 계산에서는 5천원 도출. 연 계산으로 넘어가면 연간 횟수 제한 캡에 걸려 5,000 * 6 = 30,000원으로 환산됨)*
