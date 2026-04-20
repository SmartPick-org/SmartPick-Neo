# SmartPick-Neo

**SmartPick**은 사용자의 월별 소비 패턴을 입력받아, 실제 혜택 금액을 계산하고 가장 유리한 신용카드 Top-N을 추천하는 백엔드 서비스입니다.
단순 카테고리 매칭이 아니라, 전월 실적 조건·공유한도·선택형 혜택 등 카드 약관 로직을 그대로 구현한 계산 엔진을 사용하고, Upstage Solar LLM으로 추천 근거를 자연어 설명까지 생성합니다.

---

## 목차

1. [주요 기능](#주요-기능)
2. [아키텍처 개요](#아키텍처-개요)
3. [기술 스택](#기술-스택)
4. [프로젝트 구조](#프로젝트-구조)
5. [시작하기](#시작하기)
   - [사전 요구사항](#사전-요구사항)
   - [설치](#설치)
   - [환경 변수](#환경-변수)
   - [서버 실행](#서버-실행)
6. [프론트엔드 연동](#프론트엔드-연동)
7. [주요 API](#주요-api)
8. [데이터 파이프라인](#데이터-파이프라인)
9. [테스트](#테스트)
10. [배포](#배포)
11. [상수 관리 가이드](#상수-관리-가이드)
12. [에러 핸들링 & 알림](#에러-핸들링--알림)
13. [트러블슈팅](#트러블슈팅)

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **카드 추천** | 월 예산·카테고리별 지출 입력 → 혜택 금액 기준 Top-N 카드 + LLM 설명 반환 |
| **카드 비교** | 현재 보유 카드 vs 추천 카드 혜택 차이를 LLM이 비교 설명 |
| **수혜 재계산** | 영수증 체크박스 토글(특정 혜택 제외) → 50ms 이내 재계산 및 순위 갱신 |
| **혜택 Q&A** | 추천 결과 원본 데이터를 기반으로 사용자 질문에 LLM이 답변 |
| **카드 어드바이저** | 특정 카드의 연회비·수수료·후기 등 상세 정보를 웹 검색 + LLM으로 답변 (Supabase 캐싱) |

---

## 아키텍처 개요

```
[Frontend (Vercel)]
        │  HTTP (REST API)
        ▼
[FastAPI Backend (EC2)]
        │
        ├── /cards/recommend  →  BenefitCalculator (카드별 병렬 계산)
        │                        └── ExplainService (Upstage Solar LLM)
        │
        ├── /cards/recalculate →  체크박스 토글 재계산 (shallow, <50ms)
        │                         └── 1순위 변경 시 LLM 재생성
        │
        ├── /cards/compare    →  ExplainService (LLM 비교 설명)
        ├── /cards/qa         →  ExplainService (LLM Q&A)
        │
        └── /advisor/ask      →  AdvisorAgent
                                  ├── Supabase 캐시 조회 (7일 TTL)
                                  ├── 매뉴얼/약관 문서 로딩
                                  └── Web Search (Naver → Tavily fallback)
                                       └── Upstage Solar LLM
```

추천 흐름 상세는 [`SmartPick Mermaid Flow.mmd`](SmartPick%20Mermaid%20Flow.mmd) 참조.

---

## 기술 스택

| 분류 | 기술 |
|---|---|
| **런타임** | Python 3.12+ · FastAPI · Uvicorn · Pydantic v2 |
| **의존성 관리** | [uv](https://github.com/astral-sh/uv) |
| **LLM** | LangChain + Upstage Solar Pro 2 (`solar-pro2`) |
| **DB / Storage** | Supabase (카드 데이터·약관·어드바이저 캐시) |
| **LLM 관측** | LangSmith · Langfuse |
| **로깅** | loguru · Better Stack (Logtail) |
| **알림** | Discord Webhook (서버 장애) |
| **LLM 회복력** | pycircuitbreaker · tenacity |
| **CI/CD** | GitHub Actions (테스트 자동화 · EC2 자동 배포) |

---

## 프로젝트 구조

```
app/
  api/              # FastAPI 라우터
    card.py         #   /cards/* 엔드포인트
    advisor.py      #   /advisor/* 엔드포인트
  core/             # 인프라 레이어
    config.py       #   환경 변수·LLM 초기화
    database.py     #   Supabase 클라이언트
    dependencies.py #   FastAPI 의존성 주입
    discord.py      #   Discord 웹훅 알림
    exceptions.py   #   BusinessException / SystemException
    logger.py       #   loguru 초기화
    middleware.py   #   요청 로깅 미들웨어
    resilience.py   #   서킷브레이커·재시도 설정
  domain/           # 도메인 어댑터/모델
  prompts.py        # LLM 프롬프트 템플릿
  repositories/     # DB 접근 계층
    card_repo.py    #   카드 마스터 데이터
    digest_repo.py  #   카드 요약 마크다운
    manual_repo.py  #   카드사 이용 안내 문서
    terms_repo.py   #   카드 약관
  schemas/          # Pydantic 요청·응답 스키마
  services/
    card_service.py    # 카드 필터링·혜택 계산·랭킹
    explain_service.py # LLM 설명 생성
    advise_service.py  # 어드바이저 에이전트 (웹 검색 + LLM)
  tools/
    Calc_tool.py    # 혜택 계산 엔진 (전월실적·공유한도·선택형 등)
    web_search.py   # 웹 검색 도구 (Naver / Tavily)
  utils/            # masking, markdown/pdf 유틸

datasets/
  json_v4/              # 카드 마스터 데이터 (현대·KB·신한)
  digest_v4/            # 카드 요약 마크다운 (LLM 프롬프트 주입용)
  terms/                # 약관 마크다운
  gemini_md/            # 원본 약관·혜택 설명 (파싱 전)
  manuals/              # 카드사 이용 안내 문서
  parsing_optimization/ # 파싱 최적화 실험 데이터

scripts/              # 데이터 파이프라인 스크립트
tests/                # pytest (단위·회귀 테스트, 256개)
```

---

## 시작하기

### 사전 요구사항

- **Python 3.12** 이상
- **[uv](https://github.com/astral-sh/uv)** 패키지 매니저
- Supabase 프로젝트 (카드 데이터·약관이 업로드된 상태)
- Upstage API 키 (Solar LLM 호출)

```bash
# uv 설치 (없을 경우)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 설치

```bash
git clone https://github.com/SmartPick-org/SmartPick-Neo.git
cd SmartPick-Neo

uv python install 3.12
uv sync
```

### 환경 변수

프로젝트 루트에 `.env` 파일을 생성합니다.
운영 환경이 아닌 경우 선택 항목이 없어도 해당 기능만 비활성화되고 서버는 정상 기동됩니다.

#### 필수

| 변수 | 설명 |
|---|---|
| `UPSTAGE_API_KEY` | Upstage Solar LLM 호출 |
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | Supabase anon 키 (DB 쿼리) |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 (private 버킷 접근) |
| `LANGSMITH_API_KEY` | LangSmith 트레이싱 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse 관측 (public key) |
| `LANGFUSE_SECRET_KEY` | Langfuse 관측 (secret key) |

#### 선택

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ENV` | `production` | `production`이면 JSON 구조화 stdout 로깅, 그 외 개발용 포맷 |
| `LOGTAIL_SOURCE_TOKEN` | — | Better Stack 연동 (없으면 stdout만) |
| `LOGTAIL_HOST` | — | Better Stack 커스텀 호스트 |
| `DISCORD_WEBHOOK_URL` | — | 서버 장애 시 Discord 알림 (없으면 skip) |
| `LLM_TIMEOUT` | `30.0` | LLM 단일 호출 타임아웃 (초) |
| `LLM_TOTAL_TIMEOUT` | `65.0` | 재시도 포함 총 타임아웃 (초) |
| `LLM_MAX_RETRIES` | `2` | LLM 호출 재시도 횟수 |
| `LLM_CB_FAILURE_THRESHOLD` | `5` | 서킷브레이커 OPEN 조건 (연속 실패 횟수) |
| `LLM_CB_RECOVERY_TIMEOUT` | `60` | HALF_OPEN 회복 대기 (초) |

`.env` 예시:

```dotenv
UPSTAGE_API_KEY=up-...
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...
LANGSMITH_API_KEY=lsv2_...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

```

### 서버 실행

```bash
# 개발 서버 (hot reload)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

```

- 헬스체크: `GET /` → `{"status": "ok"}`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## 프론트엔드 연동

프론트엔드는 별도 Vercel 프로젝트로 배포됩니다 — **[SmartPick-frontend](https://github.com/SmartPick-org/SmartPick-frontend)**

백엔드는 CORS를 모든 오리진 허용(`*`)으로 설정하고 있으므로 추가 설정 없이 어느 도메인에서도 API를 호출할 수 있습니다.

### API 베이스 URL

| 환경 | URL |
|---|---|
| 로컬 개발 | `http://localhost:8000` |
| EC2 (운영) | 배포된 EC2 인스턴스 주소 (GitHub Secrets `EC2_HOST` 참고) |

### ngrok 로컬 터널링

프론트엔드 Vercel에서 로컬 백엔드를 테스트할 때 ngrok을 사용할 경우, ngrok 브라우저 경고 페이지를 건너뛰기 위해 모든 요청에 다음 헤더를 추가하세요.

```
Ngrok-Skip-Browser-Warning: true
```

---

## 주요 API

전체 명세는 `/docs` (Swagger UI) 또는 `/openapi.json`을 참고하세요.

### 카드 추천

```
POST /api/v1/cards/recommend
```

소비 패턴을 입력하면 혜택 금액 기준으로 카드를 추천합니다.

**요청 예시**:
```json
{
  "total_budget": 500000,
  "top_n": 3,
  "category_spending": {
    "Coffee": { "total": 50000, "cafe": "75%", "bakery": "25%" },
    "Food":   { "total": 300000, "restaurant": "70%", "delivery": "30%" },
    "Shopping": 150000,
    "Traffic": { "total": 100000, "transit": "100%" }
  }
}
```

- `total_budget`: 월 총 사용 예산 (원)
- `category_spending`: 카테고리별 지출. 단순 금액(`150000`) 또는 서브카테고리 비율(`"cafe": "75%"`)로 입력 가능
- `top_n`: 반환할 카드 수 (1~10, 기본값 5)

지원 카테고리: `General` · `Shopping` · `Traffic` · `Food` · `Coffee` · `Cultural` · `Travel` · `Life` · `EduHealth` · `Others`

**응답 주요 필드**:
```json
{
  "recommended_cards": [
    {
      "card_name": "신한카드 Mr.Life",
      "card_company": "신한카드",
      "card_id": "shinhan_mr_life",
      "annual_fee": 15000,
      "minimum_performance": 300000,
      "expected_monthly_benefit": 99000,
      "expected_yearly_benefit": 1188000,
      "category_breakdown": [...],
      "applied_benefits_trace": [
        {
          "benefit_id": "shinhan_mr_life_b_food_restaurant",
          "content": "음식점 10% 할인",
          "category": "Food",
          "sub_category": "restaurant",
          "applied_budget": 210000,
          "yielded_discount": 21000,
          "user_choice": true
        }
      ],
      "explanation": "..."
    }
  ],
  "explanation": "..."
}
```

---

### 카드 비교

```
POST /api/v1/cards/compare
```

현재 보유 카드와 추천 카드의 혜택을 LLM이 비교 설명합니다.

**요청 예시**:
```json
{
  "total_budget": 500000,
  "category_spending": { "Food": 300000, "Coffee": 50000 },
  "current_card_id": "kb_woori_card"
}
```

---

### 수혜 재계산

```
POST /api/v1/cards/recalculate
```

특정 혜택을 제외(체크박스 해제)하고 순위를 재계산합니다. 50ms 이내 응답.

**요청 예시**:
```json
{
  "total_budget": 500000,
  "category_spending": { "Food": 300000 },
  "recommended_cards": [...],
  "excluded_benefit_ids": ["shinhan_mr_life_b_food_restaurant"]
}
```

---

### 혜택 Q&A

```
POST /api/v1/cards/qa
```

추천 결과 원본 JSON을 기반으로 사용자 질문에 LLM이 답변합니다.

```json
{
  "raw_data": "<recommend 응답 JSON 전체를 문자열로>",
  "question": "왜 커피 혜택이 적용되지 않았나요?"
}
```

---

### 카드 목록

```
GET /api/v1/cards
```

전체 카드 카탈로그 반환 (검색·필터·페이징 지원).

---

### 카드 어드바이저

```
POST /api/v1/advisor/ask
```

특정 카드의 상세 정보를 웹 검색 + LLM으로 답변합니다. 결과는 Supabase에 7일간 캐시됩니다.

```json
{
  "card_name": "신한카드 Mr.Life",
  "query_type": "credit_fees"
}
```

지원 `query_type` 목록은 `GET /api/v1/advisor/queries`로 확인하세요.

---

## 데이터 파이프라인

카드 데이터는 아래 순서로 처리한 뒤 Supabase에 업로드합니다.
스크립트는 반드시 **모듈 방식(`python -m`)**으로 실행하세요 (경로 방식은 import 오류 발생).

```bash
# 1. 원본 마크다운 → 구조화 JSON v4
uv run python -m scripts.generate_json_v4

# 2. 구조화 JSON → digest 마크다운 (LLM 프롬프트용 요약)
uv run python -m scripts.generate_digest

# 3. Supabase DB/Storage 업로드
uv run python -m scripts.upload_cards_to_db
```

---

## 테스트

```bash
uv run pytest tests/ -v
```

현재 **256개 테스트** 유지. CI(`.github/workflows/test.yml`)에서 PR·push 시 자동 실행되고, 실패 시 PR에 코멘트가 달립니다.

---

## 배포

배포는 GitHub Actions(`.github/workflows/deploy.yml`)가 자동으로 처리합니다.

- **트리거**: `main` 또는 `dev` 브랜치에 push 시
- **방식**: EC2 인스턴스에 SSH 접속 → `git pull` → `uv sync` → `systemctl restart smartpick`
- **서비스명**: `smartpick` (systemd unit)

Docker는 사용하지 않습니다.

### 수동 배포 (긴급 시)

```bash
ssh ubuntu@<EC2_HOST>
cd SmartPick-Neo
git pull
/home/ubuntu/.local/bin/uv sync --no-group dev
sudo systemctl restart smartpick
```

---

## 상수 관리 가이드

| 파일 | 상수 | 의미 |
|---|---|---|
| `app/core/config.py` | `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_CB_*` | LLM 연결·회복력 설정 (`.env`로 오버라이드) |
| `app/tools/Calc_tool.py` | `DEFAULT_FUEL_PRICE_PER_LITER`, `DAYS_PER_MONTH` 등 | 혜택 계산 기준값 (유가, 월 기준일수) |
| `app/services/card_service.py` | `_CONCURRENCY_LIMIT` | asyncio 동시 계산 카드 수 상한 |
| `app/services/advise_service.py` | `_CACHE_TTL_DAYS` | 어드바이저 캐시 유효 기간 |
| `app/core/resilience.py` | `wait_exponential(multiplier, min, max)` | 재시도 백오프 파라미터 |

> **변경 시 참고:** LLM 동작 관련은 `.env` 우선 확인. 계산 로직 관련은 `app/tools/Calc_tool.py` 상단 상수 블록 확인.

---

## 에러 핸들링 & 알림

| 예외 유형 | HTTP 상태 | Discord 알림 |
|---|---|---|
| `SystemException` | 500 | O |
| 미분류 `Exception` | 500 | O |
| `KeyError` | 500 | O (서버 버그로 분류) |
| `BusinessException` (NoCardsFoundError, LLMUnavailableError 등) | 422 | X |
| `ValueError` | 400 | X |
| Pydantic `RequestValidationError` | 422 | X |

모든 요청에 `request_id`(UUID)가 할당되어 로그에 바인딩됩니다. 장애 추적 시 Logtail에서 `request_id`로 검색하세요.

---

## 트러블슈팅

**`uv sync`가 `tokenizers` 빌드 실패로 멈춤**
→ Python 3.14 등 너무 최신 버전의 가상환경을 사용할 때 발생합니다. Python 3.12 또는 3.13을 사용하세요.

**`ModuleNotFoundError: No module named 'app'`**
→ 프로젝트 루트에서 실행해야 합니다. `cd <repo-root>` 후 `uv run ...` 으로 실행하세요.

**`KeyError` 응답 500 + Discord 알림**
→ 사용자 입력 오류가 아니라 서버 버그입니다. 카드 데이터셋의 필수 필드 누락이나 `Calc_tool` 로직 이슈가 주 원인입니다. Logtail에서 `request_id`로 로그를 추적하세요.

**Vercel 프론트엔드 ↔ ngrok 로컬 테스트 시 빈 응답**
→ ngrok 브라우저 경고 페이지가 개입합니다. 프론트엔드 요청 헤더에 `Ngrok-Skip-Browser-Warning: true`를 추가하세요.