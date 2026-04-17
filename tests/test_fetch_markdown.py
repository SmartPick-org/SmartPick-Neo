"""Tests for fetch_markdown_from_s3 — flat 버킷 구조 기준.

현재 fetch_markdown_from_s3 는 file_path 의 첫 세그먼트를 **버킷 이름** 으로
사용한다. BUCKET_MAP 에 "Digest"·"Manuals"·"Terms" 세 개만 등록돼 있다 (대문자 시작).
버킷 내부는 모두 flat 구조 — 회사별 서브폴더 자동 삽입 없음.

(이전의 소문자 prefix + 회사 폴더 삽입 가정은 커밋 2d6633b "fix: Storage 버킷
경로 수정 및 파일 조회 로그 개선" 에서 제거됨.)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_storage(content: bytes = b"# content") -> MagicMock:
    """Build a mock Supabase storage client returning content on any download call."""
    mock = MagicMock()
    bucket = mock.storage.from_.return_value
    bucket.download.return_value = content
    return mock


# ---------------------------------------------------------------------------
# Bucket routing — 첫 세그먼트가 버킷 이름
# ---------------------------------------------------------------------------

def test_digest_path_downloads_from_digest_bucket_flat():
    """Digest/hyundai_x.md → bucket 'Digest' 에서 'hyundai_x.md' 다운로드."""
    mock_client = _mock_storage(b"# digest content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Digest/hyundai_x.md")

    assert result == "# digest content"
    mock_client.storage.from_.assert_called_with("Digest")
    mock_client.storage.from_.return_value.download.assert_called_with("hyundai_x.md")


def test_terms_path_downloads_from_terms_bucket_flat():
    """Terms/foo.md → bucket 'Terms' 에서 'foo.md' 다운로드."""
    mock_client = _mock_storage(b"# terms content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Terms/hyundai_z_family.md")

    assert result == "# terms content"
    mock_client.storage.from_.assert_called_with("Terms")
    mock_client.storage.from_.return_value.download.assert_called_with("hyundai_z_family.md")


def test_manual_path_downloads_from_manuals_bucket_flat():
    """Manuals/foo.md → bucket 'Manuals' 에서 'foo.md' 다운로드."""
    mock_client = _mock_storage(b"# manual content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Manuals/hyundai_x.md")

    assert result == "# manual content"
    mock_client.storage.from_.assert_called_with("Manuals")
    mock_client.storage.from_.return_value.download.assert_called_with("hyundai_x.md")


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

def test_empty_file_path_returns_empty_string():
    from app.core.database import fetch_markdown_from_s3
    assert fetch_markdown_from_s3("") == ""


def test_unknown_prefix_returns_empty_string():
    """BUCKET_MAP에 없는 prefix (예: 소문자 'digest', 오타 'unknown') 는 빈 문자열 반환."""
    mock_client = MagicMock()
    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        assert fetch_markdown_from_s3("unknown/foo.md") == ""
        # 소문자 prefix 는 현재 허용되지 않음 (회귀 방지)
        assert fetch_markdown_from_s3("digest/foo.md") == ""


def test_no_storage_client_returns_empty_string():
    with patch("app.core.database._storage_client", None):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Terms/foo.md")
    assert result == ""


# ---------------------------------------------------------------------------
# Case-insensitive fallback
# ---------------------------------------------------------------------------

def test_case_insensitive_fallback_matches_file():
    """첫 download 가 실패하면 같은 폴더를 list 해서 대소문자 다른 파일로 재시도."""
    mock_client = MagicMock()
    bucket = mock_client.storage.from_.return_value

    # 첫 download (exact) 실패 → list 결과로 실제 파일명 찾아 재시도
    bucket.download.side_effect = [Exception("not found"), b"# found via fallback"]
    bucket.list.return_value = [{"name": "Hyundai_X.md"}]

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Digest/hyundai_x.md")

    assert result == "# found via fallback"
    # 두 번째 download 는 실제 대소문자로 수정된 파일명 사용
    assert bucket.download.call_args[0][0] == "Hyundai_X.md"


def test_case_insensitive_fallback_no_match_returns_empty():
    """폴더 리스팅에서 매칭되는 파일명이 없으면 빈 문자열 반환."""
    mock_client = MagicMock()
    bucket = mock_client.storage.from_.return_value
    bucket.download.side_effect = Exception("not found")
    bucket.list.return_value = [{"name": "completely_different.md"}]

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("Digest/hyundai_x.md")

    assert result == ""
