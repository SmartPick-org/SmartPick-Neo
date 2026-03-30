# SmartPick

SmartPick은 신용카드 추천을 위한 통합 프로젝트입니다. 크롤러로 원천 데이터를 수집하고,
청크/임베딩 파이프라인으로 벡터 DB를 구축한 뒤, 에이전트와 API를 통해 추천 결과를 제공합니다.

## 프로젝트 원칙

- Python 의존성은 루트 `pyproject.toml` 하나로 관리합니다.
- 잠금 파일은 루트 `uv.lock` 하나만 사용합니다.
- 백엔드 실행은 반드시 루트에서 모듈 방식(`python -m`)으로 실행합니다.

## 사전 준비

- Python 3.12
- `uv`
- Node.js 20+ (프론트 개발 시)

루트에서 의존성을 설치합니다.

```bash
uv sync
```

## 환경 변수 설정

`apps/backend/.env` 파일을 만들고 아래 값을 설정하세요.

```env
UPSTAGE_API_KEY=your_upstage_api_key
UPSTAGE_EMBEDDING_MODEL=embedding-query
CORS_ALLOW_ORIGINS=http://localhost:3000
LANGSMITH_API_KEY=your_langsmith_api_key
```

필수 값은 `UPSTAGE_API_KEY`입니다.

## 실행 순서 (중요)

에이전트는 벡터 DB를 전제로 동작하므로, 아래 순서를 반드시 지켜야 합니다.

1. 크롤링
2. 청크/임베딩 파이프라인
3. 에이전트 또는 API 실행

```bash
# 1) 브라우저 설치 (최초 1회)
uv run playwright install chromium

# 2) 크롤링
uv run python -m apps.backend.crawler.main

# 3) 청크 + 임베딩
uv run python -m apps.backend.chunker.cli

# 4) 에이전트 테스트 실행
uv run python -m apps.backend.agent.agent
```

## API 실행

```bash
uv run uvicorn apps.backend.main:app --reload --host 0.0.0.0 --port 8000
```

헬스체크: `GET /health`

## 프론트엔드 실행

```bash
cd apps/frontend
npm ci
npm run dev
```

`apps/frontend/.env` 예시:

```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## 자주 발생하는 실행 오류

- `uv run ./apps/backend/agent/agent.py`처럼 스크립트 경로로 실행하면 import 오류가 발생할 수 있습니다.
- 반드시 `uv run python -m apps.backend.agent.agent`처럼 모듈 방식으로 실행하세요.
