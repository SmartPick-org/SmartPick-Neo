"""Supabase 클라이언트 설정 및 Storage 헬퍼.

Mk2 → Neo 이식:
  - anon 클라이언트: DB 쿼리용 (SUPABASE_KEY)
  - service_role 클라이언트: private 버킷 접근용 (SUPABASE_SERVICE_KEY)
  - fetch_markdown_from_s3: Storage 에서 마크다운 파일 다운로드
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from loguru import logger
from supabase import Client, create_client

# 프로젝트 루트의 .env 로드
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=_env_path)

_url: str = os.environ.get("SUPABASE_URL", "")
_key: str = os.environ.get("SUPABASE_KEY", "")
_service_key: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

supabase: Client | None = None
_storage_client: Client | None = None

if _url and _key:
    # DB 쿼리용 anon 클라이언트 (singleton)
    supabase = create_client(_url, _key)

    # Storage 전용 service_role 클라이언트 (private 버킷 접근용)
    # service_key 가 없으면 anon 클라이언트로 fallback
    _storage_client = create_client(_url, _service_key) if _service_key else supabase
else:
    logger.warning("Missing SUPABASE_URL or SUPABASE_KEY in .env. Supabase disabled. Falling back to local mode.")


def get_supabase() -> Client:
    """FastAPI Depends 등에서 사용할 DB 클라이언트 반환."""
    if supabase is None:
        raise RuntimeError("Supabase client is not initialized due to missing environment variables.")
    return supabase


# ---------------------------------------------------------------------------
# 버킷 매핑 (DB 경로 prefix → Supabase Storage 버킷 이름)
# ---------------------------------------------------------------------------
BUCKET_MAP: dict[str, str] = {
    "Digest": "Digest",
    "Manuals": "Manuals",
    "Terms": "Terms",
}

# Digest 버킷 내 회사별 폴더 매핑 (파일명 prefix 기준)
DIGEST_COMPANY_FOLDER_MAP: dict[str, str] = {
    "hyundai": "hyundai",
    "kb": "kb",
    "shinhan": "shinhan",
    "sc": "shinhan",  # sc_ prefix 도 shinhan 폴더에 있음
}


def fetch_markdown_from_s3(file_path: str) -> str:
    """Supabase Storage 에서 마크다운 파일을 다운로드해 문자열로 반환.

    DB에 저장된 file_path 형식: "{Bucket}/{path}" (e.g. "Manuals/kb_youth_talk_talk.md")
    버킷 구조:
      - Manuals 버킷: {filename}.md  (root-level)
      - Terms   버킷: {filename}.md  (root-level)
      - Digest  버킷: {company}/{filename}.md  (company subfolder)
    """
    if not file_path:
        return ""

    if not _storage_client:
        print("[WARN] Supabase storage is disabled due to missing URL/KEY.")
        return ""

    prefix = file_path.split("/")[0]    # e.g. 'Digest', 'Manuals', 'Terms'
    filename = file_path.split("/")[-1] # e.g. 'kb_youth_talk_talk.md'
    bucket_name = BUCKET_MAP.get(prefix)

    if not bucket_name:
        logger.warning("[Storage] 알 수 없는 경로 prefix | prefix={} | file_path={}", prefix, file_path)
        return ""

    if prefix == "Digest":
        # Digest 버킷: {company}/{filename} 경로로 변환
        company_key = filename.split("_")[0]
        company_folder = DIGEST_COMPANY_FOLDER_MAP.get(company_key)
        if not company_folder:
            logger.warning("[Storage] 알 수 없는 회사 key | company_key={} | filename={}", company_key, filename)
            return ""
        bucket_path = f"{company_folder}/{filename}"
    else:
        # Manuals / Terms 버킷: prefix를 제거한 나머지가 버킷 내 경로
        bucket_path = "/".join(file_path.split("/")[1:])

    logger.info("[Storage] 다운로드 시도 | bucket={} | bucket_path={}", bucket_name, bucket_path)
    try:
        res = _storage_client.storage.from_(bucket_name).download(bucket_path)
        content = res.decode("utf-8")
        logger.info("[Storage] 다운로드 성공 | bucket={} | bucket_path={} | {} chars", bucket_name, bucket_path, len(content))
        return content
    except Exception as e:
        logger.warning("[Storage] 다운로드 실패 | bucket={} | bucket_path={} | error={}", bucket_name, bucket_path, e)
        # 대소문자 무시 fallback
        if "/" in bucket_path:
            folder = bucket_path.rsplit("/", 1)[0]
            target_name = bucket_path.rsplit("/", 1)[-1].lower()
        else:
            folder = ""
            target_name = bucket_path.lower()
        logger.info("[Storage] 대소문자 무시 fallback 시도 | bucket={} | folder='{}' | target={}", bucket_name, folder, target_name)
        try:
            files = _storage_client.storage.from_(bucket_name).list(folder)
            matched = next(
                (f["name"] for f in files if f["name"].lower() == target_name),
                None,
            )
            if matched:
                actual_path = f"{folder}/{matched}" if folder else matched
                logger.info("[Storage] 대소문자 무시 매칭 성공 | actual_path={}", actual_path)
                res = _storage_client.storage.from_(bucket_name).download(actual_path)
                return res.decode("utf-8")
            logger.warning("[Storage] 대소문자 무시 fallback 매칭 없음 | bucket={} | folder='{}' | target={}", bucket_name, folder, target_name)
        except Exception as e2:
            logger.warning("[Storage] 대소문자 무시 fallback 실패 | bucket={} | error={}", bucket_name, e2)
        return ""
