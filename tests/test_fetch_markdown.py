"""Tests for fetch_markdown_from_s3 — path routing, bucket mapping, case-insensitive fallback."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _mock_storage(content: bytes = b"# content", raise_on_first: bool = False) -> MagicMock:
    """Build a mock Supabase storage client."""
    mock = MagicMock()
    bucket = mock.storage.from_.return_value
    if raise_on_first:
        bucket.download.side_effect = [Exception("not found"), content]
    else:
        bucket.download.return_value = content
    return mock


# ---------------------------------------------------------------------------
# Path routing
# ---------------------------------------------------------------------------

def test_digest_path_converted_to_company_folder():
    """digest/hyundai_x.md → downloads from hyundai/hyundai_x.md in Digest bucket."""
    mock_client = _mock_storage(b"# digest content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("digest/hyundai_x.md")

    assert result == "# digest content"
    mock_client.storage.from_.assert_called_with("Digest")
    mock_client.storage.from_.return_value.download.assert_called_with("hyundai/hyundai_x.md")


def test_terms_path_used_as_is():
    """terms/foo.md → downloads from terms/foo.md in Markdown bucket."""
    mock_client = _mock_storage(b"# terms content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("terms/hyundai_z_family.md")

    assert result == "# terms content"
    mock_client.storage.from_.assert_called_with("Markdown")
    mock_client.storage.from_.return_value.download.assert_called_with("terms/hyundai_z_family.md")


def test_manual_path_used_as_is():
    """manual/foo.md → downloads from manual/foo.md in Markdown bucket."""
    mock_client = _mock_storage(b"# manual content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("manual/hyundai_x.md")

    assert result == "# manual content"
    mock_client.storage.from_.assert_called_with("Markdown")
    mock_client.storage.from_.return_value.download.assert_called_with("manual/hyundai_x.md")


def test_sc_prefix_mapped_to_shinhan_folder():
    """sc_ prefix files are stored in the shinhan/ folder of the Digest bucket."""
    mock_client = _mock_storage(b"# sc content")

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("digest/sc_deep_oil.md")

    assert result == "# sc content"
    mock_client.storage.from_.return_value.download.assert_called_with("shinhan/sc_deep_oil.md")


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

def test_empty_file_path_returns_empty_string():
    from app.core.database import fetch_markdown_from_s3
    assert fetch_markdown_from_s3("") == ""


def test_unknown_prefix_returns_empty_string():
    mock_client = MagicMock()
    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("unknown/foo.md")
    assert result == ""


def test_unknown_company_key_in_digest_returns_empty_string():
    """digest/xxxxxx_card.md with an unrecognised company prefix returns empty."""
    mock_client = MagicMock()
    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("digest/xxxxxx_card.md")
    assert result == ""


def test_no_storage_client_returns_empty_string():
    with patch("app.core.database._storage_client", None):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("terms/foo.md")
    assert result == ""


# ---------------------------------------------------------------------------
# Case-insensitive fallback
# ---------------------------------------------------------------------------

def test_case_insensitive_fallback_matches_file():
    """When exact download fails, lists the folder and retries with the real filename."""
    mock_client = MagicMock()
    bucket = mock_client.storage.from_.return_value

    # First download (exact path) fails; second (corrected case) succeeds
    bucket.download.side_effect = [Exception("not found"), b"# found via fallback"]
    bucket.list.return_value = [{"name": "Hyundai_X.md"}]

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("digest/hyundai_x.md")

    assert result == "# found via fallback"
    # Second download should use the correctly-cased filename
    assert bucket.download.call_args[0][0] == "hyundai/Hyundai_X.md"


def test_case_insensitive_fallback_no_match_returns_empty():
    """Returns empty string when the folder listing has no matching filename."""
    mock_client = MagicMock()
    bucket = mock_client.storage.from_.return_value
    bucket.download.side_effect = Exception("not found")
    bucket.list.return_value = [{"name": "completely_different.md"}]

    with patch("app.core.database._storage_client", mock_client):
        from app.core.database import fetch_markdown_from_s3
        result = fetch_markdown_from_s3("digest/hyundai_x.md")

    assert result == ""