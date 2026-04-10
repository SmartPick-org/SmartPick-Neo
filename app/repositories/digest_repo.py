from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from app.domain.models import CardData

# Supabase: 환경변수가 없으면 사용 안 함
_USE_SUPABASE = bool(os.environ.get("SUPABASE_URL"))

_COMPANY_DIR_MAP: dict[str, str] = {
    "KB국민카드": "kb",
    "신한카드": "shinhan",
    "현대카드": "hyundai",
}


class DigestRepository:
    def __init__(self, digest_dir: Path):
        self.digest_dir = digest_dir

    async def get_digest(self, card: CardData) -> str:
        from app.core.discord import notify_discord

        card_meta = card.get("card_meta", {})
        card_id = card_meta.get("card_id", "")
        company = card_meta.get("card_company", "")
        card_name = card_meta.get("card_name", "알 수 없음")

        logger.info(
            "[DigestRepository] explain 서비스 digest 조회 시작 | card={} | company={} | card_id={}",
            card_name, company, card_id,
        )

        # 1) Supabase DB lookup → Storage download (primary)
        if _USE_SUPABASE:
            try:
                from app.core.database import fetch_markdown_from_s3, get_supabase
                supabase = get_supabase()
                response = (
                    supabase.table("cards")
                    .select("digest_file_path")
                    .eq("card_name", card_name)
                    .single()
                    .execute()
                )
                file_path: str = (response.data or {}).get("digest_file_path", "")
                if file_path:
                    content = fetch_markdown_from_s3(file_path)
                    if content:
                        logger.info(
                            "[DigestRepository] Supabase storage에서 digest 로드 성공 | card={} | path={}",
                            card_name, file_path,
                        )
                        return content
            except Exception as exc:
                logger.warning(
                    "[DigestRepository] Supabase 조회 실패, 로컬 파일로 폴백 | card={} | error={}",
                    card_name, repr(exc),
                )

        # 2) Local file fallback
        company_dir = _COMPANY_DIR_MAP.get(company, "")
        if company_dir:
            local_dir = self.digest_dir / company_dir
            if local_dir.exists():
                for md_file in local_dir.glob("*.md"):
                    if card_id.replace("_", "") in md_file.stem.replace("_", "").replace(" ", "").lower():
                        logger.info(
                            "[DigestRepository] 로컬 파일에서 digest 로드 성공 | card={} | file={}",
                            card_name, md_file.name,
                        )
                        return md_file.read_text(encoding="utf-8")

        # 3) Not found
        exc = RuntimeError(f"digest 파일을 찾을 수 없음: {card_name} (card_id={card_id})")
        logger.error("[DigestRepository] {}", exc)
        await notify_discord(exc, context=f"DigestRepository.get_digest — file not found | card={card_name} | card_id={card_id}")
        return f"# {card_name}\n(digest 파일 없음)"
