import os
from dotenv import load_dotenv
from supabase import create_client, Client

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=env_path)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
service_key = os.environ.get("SUPABASE_SERVICE_KEY")

if not url or not key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

# DB 쿼리용 anon 클라이언트 (singleton)
supabase: Client = create_client(url, key)

# Storage 전용 service_role 클라이언트 (private 버킷 접근용)
# service_key가 없으면 anon 클라이언트로 fallback
_storage_client: Client = create_client(url, service_key) if service_key else supabase

def get_supabase() -> Client:
    return supabase

# 파일 경로 prefix → 버킷 이름 매핑
# DB에 저장된 경로: digest/xxx.md → Digest 버킷, manual/xxx.md → Markdown 버킷
BUCKET_MAP = {
    "digest": "Digest",
    "manual": "Markdown",
}

# 파일명 prefix → Digest 버킷 내 폴더 매핑
# Digest 버킷 실제 구조: hyundai/hyundai_xxx.md, kb/kb_xxx.md , shinhan/shinhan_xxx.md
DIGEST_COMPANY_FOLDER_MAP = {
    "hyundai": "hyundai",
    "kb": "kb",
    "shinhan": "shinhan",
    "sc": "shinhan",  # sc_ prefix도 shinhan 버킷에
}

def fetch_markdown_from_s3(file_path: str) -> str:
    """Helper to download text/markdown files from Supabase Storage.

    버킷 구조:
      - Markdown 버킷: manual/{filename}.md   <- DB 경로 기준 같은 경로 사용
      - Digest   버킷: {company}/{filename}.md <- DB는 digest/{filename}.md로 저장
                                               하지만 실제 버킷 경로는 {company}/{filename}
    """
    if not file_path:
        return ""

    prefix = file_path.split("/")[0]   # 'manual' or 'digest'
    filename = file_path.split("/")[-1] # 예: hyundai_DigitalLover.md
    bucket_name = BUCKET_MAP.get(prefix)

    if not bucket_name:
        print(f"Unknown file path prefix '{prefix}' in: {file_path}")
        return ""

    if prefix == "manual":
        # Markdown 버킷: 경로 기준 그대로 사용 (manual/hyundai_DigitalLover.md)
        bucket_path = file_path
    else:
        # Digest 버킷: {company}/{filename} 형태로 변환 필요
        company_key = filename.split("_")[0]  # 'hyundai', 'kb', 'shinhan', 'sc'
        company_folder = DIGEST_COMPANY_FOLDER_MAP.get(company_key)
        if not company_folder:
            print(f"Unknown company key '{company_key}' from file: {filename}")
            return ""
        bucket_path = f"{company_folder}/{filename}"

    try:
        res = _storage_client.storage.from_(bucket_name).download(bucket_path)
        return res.decode("utf-8")
    except Exception:
        # 정확한 경로로 실패 시 대소문자 무시 매칭 시도
        folder = bucket_path.rsplit("/", 1)[0]
        target_name = bucket_path.rsplit("/", 1)[-1].lower()
        try:
            files = _storage_client.storage.from_(bucket_name).list(folder)
            matched = next(
                (f["name"] for f in files if f["name"].lower() == target_name),
                None
            )
            if matched:
                actual_path = f"{folder}/{matched}"
                res = _storage_client.storage.from_(bucket_name).download(actual_path)
                return res.decode("utf-8")
        except Exception:
            pass
        print(f"File not found: '{bucket_path}' in bucket '{bucket_name}' (case-insensitive fallback also failed)")
        return ""
