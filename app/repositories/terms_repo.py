from __future__ import annotations

from loguru import logger

from app.core.database import fetch_markdown_from_s3, get_supabase
from app.core.discord import notify_discord


class TermsRepository:
    """cards 테이블에서 terms_file_path를 조회하고 Supabase Storage에서 약관 마크다운을 로드합니다."""

    async def get_terms(self, card_name: str) -> str:
        try:
            supabase = get_supabase()
            response = (
                supabase.table("cards")
                .select("terms_file_path")
                .eq("card_name", card_name)
                .single()
                .execute()
            )
        except Exception as exc:
            logger.error("[TermsRepository] cards 테이블 DB 조회 실패 | card={} | error={}", card_name, exc)
            await notify_discord(exc, context=f"TermsRepository.get_terms — DB lookup | card={card_name}")
            raise RuntimeError(f"카드 정보 DB 조회 실패: {card_name}") from exc

        file_path: str = (response.data or {}).get("terms_file_path", "")
        if not file_path:
            exc = RuntimeError(f"cards 테이블에 '{card_name}' 항목 없음 또는 terms_file_path 미설정")
            logger.error("[TermsRepository] {}", exc)
            await notify_discord(exc, context=f"TermsRepository.get_terms — missing terms_file_path | card={card_name}")
            raise exc

        logger.info("[TermsRepository] Fetching terms markdown from Supabase storage | card={} | path={}", card_name, file_path)

        try:
            content = fetch_markdown_from_s3(file_path)
        except Exception as exc:
            logger.error("[TermsRepository] storage 다운로드 예외 | path={} | error={}", file_path, exc)
            await notify_discord(exc, context=f"TermsRepository.get_terms — storage download | card={card_name} path={file_path}")
            raise RuntimeError(f"Supabase storage 다운로드 실패: {file_path}") from exc

        if not content:
            exc = RuntimeError(f"Supabase storage에서 빈 파일 반환 또는 파일 없음: {file_path}")
            logger.error("[TermsRepository] {}", exc)
            await notify_discord(exc, context=f"TermsRepository.get_terms — empty content | card={card_name} path={file_path}")
            raise exc

        logger.info("[TermsRepository] 약관 로드 완료 | card={} | path={} | {} chars", card_name, file_path, len(content))
        return content