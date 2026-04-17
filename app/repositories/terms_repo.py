from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.core.database import fetch_markdown_from_s3, get_supabase
from app.core.discord import notify_discord


class TermsRepository:
    """cards 테이블에서 terms_file_path를 조회하고 Supabase Storage에서 약관 마크다운을 로드합니다.
    Storage 실패 시 datasets/terms/{card_slug}.md 로컬 파일로 폴백합니다."""

    def __init__(self, terms_dir: Path):
        self.terms_dir = terms_dir

    async def get_terms(self, card_name: str) -> str:
        card_slug: str = ""
        file_path: str = ""

        # 1) DB lookup — get both terms_file_path and card_slug in one query
        logger.info("[TermsRepository] DB 조회 시작 | card={}", card_name)
        try:
            supabase = get_supabase()
            response = (
                supabase.table("cards")
                .select("terms_file_path, card_slug")
                .eq("card_name", card_name)
                .single()
                .execute()
            )
            data = response.data or {}
            file_path = data.get("terms_file_path", "")
            card_slug = data.get("card_slug", "")
            logger.info(
                "[TermsRepository] DB 조회 완료 | card={} | slug={} | terms_file_path={}",
                card_name, card_slug, file_path or "(없음)",
            )
        except Exception as exc:
            logger.warning(
                "[TermsRepository] DB 조회 실패, 로컬 파일로 폴백 | card={} | error={}",
                card_name, exc,
            )
            await notify_discord(exc, context=f"TermsRepository.get_terms — DB lookup | card={card_name}")

        # 2) Supabase Storage download
        if file_path:
            logger.info("[TermsRepository] Storage 다운로드 시도 | card={} | path={}", card_name, file_path)
            try:
                content = fetch_markdown_from_s3(file_path)
                if content:
                    logger.info(
                        "[TermsRepository] Storage에서 약관 로드 성공 | card={} | path={} | {} chars",
                        card_name, file_path, len(content),
                    )
                    return content
                logger.warning(
                    "[TermsRepository] Storage 다운로드 결과 없음, 로컬 파일로 폴백 | card={} | path={}",
                    card_name, file_path,
                )
            except Exception as exc:
                logger.warning(
                    "[TermsRepository] Storage 다운로드 실패, 로컬 파일로 폴백 | path={} | error={}",
                    file_path, exc,
                )
                await notify_discord(
                    exc,
                    context=f"TermsRepository.get_terms — storage download | card={card_name} path={file_path}",
                )
        else:
            logger.info("[TermsRepository] terms_file_path 없음, 로컬 파일로 폴백 | card={}", card_name)

        # 3) Local fallback: datasets/terms/{card_slug}.md
        slug = card_slug or card_name
        local_file = self.terms_dir / f"{slug}.md"
        logger.info("[TermsRepository] 로컬 파일 확인 | card={} | path={}", card_name, local_file)
        if local_file.exists():
            logger.info(
                "[TermsRepository] 로컬 파일 로드 성공 | card={} | path={}",
                card_name, local_file,
            )
            return local_file.read_text(encoding="utf-8")

        # 4) Not found
        logger.warning(
            "[TermsRepository] 약관 없음 — DB에도 로컬에도 파일 없음 | card={} | slug={} | 시도한 경로={}",
            card_name, slug, local_file,
        )
        return ""
