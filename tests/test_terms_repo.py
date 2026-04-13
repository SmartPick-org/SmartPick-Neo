"""Tests for TermsRepository — Supabase DB lookup and storage download."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.terms_repo import TermsRepository


def _mock_supabase(file_path: str = "terms/hyundai_z_family.md") -> MagicMock:
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
        .data
    ) = {"terms_file_path": file_path}
    return mock


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_terms_success(tmp_path):
    """Returns content when DB has the path and storage returns data."""
    repo = TermsRepository(tmp_path)

    with patch("app.repositories.terms_repo.get_supabase", return_value=_mock_supabase()), \
         patch("app.repositories.terms_repo.fetch_markdown_from_s3", return_value="# 약관 내용"):
        result = await repo.get_terms("현대카드 Z family")

    assert result == "# 약관 내용"


# ---------------------------------------------------------------------------
# DB failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_terms_db_exception_raises_runtime_error(tmp_path):
    """Raises RuntimeError when the Supabase DB query throws and no local file exists."""
    repo = TermsRepository(tmp_path)

    with patch("app.repositories.terms_repo.get_supabase", side_effect=RuntimeError("connection lost")), \
         patch("app.repositories.terms_repo.notify_discord", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="약관 파일을 찾을 수 없음"):
            await repo.get_terms("현대카드 Z family")


@pytest.mark.asyncio
async def test_get_terms_missing_file_path_raises_runtime_error(tmp_path):
    """Raises RuntimeError when terms_file_path is not set and no local file exists."""
    repo = TermsRepository(tmp_path)
    mock_supabase = _mock_supabase(file_path="")

    with patch("app.repositories.terms_repo.get_supabase", return_value=mock_supabase), \
         patch("app.repositories.terms_repo.notify_discord", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="약관 파일을 찾을 수 없음"):
            await repo.get_terms("현대카드 Z family")


# ---------------------------------------------------------------------------
# Storage failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_terms_storage_exception_raises_runtime_error(tmp_path):
    """Raises RuntimeError when storage download throws and no local file exists."""
    repo = TermsRepository(tmp_path)

    with patch("app.repositories.terms_repo.get_supabase", return_value=_mock_supabase()), \
         patch("app.repositories.terms_repo.fetch_markdown_from_s3", side_effect=Exception("network error")), \
         patch("app.repositories.terms_repo.notify_discord", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="약관 파일을 찾을 수 없음"):
            await repo.get_terms("현대카드 Z family")


@pytest.mark.asyncio
async def test_get_terms_empty_content_raises_runtime_error(tmp_path):
    """Raises RuntimeError when storage returns empty content and no local file exists."""
    repo = TermsRepository(tmp_path)

    with patch("app.repositories.terms_repo.get_supabase", return_value=_mock_supabase()), \
         patch("app.repositories.terms_repo.fetch_markdown_from_s3", return_value=""), \
         patch("app.repositories.terms_repo.notify_discord", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="약관 파일을 찾을 수 없음"):
            await repo.get_terms("현대카드 Z family")
