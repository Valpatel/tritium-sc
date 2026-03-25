# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for path parameter sanitization (path_safety.py).

Proves that path traversal attacks are rejected at the utility level
and at every hardened API endpoint.
"""

import pytest
from fastapi import HTTPException

from app.path_safety import sanitize_path_param


class TestSanitizePathParam:
    """Unit tests for the sanitize_path_param utility."""

    # -- Valid inputs that must pass --

    def test_simple_alphanumeric(self):
        assert sanitize_path_param("abc123") == "abc123"

    def test_with_hyphens(self):
        assert sanitize_path_param("my-thumbnail-01") == "my-thumbnail-01"

    def test_with_underscores(self):
        assert sanitize_path_param("backup_2026_03_25") == "backup_2026_03_25"

    def test_with_dots(self):
        assert sanitize_path_param("video.mp4") == "video.mp4"

    def test_date_format(self):
        assert sanitize_path_param("2026-03-25") == "2026-03-25"

    def test_single_char(self):
        assert sanitize_path_param("x") == "x"

    def test_single_digit(self):
        assert sanitize_path_param("0") == "0"

    def test_uuid_like(self):
        val = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert sanitize_path_param(val) == val

    # -- Path traversal attacks that must be rejected --

    def test_double_dot_traversal(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_encoded_double_dot(self):
        """Even literal .. embedded in otherwise valid chars."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("foo..bar")
        assert exc_info.value.status_code == 400

    def test_leading_dot_dot_slash(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("../../etc/shadow")
        assert exc_info.value.status_code == 400

    def test_absolute_path(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("/etc/passwd")
        assert exc_info.value.status_code == 400

    def test_null_byte(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("file\x00.jpg")
        assert exc_info.value.status_code == 400

    def test_empty_string(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("")
        assert exc_info.value.status_code == 400

    def test_slash_in_middle(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("foo/bar")
        assert exc_info.value.status_code == 400

    def test_backslash(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("foo\\bar")
        assert exc_info.value.status_code == 400

    def test_space(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("foo bar")
        assert exc_info.value.status_code == 400

    def test_leading_dot(self):
        """Hidden file / dotfile names are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param(".hidden")
        assert exc_info.value.status_code == 400

    def test_tilde(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("~root")
        assert exc_info.value.status_code == 400

    def test_semicolon(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("a;rm -rf /")
        assert exc_info.value.status_code == 400

    def test_negative_number_string(self):
        """Negative numbers as strings are rejected (hyphen at start is not leading alnum)."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("-5")
        assert exc_info.value.status_code == 400

    def test_error_message_includes_name(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_path_param("../bad", "thumbnail_id")
        assert "thumbnail_id" in exc_info.value.detail


class TestEndpointPathTraversal:
    """Integration tests proving traversal is blocked at the API layer.

    Uses httpx TestClient against real FastAPI routers.
    """

    @pytest.fixture(autouse=True)
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._client = TestClient(app, raise_server_exceptions=False)
        yield

    # -- search.py endpoints --
    # Note: %2F (encoded slash) causes route mismatch (404) at the Starlette
    # level before our handler runs. We test with payloads that reach the
    # handler: ".." sequences, null bytes, and special characters.

    def test_search_thumbnail_dot_dot(self):
        resp = self._client.get("/api/search/thumbnail/..passwd")
        assert resp.status_code == 400

    def test_search_thumbnail_null_byte(self):
        resp = self._client.get("/api/search/thumbnail/file%00.jpg")
        assert resp.status_code == 400

    def test_search_thumbnail_hidden_file(self):
        resp = self._client.get("/api/search/thumbnail/.htaccess")
        assert resp.status_code == 400

    def test_search_thumbnail_special_chars(self):
        resp = self._client.get("/api/search/thumbnail/foo;rm+-rf")
        assert resp.status_code == 400

    def test_search_target_dot_dot(self):
        resp = self._client.get("/api/search/target/..passwd")
        assert resp.status_code == 400

    def test_search_target_hidden_file(self):
        resp = self._client.get("/api/search/target/.env")
        assert resp.status_code == 400

    # -- ai.py endpoints --

    def test_ai_hyperlapse_date_dot_dot(self):
        resp = self._client.get("/api/ai/hyperlapse/1/..2026-03-25/video")
        assert resp.status_code == 400

    def test_ai_hyperlapse_date_hidden(self):
        resp = self._client.get("/api/ai/hyperlapse/1/.secret/video")
        assert resp.status_code == 400

    def test_ai_detect_frame_filename_dot_dot(self):
        resp = self._client.get("/api/ai/detect/frame/1/2026-03-25/..video.mp4")
        assert resp.status_code == 400

    def test_ai_detect_frame_date_dot_dot(self):
        resp = self._client.get("/api/ai/detect/frame/1/..secret/video.mp4")
        assert resp.status_code == 400

    def test_ai_detect_frame_filename_special(self):
        resp = self._client.get("/api/ai/detect/frame/1/2026-03-25/file%00name.mp4")
        assert resp.status_code == 400

    # -- backup.py endpoint --

    def test_backup_download_dot_dot(self):
        resp = self._client.get("/api/backup/download/..passwd")
        # Could be 400 (sanitized) or 401/403 (auth required first)
        assert resp.status_code in (400, 401, 403)

    def test_backup_download_hidden(self):
        resp = self._client.get("/api/backup/download/.env")
        assert resp.status_code in (400, 401, 403)

    # -- recordings.py endpoint --

    def test_recordings_stop_dot_dot(self):
        resp = self._client.post("/api/recordings/stop/..traversal")
        assert resp.status_code == 400

    def test_recordings_stop_hidden(self):
        resp = self._client.post("/api/recordings/stop/.hidden")
        assert resp.status_code == 400

    # -- scenarios.py endpoint --

    def test_scenarios_run_dot_dot(self):
        resp = self._client.get("/api/scenarios/run/..traversal")
        assert resp.status_code == 400

    def test_scenarios_run_hidden(self):
        resp = self._client.get("/api/scenarios/run/.hidden")
        assert resp.status_code == 400

    # -- Valid requests should not be broken --

    def test_search_thumbnail_valid_id_404(self):
        """Valid ID format but non-existent thumbnail returns 404, not 400."""
        resp = self._client.get("/api/search/thumbnail/abc123")
        assert resp.status_code == 404

    def test_search_target_valid_id_404(self):
        """Valid ID format but non-existent target returns 404, not 400."""
        resp = self._client.get("/api/search/target/abc123")
        assert resp.status_code == 404

    def test_scenarios_run_valid_id_404(self):
        """Valid run_id format but non-existent run returns 404, not 400."""
        resp = self._client.get("/api/scenarios/run/abc123")
        assert resp.status_code == 404

    def test_recordings_stop_valid_id_404(self):
        """Valid recording_id format but non-existent recording returns 404, not 400."""
        resp = self._client.post("/api/recordings/stop/abc123")
        assert resp.status_code == 404
