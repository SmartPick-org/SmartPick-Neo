# SmartPick-Neo 엣지 케이스 처리/검증 리포트

## 요약
이 문서는 `LLM 장애`, `데이터 누락(KeyError)`, `입력값 오류(ValueError/TypeError)`, `LangGraph 오류 복구`, `계산 툴(Calc_tool) 실패` 같은 엣지 케이스에서 서버가 **raw 500을 그대로 노출하지 않고**, 가능한 경우 **graceful degradation(기본/대체 응답)** 을 수행하도록 코드를 보강하고, 추가 엣지 케이스 테스트를 추가/실행한 내역을 정리합니다.

---

## 목표(스펙 기반)
1. 전역 예외 처리기 추가
2. API 레벨 방어 로직 추가
3. LangGraph 에러 복구 노드 추가
4. Calc_tool 입력/예외 안정성 보강
5. 중요한 시스템 레벨 에러는 로그/스택 트레이스로 남김
6. 예외/실패 시 에러 응답 포맷 일관화
   - 응답 포맷: `{ "error_code": str, "message": str, "detail": optional, "fallback": bool }`

---

## 구현된 내용 (코드 보강)

### 1) 전역 예외 처리기: `app/main.py`
- 전역 예외 핸들러를 추가/정비하여 에러 응답을 공통 포맷으로 반환하도록 구성했습니다.
- 예외 분기 규칙:
  - `ValueError / KeyError` → HTTP 400
  - `BusinessException` → HTTP 422
  - 그 외 `SystemException / Exception` → HTTP 500 (generic message)
  - `RequestValidationError` → HTTP 422 (Pydantic body validation 오류)
- 로그/알림 구조:
  - `logger.exception`으로 stack trace 기록
  - 향후 Slack 연동 가능하도록 `_notify_error_channels()`를 두고, 현재는 Discord만 호출합니다.

관련: `app/main.py`

---

### 2) API 레벨 방어 로직: `app/api/card.py`
`/cards/recommend`, `/cards/qa`에서 raw 500이 새지 않도록 방어를 강화했습니다.

#### `/cards/recommend`
- Pydantic 1차 검증 이후 추가 방어:
  - `total_budget <= 0` → `ValueError`로 400 처리
  - `category_spending` 비어있거나 값이 0 이하 → `ValueError`로 400 처리
- LLM init 실패:
  - `ExplainService(get_llm())` 생성 실패 시 `explain_service=None`으로 두고 계속 진행
  - 설명은 `_LLM_FALLBACK_EXPLAIN` 문자열로 대체
- 데이터 누락/KeyError 가능 구간 방어:
  - `calculate_benefits()` 중 KeyError → `ValueError`로 변환(400 경로로 유도)
  - digest 로딩은 try/except로 실패 시 빈 digest 사용
  - `ExplainService.build_recommended_cards()` KeyError/예외 발생 시:
    - 안전 빌더 `_safe_build_recommended_cards()`로 대체 응답 생성(스키마 붕괴 방지)

관련: `app/api/card.py`

#### `/cards/qa`
- `raw_data`가 유효한 JSON 문자열인지 검사:
  - 실패 시 `ValueError`로 400
- LLM init/invoke 실패:
  - `LLMUnavailableError()` 발생(전역 핸들러로 에러 포맷 반환)
- `answer_qa()`에서 KeyError 발생 시에도 raw 500 방지 위해 `LLMUnavailableError()`로 통일

관련: `app/api/card.py`

---

### 3) LangGraph 에러 복구 노드: `app/workflows/v3_graph.py`
- `AgentState`에 에러 복구용 필드 `_error_type`, `_fallback`을 추가했습니다.
- `error_recovery_node`에서:
  - LLM 실패(`_error_type == "LLM"`)면
    - 기본 문구(`현재 답변 생성이 원활하지 않습니다...`)를 사용
    - `_fallback=True`를 명시적으로 state에 기록
  - 그 외 데이터/계산 실패면 state의 `_error_message`를 사용
- LLM 실패 경로에서 `build_recommended_cards`가 추가로 깨지지 않도록 예외 방어를 추가했습니다.

관련: `app/workflows/v3_graph.py`

---

### 4) Calc_tool 안정성 보강: `app/tools/Calc_tool.py`
- `BenefitCalculator.calculate()`에 최소 입력 검증을 추가했습니다.
- 계산 로직 전체를 try/except로 감싸서, 아래 예외에서 **예외 전파 대신 fallback 결과 dict을 반환**합니다.
  - `ZeroDivisionError`, `TypeError`, `ValueError`
- fallback 결과는:
  - 할인 합계 0 (`monthly_total_krw`, `annual_total_krw`)
  - `category_breakdown=[]`
  - `warnings=[원인 요약]`
  - `fallback=True`
- 계산 실패가 발생해도 다운스트림이 스키마를 기대할 수 있도록 **최소한의 구조**를 유지합니다.

관련: `app/tools/Calc_tool.py`

---

## 테스트(엣지 케이스) 추가 및 실행

### 추가한 통합 테스트 파일
- `tests/test_edge_case_fallbacks.py`
- 방식: `fastapi.testclient.TestClient` + `monkeypatch`로 LLM/서비스 호출을 결정적으로 실패/KeyError가 나도록 강제

### 포함한 엣지 케이스(5개)
1. `/cards/recommend` 입력값 오류(`total_budget=0`) → HTTP 400, `error_code=INVALID_INPUT`, `fallback=false`
2. `/cards/recommend` LLM 호출 실패 → HTTP 200, `explanation`이 fallback 문구로 채워짐
3. `/cards/recommend` `build_recommended_cards`에서 KeyError 발생 → HTTP 200, 안전 빌더로 최소 응답 생성
4. `/cards/qa` `raw_data`가 JSON이 아님 → HTTP 400, `error_code=INVALID_INPUT`
5. `/cards/qa` LLM init 실패 → HTTP 422, `error_code=LLM_UNAVAILABLE`, `fallback=true`

### 실행 커맨드 및 결과
- 커맨드: `.venv/bin/python -m pytest -q`
- 결과: `12 passed`

---

## 남아있는 리스크/주의사항
- 현재 문서의 목표(“모든 endpoint raw 500 방지”)를 **프로젝트 전체**로 엄격히 적용하려면, 타 라우터에서 아직 raw 500을 던지는 코드가 있는지 추가 점검이 필요합니다.
- 현재 확인된 예: `app/api/advisor.py`는 `HTTPException(status_code=500, ...)`를 그대로 던지고 있어, “raw 500 절대 노출” 목표를 전역으로 만족하지 못할 수 있습니다.

관련: `app/api/advisor.py`

---

## 다음에 하면 좋은 것(선택)
- `app/api/advisor.py`도 동일한 공통 에러 포맷/전역 핸들러 규칙에 맞추기
- `/cards/recommend` 성공 응답에도 구조적으로 `fallback` 필드를 포함시키는지 정책 결정(지금은 fallback 여부가 필드로 노출되지 않음)
- LangGraph(`v3_graph.py`)를 실제 endpoint 호출 경로에 연결해 통합 테스트 추가

