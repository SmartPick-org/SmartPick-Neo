"""Supabase 클라이언트 설정 및 Storage 헬퍼.

Mk2 → Neo 이식:
  - anon 클라이언트: DB 쿼리용 (SUPABASE_KEY)
  - service_role 클라이언트: private 버킷 접근용 (SUPABASE_SERVICE_KEY)
  - fetch_markdown_from_s3: Storage 에서 마크다운 파일 다운로드
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from supabase import Client, create_client

# 프로젝트 루트의 .env 로드
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=_env_path)

_url: str = os.environ.get("SUPABASE_URL", "")
_key: str = os.environ.get("SUPABASE_KEY", "")
_service_key: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not _url or not _key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

# DB 쿼리용 anon 클라이언트 (singleton)
supabase: Client = create_client(_url, _key)

# Storage 전용 service_role 클라이언트 (private 버킷 접근용)
# service_key 가 없으면 anon 클라이언트로 fallback
_storage_client: Client = create_client(_url, _service_key) if _service_key else supabase


def get_supabase() -> Client:
    """FastAPI Depends 등에서 사용할 DB 클라이언트 반환."""
    return supabase


# ---------------------------------------------------------------------------
# 버킷 매핑 (DB 경로 prefix → Supabase Storage 버킷 이름)
# ---------------------------------------------------------------------------
BUCKET_MAP: dict[str, str] = {
    "digest": "Digest",
    "manual": "Markdown",
    "terms": "Markdown",
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

    버킷 구조:
      - Markdown 버킷: manual/{filename}.md  ← DB 경로 그대로 사용
      - Digest   버킷: {company}/{filename}.md ← DB는 digest/{filename}.md 형태로 저장
                                               실제 버킷 경로는 {company}/{filename}
    """
    if not file_path:
        return ""

    prefix = file_path.split("/")[0]    # 'manual' or 'digest'
    filename = file_path.split("/")[-1] # 예: hyundai_DigitalLover.md
    bucket_name = BUCKET_MAP.get(prefix)

    if not bucket_name:
        print(f"[WARN] Unknown file path prefix '{prefix}' in: {file_path}")
        return ""

    if prefix in ("manual", "terms"):
        bucket_path = file_path
    else:
        # Digest 버킷: {company}/{filename} 으로 변환
        company_key = filename.split("_")[0]
        company_folder = DIGEST_COMPANY_FOLDER_MAP.get(company_key)
        if not company_folder:
            print(f"[WARN] Unknown company key '{company_key}' from file: {filename}")
            return ""
        bucket_path = f"{company_folder}/{filename}"

    try:
        res = _storage_client.storage.from_(bucket_name).download(bucket_path)
        return res.decode("utf-8")
    except Exception:
        # 대소문자 무시 fallback
        folder = bucket_path.rsplit("/", 1)[0]
        target_name = bucket_path.rsplit("/", 1)[-1].lower()
        try:
            files = _storage_client.storage.from_(bucket_name).list(folder)
            matched = next(
                (f["name"] for f in files if f["name"].lower() == target_name),
                None,
            )
            if matched:
                actual_path = f"{folder}/{matched}"
                res = _storage_client.storage.from_(bucket_name).download(actual_path)
                return res.decode("utf-8")
        except Exception:
            pass
        print(
            f"[ERROR] File not found: '{bucket_path}' in bucket '{bucket_name}'"
            " (case-insensitive fallback also failed)"
        )
        return ""
