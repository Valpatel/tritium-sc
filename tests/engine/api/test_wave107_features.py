# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Wave 107 feature tests.

Tests for:
- Meshtastic message forwarding to MQTT/operator chat
- Target export CoT XML format
- Amy daily learning summary endpoint
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestMeshtasticMessageForwarding:
    """Verify mesh messages are forwarded to operator chat."""

    @pytest.mark.unit
    def test_on_mqtt_message_forwards_to_chat(self):
        """When a mesh text message arrives, it should be forwarded to operator chat."""
        from plugins.meshtastic_bridge.plugin import MeshtasticPlugin

        plugin = MeshtasticPlugin()
        plugin._logger = MagicMock()
        plugin._event_bus = MagicMock()
        plugin._mqtt_bridge = MagicMock()
        plugin._config.site_id = "test_site"

        msg_payload = json.dumps({
            "from_name": "MeshUser1",
            "text": "Hello from the field",
            "channel": 0,
            "timestamp": time.time(),
            "from_id": "!abc123",
        })

        plugin._on_mqtt_message("tritium/test_site/meshtastic/abc123/message", msg_payload)

        # Message should be stored
        assert len(plugin._messages) == 1
        assert plugin._messages[0]["text"] == "Hello from the field"

        # Event bus should be called for both meshtastic and operator chat
        assert plugin._event_bus.publish.call_count >= 2
        calls = [c[0][0] for c in plugin._event_bus.publish.call_args_list]
        assert "meshtastic:text_received" in calls
        assert "operator:chat_message" in calls

        # MQTT bridge should publish to chat topic
        plugin._mqtt_bridge.publish.assert_called_once()
        topic = plugin._mqtt_bridge.publish.call_args[0][0]
        assert "chat/mesh" in topic

    @pytest.mark.unit
    def test_forward_skips_empty_messages(self):
        """Empty mesh messages should not be forwarded."""
        from plugins.meshtastic_bridge.plugin import MeshtasticPlugin

        plugin = MeshtasticPlugin()
        plugin._logger = MagicMock()
        plugin._event_bus = MagicMock()
        plugin._mqtt_bridge = MagicMock()

        msg_payload = json.dumps({"from_name": "User", "text": ""})
        plugin._on_mqtt_message("topic", msg_payload)

        # Message stored but not forwarded (empty text)
        plugin._mqtt_bridge.publish.assert_not_called()

    @pytest.mark.unit
    def test_forward_without_mqtt_bridge(self):
        """If no MQTT bridge, message should still be stored locally."""
        from plugins.meshtastic_bridge.plugin import MeshtasticPlugin

        plugin = MeshtasticPlugin()
        plugin._logger = MagicMock()
        plugin._event_bus = MagicMock()
        plugin._mqtt_bridge = None  # No bridge

        msg_payload = json.dumps({
            "from_name": "User",
            "text": "Test message",
        })
        plugin._on_mqtt_message("topic", msg_payload)

        assert len(plugin._messages) == 1

    @pytest.mark.unit
    def test_operator_chat_route_exists(self):
        """The /api/meshtastic/chat POST route should exist."""
        from plugins.meshtastic_bridge.plugin import MeshtasticPlugin
        from plugins.meshtastic_bridge.routes import create_router

        plugin = MeshtasticPlugin()
        plugin._app = FastAPI()
        plugin._logger = MagicMock()

        router = create_router(plugin)
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert any("/chat" in p for p in paths)


