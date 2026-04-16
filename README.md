# SmartPick-Neo

소비 패턴 입력을 받아 혜택이 가장 큰 신용카드를 추천하고, LLM으로 추천 근거를 설명하는 백엔드 서비스입니다.

---

## 기술 스택

- **Python 3.12+** · **FastAPI** · **Pydantic v2**
- **uv** (의존성 관리)
- **Supabase** (DB & Storage) — 카드·약관·요약(digest) 저장소
- **LangChain + Upstage Solar** (LLM 설명/QA 생성)
- **Better Stack (Logtail)** (로그 수집) · **Discord Webhook** (에러 알림)
- **loguru** (구조화 로깅) · **pycircuitbreaker + tenacity** (LLM 회복력)

---

## 프로젝트 구조

```
app/
  api/          # FastAPI 라우터 (cards, advisor)
  core/         # config, logger, middleware, exceptions, database, discord, resilience
  domain/       # 도메인 어댑터/모델
  prompts.py    # LLM 프롬프트 템플릿
  repositories/ # card_repo, digest_repo, terms_repo, manual_repo
  schemas/      # Pydantic 요청/응답 스키마
  services/     # card_service (추천), explain_service (LLM), advise_service
  tools/        # Calc_tool — 혜택 계산 엔진
  utils/        # masking, markdown/pdf 유틸

datasets/
  json_v4/      # 카드 마스터 데이터 (hyundai, kb, shinhan)
  digest/       # 카드 요약 마크다운 (LLM 프롬프트에 주입)
  terms/        # 약관 마크다운
  markdown_upstage/ # 원본 약관·혜택 설명

scripts/        # 데이터 파이프라인: generate_json_v4/v5, generate_digest, upload_cards_to_db 등
tests/          # pytest (단위/회귀 테스트)
```

---

## 사전 준비

- Python **3.12** 이상 (`pyproject.toml`의 `requires-python = ">=3.12"`)
- [uv](https://github.com/astral-sh/uv)

```bash
uv python install 3.12
uv sync
```

---

## 환경 변수

프로젝트 루트에 `.env` 파일을 만들고 필요한 값만 설정합니다. 비어 있으면 해당 기능이
graceful하게 비활성화됩니다 (로컬 개발 편의).

### 필수 (운영)
| 변수 | 설명 |
|---|---|
| `UPSTAGE_API_KEY` | Solar LLM 호출용 |
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | Supabase anon 키 (DB 쿼리) |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 (private 버킷 접근) |

### 선택
| 변수 | 기본값 | 설명 |
|---|---|---|
| `ENV` | `production` | `production` 이면 JSON 구조화 stdout 로깅, 그 외엔 개발용 포맷 |
| `LOGTAIL_SOURCE_TOKEN` | — | Better Stack 연동 (없으면 로컬/stdout만) |
| `LOGTAIL_HOST` | — | Better Stack 커스텀 호스트 |
| `DISCORD_WEBHOOK_URL` | — | 서버 장애 시 알림 (없으면 skip) |
| `LLM_TIMEOUT` | `30.0` | LLM 단일 호출 타임아웃(초) |
| `LLM_TOTAL_TIMEOUT` | `65.0` | 재시도 포함 총 타임아웃(초) |
| `LLM_MAX_RETRIES` | `2` | 재시도 횟수 |
| `LLM_CB_FAILURE_THRESHOLD` | `5` | 서킷브레이커 OPEN 조건 |
| `LLM_CB_RECOVERY_TIMEOUT` | `60` | HALF_OPEN 회복 대기(초) |

---

## 실행

### 개발 서버

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

헬스체크: `GET /` → `{"status": "ok"}`
OpenAPI UI: `http://localhost:8000/docs`

### 운영 모드

```bash
ENV=production uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 주요 API

전체 명세는 `/docs` (Swagger UI) 또는 `/openapi.json`을 참고하세요.

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/v1/cards` | 카드 카탈로그 (검색·필터·페이징) |
| GET | `/api/v1/cards/{card_id}` | 카드 상세 |
| POST | `/api/v1/cards/recommend` | 소비 패턴 기반 카드 추천 (LLM 설명 포함) |
| POST | `/api/v1/cards/compare` | 기존 카드 vs 추천 카드 비교 |
| POST | `/api/v1/cards/recalculate` | 영수증 체크박스 토글 재계산 (<50ms) |
| POST | `/api/v1/cards/qa` | 추천 결과 원본 JSON 기반 자유 질의 |
| POST | `/api/v1/advisor/ask` | 특정 카드 상세 정보(수수료·후기 등) 답변 |
| GET | `/api/v1/advisor/queries` | 버튼 그룹별 query_type 목록 |

---

## 데이터 파이프라인

크롤링된 카드 설명 마크다운 → 구조화 JSON → 요약(digest) → Supabase 업로드 순서로 돌아갑니다.

```bash
# 원본 마크다운 → 구조화 JSON v4
uv run python -m scripts.generate_json_v4

# 구조화 JSON → digest 마크다운 (LLM 프롬프트용 요약)
uv run python -m scripts.generate_digest

# Supabase DB/Storage 업로드
uv run python -m scripts.upload_cards_to_db
```

스크립트는 모두 **모듈 방식(`python -m`)**으로 실행하세요.
경로 기반 실행(`python scripts/xxx.py`)은 import 오류가 납니다.

---

## 테스트

```bash
uv run pytest tests/ -v
```

현재 **127개 테스트** 유지. CI(`.github/workflows/test.yml`)에서 PR·push 시 자동 실행됩니다.

---

## 상수 관리 가이드

| 파일 | 상수 | 의미 |
|---|---|---|
| `app/core/config.py` | `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_CB_*` | LLM 연결·회복력 설정 (`.env`로 오버라이드) |
| `app/tools/Calc_tool.py` | `DEFAULT_FUEL_PRICE_PER_LITER`, `DAYS_PER_MONTH` 등 | 혜택 계산 기준값 (유가, 월 기준일수) |
| `app/services/card_service.py` | `_CONCURRENCY_LIMIT` | asyncio 동시 계산 카드 수 상한 |
| `app/services/advise_service.py` | `_CACHE_TTL_DAYS` | 상담 캐시 유효 기간 |
| `app/core/resilience.py` | `wait_exponential(multiplier, min, max)` | 재시도 백오프 파라미터 |

> **변경 시 참고:** LLM 동작 관련은 `.env` 우선 확인. 계산 로직 관련은 `app/tools/Calc_tool.py` 상단 상수 블록 확인.

---

## 에러 핸들링 & 알림

- **`SystemException`** / 미분류 `Exception` / `KeyError` → 500 응답 + Discord 알림
- **`BusinessException`** (NoCardsFoundError, LLMUnavailableError 등) → 4xx 응답, 알림 없음
- **`ValueError`** → 400 (사용자 입력 검증 실패)
- 모든 요청에 `request_id`(UUID)가 할당되어 로그에 바인딩됨

---

## 트러블슈팅

- **`uv sync`가 `tokenizers` 빌드 실패로 멈춤**
  → Python 3.14 등 너무 최신 버전으로 가상환경을 만들면 발생. 3.12 또는 3.13 사용.

- **`ModuleNotFoundError: No module named 'app'`**
  → 프로젝트 루트에서 실행해야 합니다. `cd <repo-root>` 후 `uv run ...`.

- **`KeyError` 응답 500 + Discord 알림이 떨어짐**
  → 사용자 입력 오류가 아니라 서버 버그입니다. 카드 데이터셋의 필수 필드 누락이나
  `Calc_tool` 로직 이슈가 주 원인. Logtail에서 request_id로 로그 추적.
