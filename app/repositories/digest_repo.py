from __future__ import annotations

import os
from pathlib import Path

from app.domain.models import CardData

# Supabase Storage fallback: 환경변수가 없으면 사용 안 함
_USE_SUPABASE = bool(os.environ.get("SUPABASE_URL"))

_COMPANY_DIR_MAP: dict[str, str] = {
    "KB국민카드": "kb",
    "신한카드": "shinhan",
    "현대카드": "hyundai",
}

# Supabase Storage 경로용 회사 prefix 매핑
_COMPANY_BUCKET_PREFIX: dict[str, str] = {
    "KB국민카드": "kb",
    "신한카드": "shinhan",
    "현대카드": "hyundai",
}


class DigestRepository:
    def __init__(self, digest_dir: Path):
        self.digest_dir = digest_dir

    def get_digest(self, card: CardData) -> str:
        card_meta = card.get("card_meta", {})
        card_id = card_meta.get("card_id", "")
        company = card_meta.get("card_company", "")
        card_name = card_meta.get("card_name", "알 수 없음")

        # 1) 로컬 파일 우선 탐색
        company_dir = _COMPANY_DIR_MAP.get(company, "")
        if company_dir:
            local_dir = self.digest_dir / company_dir
            if local_dir.exists():
                for md_file in local_dir.glob("*.md"):
                    if card_id.replace("_", "") in md_file.stem.replace("_", "").replace(" ", "").lower():
                        return md_file.read_text(encoding="utf-8")

        # 2) Supabase Storage fallback
        if _USE_SUPABASE and company_dir:
            from app.core.database import fetch_markdown_from_s3  # lazy import

            # Digest 버킷 경로: digest/{company_prefix}_{card_id}.md (추정)
            # DB에 file_path 필드가 있으면 그것을 사용
            file_path: str = card_meta.get("file_path", "") or card.get("file_path", "")
            if file_path:
                content = fetch_markdown_from_s3(file_path)
                if content:
                    return content

        return f"# {card_name}\n(digest 파일 없음)"