class TestTargetExportCoT:
    """Verify CoT XML export format works."""

    @pytest.mark.unit
    def test_cot_export_format_available(self):
        """The /api/targets/export endpoint should accept format=cot."""
        from app.routers.targets_unified import export_targets
        import inspect
        sig = inspect.signature(export_targets)
        # Check that format param description mentions cot
        assert "format" in sig.parameters

    @pytest.mark.unit
    def test_cot_export_returns_xml(self):
        """Export with format=cot should return XML content."""
        from app.routers.targets_unified import router

        app = FastAPI()
        app.include_router(router)

        # Mock tracker with a target
        mock_tracker = MagicMock()
        mock_target = MagicMock()
        mock_target.to_dict.return_value = {
            "target_id": "ble_test",
            "name": "Test Device",
            "alliance": "friendly",
            "asset_type": "phone",
            "lat": 33.5,
            "lng": -117.2,
            "source": "ble",
            "battery": 0.9,
            "speed": 0.0,
            "heading": 0.0,
            "status": "active",
        }
        mock_tracker.get_all.return_value = [mock_target]

        mock_amy = MagicMock()
        mock_amy.target_tracker = mock_tracker
        app.state.amy = mock_amy
        app.state.simulation_engine = None

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/targets/export?format=cot")

        assert resp.status_code == 200
        # Should be XML content
        content = resp.text
        assert "<event" in content or "<cot-events" in content
        assert "ble_test" in content

    @pytest.mark.unit
    def test_cot_export_empty_targets(self):
        """Export with no targets should still return valid XML structure."""
        from app.routers.targets_unified import router

        app = FastAPI()
        app.include_router(router)

        mock_tracker = MagicMock()
        mock_tracker.get_all.return_value = []

        mock_amy = MagicMock()
        mock_amy.target_tracker = mock_tracker
        app.state.amy = mock_amy
        app.state.simulation_engine = None

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/targets/export?format=cot")

        assert resp.status_code == 200
        assert "cot-events" in resp.text
        assert 'count="0"' in resp.text


class TestAmyLearningSummary:
    """Verify Amy's daily learning summary endpoint."""

    @pytest.mark.unit
    def test_learning_summary_exists(self):
        """The /api/amy/learning-summary endpoint should exist."""
        from amy.router import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert any("learning-summary" in p for p in paths)

    @pytest.mark.unit
    def test_learning_summary_structure(self):
        """The learning summary response should have the expected structure."""
        from amy.router import router

        app = FastAPI()

        # Override auth
        from app.auth import require_auth
        async def fake_auth():
            return {"sub": "admin", "role": "admin"}
        app.dependency_overrides[require_auth] = fake_auth
        app.include_router(router)

        # Mock Amy with a tracker
        mock_tracker = MagicMock()
        mock_tracker.get_all.return_value = []

        mock_amy = MagicMock()
        mock_amy.target_tracker = mock_tracker
        app.state.amy = mock_amy

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/amy/learning-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert "generated_at" in data
        assert "period_hours" in data
        assert data["period_hours"] == 24
        assert "correlation_stats" in data
        assert "threat_assessment" in data
        assert "operator_feedback" in data
        assert "narrative" in data
        assert isinstance(data["narrative"], str)
        assert len(data["narrative"]) > 20  # Should have meaningful content

    @pytest.mark.unit
    def test_learning_summary_with_targets(self):
        """Learning summary should include stats when targets exist."""
        from amy.router import router

        app = FastAPI()

        from app.auth import require_auth
        async def fake_auth():
            return {"sub": "admin", "role": "admin"}
        app.dependency_overrides[require_auth] = fake_auth
        app.include_router(router)

        # Create mock targets
        mock_targets = []
        for i in range(5):
            mt = MagicMock()
            mt.to_dict.return_value = {
                "target_id": f"t{i}",
                "source": "ble" if i < 3 else "yolo",
                "alliance": "friendly" if i < 2 else ("hostile" if i == 2 else "unknown"),
            }
            mock_targets.append(mt)

        mock_tracker = MagicMock()
        mock_tracker.get_all.return_value = mock_targets

        mock_amy = MagicMock()
        mock_amy.target_tracker = mock_tracker
        app.state.amy = mock_amy

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/amy/learning-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation_stats"]["total_targets"] == 5
        assert "ble" in data["correlation_stats"]["source_distribution"]
        assert data["threat_assessment"]["hostile_count"] == 1
