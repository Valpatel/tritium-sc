# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the webhook bridge addon.

All tests run without network access — HTTP POSTs are mocked.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tritium_lib.sdk import BridgeAddon
from tritium_lib.sdk.manifest import load_manifest, validate_manifest


MANIFEST_PATH = Path(__file__).parent.parent / "tritium_addon.toml"


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_loads(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.id == "bridge-webhook"
        assert m.name == "Webhook Bridge"

    def test_manifest_valid(self):
        m = load_manifest(MANIFEST_PATH)
        errors = validate_manifest(m)
        assert errors == [], f"Manifest errors: {errors}"

    def test_manifest_category(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.category_window == "integration"

    def test_manifest_permissions(self):
        m = load_manifest(MANIFEST_PATH)
        assert m.perm_network is True
        assert m.perm_serial is False

    def test_manifest_config_fields(self):
        m = load_manifest(MANIFEST_PATH)
        assert "webhook_url" in m.config_fields
        assert "batch_interval" in m.config_fields
        assert "include_position" in m.config_fields


# ---------------------------------------------------------------------------
# Addon class tests
# ---------------------------------------------------------------------------

class TestAddonClass:
    def test_import(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        assert addon.info.id == "bridge-webhook"

    def test_is_bridge(self):
        from webhook_addon import WebhookAddon
        assert issubclass(WebhookAddon, BridgeAddon)

    def test_health_not_registered(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        h = addon.health_check()
        assert h["status"] == "not_registered"

    def test_health_no_url(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        h = addon.health_check()
        assert h["status"] == "degraded"
        assert "no webhook url configured" in h["detail"].lower()

    def test_health_ok_with_url(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = "https://example.com/hook"
        h = addon.health_check()
        assert h["status"] == "ok"


# ---------------------------------------------------------------------------
# Send and batching tests
# ---------------------------------------------------------------------------

class TestSendBatching:
    def test_send_queues_targets(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = ""  # no URL = no actual POST
        addon._last_send = time.time()  # prevent auto-flush

        targets = [
            {"target_id": "ble_001", "lat": 37.0, "lng": -122.0},
            {"target_id": "ble_002", "lat": 37.1, "lng": -122.1},
        ]
        asyncio.run(addon.send(targets))
        assert len(addon._pending) == 2

    def test_flush_clears_pending(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = "https://example.com/hook"
        addon._pending = [
            {"target_id": "t1"},
            {"target_id": "t2"},
        ]

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("webhook_addon.urlopen", return_value=mock_resp):
            asyncio.run(addon._flush())

        assert len(addon._pending) == 0
        assert addon._send_count == 1

    def test_flush_skips_when_empty(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = "https://example.com/hook"
        addon._pending = []

        asyncio.run(addon._flush())
        assert addon._send_count == 0

    def test_flush_skips_when_no_url(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = ""
        addon._pending = [{"target_id": "t1"}]

        asyncio.run(addon._flush())
        # Pending not cleared because no URL
        assert len(addon._pending) == 1
        assert addon._send_count == 0

    def test_post_json_sync_sends_correct_payload(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()

        captured_req = {}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        def capture_urlopen(req, **kwargs):
            captured_req["url"] = req.full_url
            captured_req["data"] = req.data
            captured_req["method"] = req.method
            captured_req["content_type"] = req.get_header("Content-type")
            return mock_resp

        with patch("webhook_addon.urlopen", side_effect=capture_urlopen):
            payload = {"event": "test", "targets": []}
            status = addon._post_json_sync("https://example.com/hook", payload)

        assert status == 200
        assert captured_req["url"] == "https://example.com/hook"
        assert captured_req["method"] == "POST"
        assert captured_req["content_type"] == "application/json"
        body = json.loads(captured_req["data"])
        assert body["event"] == "test"

    def test_flush_handles_network_error(self):
        from webhook_addon import WebhookAddon
        from urllib.error import URLError
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = "https://example.com/hook"
        addon._pending = [{"target_id": "t1"}]

        with patch("webhook_addon.urlopen", side_effect=URLError("connection refused")):
            asyncio.run(addon._flush())

        assert addon._error_count == 1
        assert addon._send_count == 0
        assert len(addon._pending) == 0  # cleared even on error

    def test_position_stripped_when_disabled(self):
        from webhook_addon import WebhookAddon
        addon = WebhookAddon()
        addon._registered = True
        addon._webhook_url = "https://example.com/hook"
        addon._include_position = False
        addon._pending = [
            {"target_id": "t1", "lat": 37.0, "lng": -122.0, "position": {"lat": 37.0}},
        ]

        captured_payload = {}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        def capture_urlopen(req, **kwargs):
            captured_payload.update(json.loads(req.data))
            return mock_resp

        with patch("webhook_addon.urlopen", side_effect=capture_urlopen):
            asyncio.run(addon._flush())

        target = captured_payload["targets"][0]
        assert "lat" not in target
        assert "lng" not in target
        assert "position" not in target
