from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.core.database import fetch_markdown_from_s3, get_supabase
from app.core.discord import notify_discord


class ManualRepository:
    """cards 테이블에서 manual_file_path를 조회하고 Supabase Storage에서 카드 상품 설명서를 로드합니다.
    Storage 실패 시 datasets/manuals/{card_slug}.md 로컬 파일로 폴백합니다.
    문서가 없으면 빈 문자열을 반환합니다 (약관과 달리 필수 항목이 아닐 수 있음)."""

    def __init__(self, manuals_dir: Path):
        self.manuals_dir = manuals_dir

    async def get_manual(self, card_name: str) -> str:
        card_slug: str = ""
        file_path: str = ""

        # 1) DB lookup — get both manual_file_path and card_slug in one query
        try:
            supabase = get_supabase()
            response = (
                supabase.table("cards")
                .select("manual_file_path, card_slug")
                .eq("card_name", card_name)
                .single()
                .execute()
            )
            data = response.data or {}
            file_path = data.get("manual_file_path", "")
            card_slug = data.get("card_slug", "")
        except Exception as exc:
            logger.warning(
                "[ManualRepository] DB 조회 실패, 로컬 파일로 폴백 | card={} | error={}",
                card_name, exc,
            )
            await notify_discord(exc, context=f"ManualRepository.get_manual — DB lookup | card={card_name}")

        # 2) Supabase Storage download
        if file_path:
            try:
                content = fetch_markdown_from_s3(file_path)
                if content:
                    logger.info(
                        "[ManualRepository] 상품설명서 로드 완료 | card={} | path={} | {} chars",
                        card_name, file_path, len(content),
                    )
                    return content
            except Exception as exc:
                logger.warning(
                    "[ManualRepository] storage 다운로드 실패, 로컬 파일로 폴백 | path={} | error={}",
                    file_path, exc,
                )
                await notify_discord(
                    exc,
                    context=f"ManualRepository.get_manual — storage download | card={card_name} path={file_path}",
                )

        # 3) Local fallback: datasets/manuals/{card_slug}.md
        slug = card_slug or card_name
        local_file = self.manuals_dir / f"{slug}.md"
        if local_file.exists():
            logger.info(
                "[ManualRepository] 로컬 파일에서 상품설명서 로드 성공 | card={} | file={}",
                card_name, local_file.name,
            )
            return local_file.read_text(encoding="utf-8")

        # 4) Not found — return empty (manual may not exist for all cards)
        logger.info(
            "[ManualRepository] 상품설명서 없음 | card={} | slug={}",
            card_name, slug,
        )
        return ""
