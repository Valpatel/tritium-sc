# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for audit logging middleware and audit API router."""

import pytest
from unittest.mock import MagicMock, patch

from app.audit_middleware import AuditLoggingMiddleware, _log_request


@pytest.mark.unit
class TestAuditLogging:
    """Verify audit logging records requests correctly."""

    def test_log_request_captures_fields(self):
        """_log_request writes all expected fields to the audit store."""
        mock_store = MagicMock()
        with patch("app.audit_middleware._get_audit_store", return_value=mock_store):
            _log_request("GET", "/api/targets", 200, 12.5, "192.168.1.1")

        mock_store.log.assert_called_once()
        call_kwargs = mock_store.log.call_args
        assert call_kwargs[1]["actor"] == "client:192.168.1.1"
        assert call_kwargs[1]["action"] == "GET /api/targets"
        assert "200" in call_kwargs[1]["detail"]
        assert call_kwargs[1]["severity"] == "info"
        assert call_kwargs[1]["ip_address"] == "192.168.1.1"
        meta = call_kwargs[1]["metadata"]
        assert meta["method"] == "GET"
        assert meta["status_code"] == 200

    def test_log_request_error_severity(self):
        """5xx responses get error severity."""
        mock_store = MagicMock()
        with patch("app.audit_middleware._get_audit_store", return_value=mock_store):
            _log_request("POST", "/api/fail", 500, 5.0, "10.0.0.1")

        assert mock_store.log.call_args[1]["severity"] == "error"

    def test_log_request_warning_severity(self):
        """4xx responses get warning severity."""
        mock_store = MagicMock()
        with patch("app.audit_middleware._get_audit_store", return_value=mock_store):
            _log_request("GET", "/api/missing", 404, 2.0, "10.0.0.1")

        assert mock_store.log.call_args[1]["severity"] == "warning"

    def test_log_request_no_store(self):
        """If audit store is unavailable, logging is silently skipped."""
        with patch("app.audit_middleware._get_audit_store", return_value=None):
            _log_request("GET", "/api/test", 200, 1.0, "127.0.0.1")
        # No exception = pass

    def test_log_request_store_error(self):
        """If audit store raises, the error is swallowed."""
        mock_store = MagicMock()
        mock_store.log.side_effect = Exception("db error")
        with patch("app.audit_middleware._get_audit_store", return_value=mock_store):
            _log_request("GET", "/api/test", 200, 1.0, "127.0.0.1")
        # No exception = pass
