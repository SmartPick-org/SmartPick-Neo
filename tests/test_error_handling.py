"""서버 에러 핸들링 및 Discord 알림 강화에 대한 회귀 테스트.

검증 범위:
1. notify_discord / notify_discord_sync — URL 없을 때 조용히 skip
2. notify_discord_sync — URL 있을 때 httpx.Client POST 호출, 네트워크 장애 격리
3. KeyError 전역 핸들러 — 500 + Discord 알림 호출
4. ValueError 전역 핸들러 — 400 + Discord 알림 없음
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi import Request

from app.core import discord as discord_mod
from app.core.discord import notify_discord, notify_discord_sync


# ---------------------------------------------------------------------------
# notify_discord / notify_discord_sync
# ---------------------------------------------------------------------------

class TestNotifyDiscordSkipWhenNoWebhook:
    """DISCORD_WEBHOOK_URL이 비어 있으면 조용히 skip — 로컬 개발 환경 보호."""

    def test_sync_skips_when_url_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(discord_mod, "DISCORD_WEBHOOK_URL", "")
        # httpx.Client가 호출되지 않아야 함
        with patch("app.core.discord.httpx.Client") as mock_client:
            notify_discord_sync(RuntimeError("boom"), context="test")
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_skips_when_url_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(discord_mod, "DISCORD_WEBHOOK_URL", "")
        with patch("app.core.discord.httpx.AsyncClient") as mock_client:
            await notify_discord(RuntimeError("boom"), context="test")
        mock_client.assert_not_called()


class TestNotifyDiscordPayload:
    """페이로드 구성 검증."""

    def test_payload_includes_context_and_type(self):
        exc = RuntimeError("something bad")
        payload = discord_mod._build_payload(exc, context="POST /recommend")

        assert payload["embeds"][0]["title"] == "🚨 시스템 에러 발생"
        fields = payload["embeds"][0]["fields"]
        field_names = [f["name"] for f in fields]

        assert "📍 발생 위치" in field_names
        assert "❗ 예외 종류" in field_names
        assert "💬 메시지" in field_names
        assert "📋 Traceback" in field_names

    def test_payload_exception_class_name(self):
        payload = discord_mod._build_payload(KeyError("missing_field"), context="ctx")
        type_field = next(
            f for f in payload["embeds"][0]["fields"] if f["name"] == "❗ 예외 종류"
        )
        assert "KeyError" in type_field["value"]


class TestNotifyDiscordSyncSendsRequest:
    """URL이 있으면 httpx.Client로 실제 요청을 보내야 함."""

    def test_sync_posts_to_webhook(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(discord_mod, "DISCORD_WEBHOOK_URL", "https://example.invalid/hook")

        mock_response = MagicMock(status_code=204)
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.core.discord.httpx.Client", return_value=mock_client):
            notify_discord_sync(
                RuntimeError("boom"), context="FallbackCardRepository.list_cards"
            )

        assert mock_client.post.called
        call_kwargs = mock_client.post.call_args
        # 첫 번째 positional arg = URL
        assert call_kwargs[0][0] == "https://example.invalid/hook"
        # payload가 json으로 전달
        assert "json" in call_kwargs[1]
        payload = call_kwargs[1]["json"]
        assert "FallbackCardRepository" in str(payload)

    def test_sync_swallows_network_errors(self, monkeypatch: pytest.MonkeyPatch):
        """알림 실패가 호출자를 죽이면 안 됨."""
        monkeypatch.setattr(discord_mod, "DISCORD_WEBHOOK_URL", "https://example.invalid/hook")

        with patch("app.core.discord.httpx.Client", side_effect=RuntimeError("network")):
            # 예외를 다시 던지지 않고 조용히 반환해야 함
            notify_discord_sync(RuntimeError("boom"), context="ctx")


# ---------------------------------------------------------------------------
# 전역 예외 핸들러 동작 검증
# ---------------------------------------------------------------------------

class TestKeyErrorHandler:
    """KeyError는 서버 버그로 간주 → 500 + Discord 알림."""

    def test_keyerror_returns_500_and_triggers_discord(self, monkeypatch: pytest.MonkeyPatch):
        from app.main import key_error_handler

        # Discord 알림을 mock으로 교체
        mock_notify = AsyncMock()
        monkeypatch.setattr("app.main._notify_error_channels", mock_notify)

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/api/v1/cards/recommend"
        mock_request.headers = {}

        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            key_error_handler(mock_request, KeyError("card_name"))
        )

        assert response.status_code == 500
        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert "unhandled KeyError" in kwargs["context"]


class TestValueErrorHandler:
    """ValueError는 사용자 입력 오류 → 400 + Discord 알림 없음."""

    def test_valueerror_returns_400_without_discord(self, monkeypatch: pytest.MonkeyPatch):
        from app.main import value_error_handler

        mock_notify = AsyncMock()
        monkeypatch.setattr("app.main._notify_error_channels", mock_notify)

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/api/v1/cards/recommend"
        mock_request.headers = {}

        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            value_error_handler(mock_request, ValueError("total_budget must be > 0"))
        )

        assert response.status_code == 400
        # ValueError는 사용자 잘못이므로 알림 안 감
        mock_notify.assert_not_called()
