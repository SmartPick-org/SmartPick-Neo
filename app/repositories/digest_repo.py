from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from app.domain.models import CardData

_USE_SUPABASE = bool(os.environ.get("SUPABASE_URL"))


class DigestRepository:
    def __init__(self, digest_dir: Path):
        self.digest_dir = digest_dir

    async def get_digest(self, card: CardData) -> str:
        from app.core.discord import notify_discord

        card_meta = card.get("card_meta", {})
        card_slug = card_meta.get("card_slug", "")
        card_name = card_meta.get("card_name", "알 수 없음")

        logger.info(
            "[DigestRepository] digest 조회 시작 | card={} | slug={}",
            card_name, card_slug,
        )

        # 1) Supabase DB lookup → Storage download (primary)
        if _USE_SUPABASE and card_slug:
            try:
                from app.core.database import fetch_markdown_from_s3, get_supabase
                supabase = get_supabase()
                response = (
                    supabase.table("cards")
                    .select("digest_file_path")
                    .eq("card_slug", card_slug)
                    .single()
                    .execute()
                )
                file_path: str = (response.data or {}).get("digest_file_path", "")
                if not file_path:
                    logger.info(
                        "[DigestRepository] DB에 digest_file_path 없음, 로컬 파일로 폴백 | card={} | slug={}",
                        card_name, card_slug,
                    )
                else:
                    logger.info(
                        "[DigestRepository] Storage 다운로드 시도 | card={} | path={}",
                        card_name, file_path,
                    )
                    content = fetch_markdown_from_s3(file_path)
                    if content:
                        logger.info(
                            "[DigestRepository] Storage에서 digest 로드 성공 | card={} | path={} | {} chars",
                            card_name, file_path, len(content),
                        )
                        return content
                    logger.warning(
                        "[DigestRepository] Storage 다운로드 결과 없음, 로컬 파일로 폴백 | card={} | path={}",
                        card_name, file_path,
                    )
            except Exception as exc:
                logger.warning(
                    "[DigestRepository] Supabase 조회 실패, 로컬 파일로 폴백 | card={} | error={}",
                    card_name, repr(exc),
                )

        # 2) Local file fallback: search recursively (digest_v4 uses company subfolders)
        if card_slug:
            logger.info(
                "[DigestRepository] 로컬 파일 검색 | dir={} | pattern={}.md",
                self.digest_dir, card_slug,
            )
            matches = list(self.digest_dir.rglob(f"{card_slug}.md"))
            if matches:
                local_file = matches[0]
                logger.info(
                    "[DigestRepository] 로컬 파일 로드 성공 | card={} | path={}",
                    card_name, local_file,
                )
                return local_file.read_text(encoding="utf-8")
            logger.warning(
                "[DigestRepository] 로컬 파일 없음 | card={} | dir={} | slug={}.md",
                card_name, self.digest_dir, card_slug,
            )

        # 3) Not found
        exc = RuntimeError(f"digest 파일을 찾을 수 없음: {card_name} (slug={card_slug})")
        logger.error("[DigestRepository] {}", exc)
        await notify_discord(
            exc,
            context=f"DigestRepository.get_digest — file not found | card={card_name} | slug={card_slug}",
        )
        return f"# {card_name}\n(digest 파일 없음)"
