"""Tests for DigestRepository — local fallback and Supabase path."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.digest_repo import DigestRepository


def _card(card_id: str = "hyundai_z_family", card_name: str = "현대카드 Z family", company: str = "현대카드") -> dict:
    return {"card_meta": {"card_id": card_id, "card_name": card_name, "card_company": company}}


def _make_local_digest(tmp_path: Path, subfolder: str = "manual", filename: str = "hyundai_z_family.md", content: str = "# Digest") -> Path:
    """Create a digest dir matching the real nested layout: digest/{company}/{subfolder}/{filename}."""
    digest_dir = tmp_path / "digest"
    md_file = digest_dir / "hyundai" / subfolder / filename
    md_file.parent.mkdir(parents=True)
    md_file.write_text(content, encoding="utf-8")
    return digest_dir


# ---------------------------------------------------------------------------
# Local fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_fallback_finds_file_in_subdirectory(tmp_path):
    """Recursive glob finds .md files nested inside manual/ subdir."""
    digest_dir = _make_local_digest(tmp_path, content="# Z Family")
    repo = DigestRepository(digest_dir)

    with patch("app.repositories.digest_repo._USE_SUPABASE", False), \
         patch("app.core.discord.notify_discord", new=AsyncMock()):
        result = await repo.get_digest(_card())

    assert result == "# Z Family"


@pytest.mark.asyncio
async def test_local_fallback_finds_file_in_alternative_subfolder(tmp_path):
    """Works regardless of the subfolder name (manuals/, new/, etc.)."""
    digest_dir = _make_local_digest(tmp_path, subfolder="new", content="# New Digest")
    repo = DigestRepository(digest_dir)

    with patch("app.repositories.digest_repo._USE_SUPABASE", False), \
         patch("app.core.discord.notify_discord", new=AsyncMock()):
        result = await repo.get_digest(_card())

    assert result == "# New Digest"


@pytest.mark.asyncio
async def test_local_fallback_not_found_returns_graceful_string(tmp_path):
    """Returns a fallback placeholder string (does not raise) when file is missing."""
    digest_dir = tmp_path / "digest"
    (digest_dir / "hyundai").mkdir(parents=True)
    repo = DigestRepository(digest_dir)

    with patch("app.repositories.digest_repo._USE_SUPABASE", False), \
         patch("app.core.discord.notify_discord", new=AsyncMock()):
        result = await repo.get_digest(_card(card_id="hyundai_ghost", card_name="현대카드 유령"))

    assert "digest 파일 없음" in result


@pytest.mark.asyncio
async def test_local_fallback_unknown_company_returns_graceful_string(tmp_path):
    """Cards from unmapped companies return the fallback string without raising."""
    repo = DigestRepository(tmp_path)

    with patch("app.repositories.digest_repo._USE_SUPABASE", False), \
         patch("app.core.discord.notify_discord", new=AsyncMock()):
        result = await repo.get_digest(_card(company="알수없는카드사"))

    assert "digest 파일 없음" in result


# ---------------------------------------------------------------------------
# Supabase path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_supabase_success_returns_content_without_local_read(tmp_path):
    """When Supabase storage returns content, local files are never accessed."""
    repo = DigestRepository(tmp_path)

    mock_supabase = MagicMock()
    (
        mock_supabase.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
        .data
    ) = {"digest_file_path": "digest/hyundai_z_family.md"}

    with patch("app.repositories.digest_repo._USE_SUPABASE", True), \
         patch("app.core.database.get_supabase", return_value=mock_supabase), \
         patch("app.core.database.fetch_markdown_from_s3", return_value="supabase content"):
        result = await repo.get_digest(_card())

    assert result == "supabase content"


@pytest.mark.asyncio
async def test_supabase_failure_falls_back_to_local(tmp_path):
    """If Supabase raises, local file is still found and returned."""
    digest_dir = _make_local_digest(tmp_path, content="local fallback content")
    repo = DigestRepository(digest_dir)

    with patch("app.repositories.digest_repo._USE_SUPABASE", True), \
         patch("app.core.database.get_supabase", side_effect=RuntimeError("db down")), \
         patch("app.core.discord.notify_discord", new=AsyncMock()):
        result = await repo.get_digest(_card())

    assert result == "local fallback content"


@pytest.mark.asyncio
async def test_supabase_empty_file_path_falls_back_to_local(tmp_path):
    """If DB row has no digest_file_path, local fallback is used."""
    digest_dir = _make_local_digest(tmp_path, content="local content")
    repo = DigestRepository(digest_dir)

    mock_supabase = MagicMock()
    (
        mock_supabase.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
        .data
    ) = {"digest_file_path": ""}

    with patch("app.repositories.digest_repo._USE_SUPABASE", True), \
         patch("app.core.database.get_supabase", return_value=mock_supabase), \
         patch("app.core.database.fetch_markdown_from_s3", return_value=""):
        result = await repo.get_digest(_card())

    assert result == "local content"