"""
Discord Webhook 알림 모듈

SystemException 또는 미분류 예외 발생 시 Discord 채널로 알림을 전송합니다.
Discord Embed 형식으로 보기 좋게 포맷됩니다.

사용법:
    await notify_discord(exc, context="POST /cards/recommend")

환경변수:
    DISCORD_WEBHOOK_URL: Discord 채널 Webhook URL
    (없으면 조용히 skip — 로컬 개발 환경에서 에러 안 남)
"""

from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone

import httpx
from loguru import logger

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Discord Embed 색상 (빨간색 = 에러)
_COLOR_ERROR = 0xE53935


async def notify_discord(exc: Exception, context: str = "") -> None:
    """
    시스템 예외 발생 시 Discord Embed 메시지로 알림 전송.

    Args:
        exc: 발생한 예외 객체
        context: 에러가 발생한 요청 맥락 (예: "POST /cards/recommend")
    """
    if not DISCORD_WEBHOOK_URL:
        # 로컬/테스트 환경에서는 조용히 skip
        return

    tb = traceback.format_exc()
    # Discord Embed의 field value는 최대 1024자
    tb_truncated = tb[-1000:] if len(tb) > 1000 else tb

    payload = {
        "username": "SmartPick-Neo 에러 봇",
        "embeds": [
            {
                "title": "🚨 시스템 에러 발생",
                "color": _COLOR_ERROR,
                "fields": [
                    {
                        "name": "📍 발생 위치",
                        "value": f"`{context}`" if context else "알 수 없음",
                        "inline": True,
                    },
                    {
                        "name": "❗ 예외 종류",
                        "value": f"`{type(exc).__name__}`",
                        "inline": True,
                    },
                    {
                        "name": "💬 메시지",
                        "value": str(exc) or "메시지 없음",
                        "inline": False,
                    },
                    {
                        "name": "📋 Traceback",
                        "value": f"```\n{tb_truncated}\n```",
                        "inline": False,
                    },
                ],
                "footer": {
                    "text": f"SmartPick-Neo • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                },
            }
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=5.0,
            )
            if res.status_code not in (200, 204):
                logger.warning(
                    "Discord 알림 전송 실패 — status={} body={}",
                    res.status_code,
                    res.text[:200],
                )
    except Exception as notify_err:
        # 알림 실패 자체가 앱을 죽이면 절대 안 됨
        logger.warning("Discord 알림 전송 중 예외 발생: {}", repr(notify_err))
