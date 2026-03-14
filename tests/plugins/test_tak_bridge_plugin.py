# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TAKBridgePlugin — CoT bridge plugin for ATAK/WinTAK interop.

Tests cover:
    - Plugin identity and lifecycle
    - CoT XML generation from targets
    - CoT XML parsing to targets
    - Alliance/affiliation mapping
    - Multicast UDP transport (mock socket)
    - TCP transport (mock socket)
    - MQTT transport (EventBus publish)
    - Inbound CoT -> TargetTracker injection
    - Echo-loop prevention (tak_ prefix filtering)
    - API routes
"""

from __future__ import annotations

import os
import socket
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def target_tracker():
    tracker = MagicMock()
    tracker.get_all.return_value = []
    return tracker


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.include_router = MagicMock()
    return app


@pytest.fixture
def plugin_ctx(event_bus, target_tracker, mock_app):
    from engine.plugins.base import PluginContext
    import logging
    return PluginContext(
        event_bus=event_bus,
        target_tracker=target_tracker,
        simulation_engine=None,
        settings={},
        app=mock_app,
        logger=logging.getLogger("test-tak"),
        plugin_manager=None,
    )


@pytest.fixture
def plugin(plugin_ctx):
    """Create and configure a TAKBridgePlugin (disabled by default)."""
    from tak_bridge.plugin import TAKBridgePlugin
    p = TAKBridgePlugin()
    p.configure(plugin_ctx)
    return p


@pytest.fixture
def enabled_plugin(plugin_ctx, monkeypatch):
    """Create a TAKBridgePlugin with TAK_ENABLED=true."""
    monkeypatch.setenv("TAK_ENABLED", "true")
    from tak_bridge.plugin import TAKBridgePlugin
    p = TAKBridgePlugin()
    p.configure(plugin_ctx)
    return p


@pytest.fixture
def sample_target_dict():
    return {
        "target_id": "unit-alpha",
        "name": "Alpha",
        "alliance": "friendly",
        "asset_type": "person",
        "lat": 34.0522,
        "lng": -118.2437,
        "alt": 10.0,
        "heading": 90.0,
        "speed": 1.5,
        "battery": 0.85,
        "status": "active",
        "source": "simulation",
        "health": 100,
        "max_health": 100,
        "kills": 0,
    }


@pytest.fixture
def sample_cot_xml():
    """A valid CoT XML string for a friendly ground unit."""
    return (
        '<event version="2.0" uid="ATAK-user-1" type="a-f-G-U" how="h-g-i-g-o" '
        'time="2026-03-13T00:00:00.000000Z" start="2026-03-13T00:00:00.000000Z" '
        'stale="2026-03-13T00:02:00.000000Z">'
        '<point lat="34.0522" lon="-118.2437" hae="10.0" ce="10.0" le="10.0" />'
        '<detail>'
        '<contact callsign="Bravo" />'
        '<__group name="Cyan" role="Team Member" />'
        '<track speed="2.0" course="180.0" />'
        '</detail>'
        '</event>'
    )


# ===================================================================
# Plugin Identity
# ===================================================================

class TestPluginIdentity:

    def test_import(self):
        from tak_bridge.plugin import TAKBridgePlugin
        assert TAKBridgePlugin is not None

    def test_plugin_id(self, plugin):
        assert plugin.plugin_id == "tritium.tak-bridge"

    def test_name(self, plugin):
        assert plugin.name == "TAK Bridge"

    def test_version(self, plugin):
        assert plugin.version == "1.0.0"

    def test_capabilities(self, plugin):
        caps = plugin.capabilities
        assert "bridge" in caps
        assert "data_source" in caps
        assert "routes" in caps

    def test_routes_registered(self, mock_app, plugin):
        mock_app.include_router.assert_called_once()


# ===================================================================
# Loader
# ===================================================================

class TestLoader:

    def test_loader_import(self):
        from tak_bridge_loader import TAKBridgePlugin
        assert TAKBridgePlugin is not None


# ===================================================================
# Configuration
# ===================================================================

class TestConfiguration:

    def test_default_disabled(self, plugin):
        assert plugin._enabled is False
        assert plugin.stats["enabled"] is False

    def test_env_enabled(self, enabled_plugin):
        assert enabled_plugin._enabled is True

    def test_env_config(self, plugin_ctx, monkeypatch):
        monkeypatch.setenv("TAK_ENABLED", "true")
        monkeypatch.setenv("TAK_SERVER_HOST", "192.168.1.100")
        monkeypatch.setenv("TAK_SERVER_PORT", "9000")
        monkeypatch.setenv("TAK_MULTICAST_ADDR", "239.5.5.5")
        monkeypatch.setenv("TAK_MULTICAST_PORT", "7777")
        monkeypatch.setenv("TAK_CALLSIGN", "MY-HQ")
        monkeypatch.setenv("TAK_PUBLISH_INTERVAL", "10")
        monkeypatch.setenv("TAK_STALE_SECONDS", "300")
        monkeypatch.setenv("MQTT_SITE_ID", "ops-center")

        from tak_bridge.plugin import TAKBridgePlugin
        p = TAKBridgePlugin()
        p.configure(plugin_ctx)

        assert p._enabled is True
        assert p._server_host == "192.168.1.100"
        assert p._server_port == 9000
        assert p._multicast_addr == "239.5.5.5"
        assert p._multicast_port == 7777
        assert p._callsign == "MY-HQ"
        assert p._publish_interval == 10.0
        assert p._stale_seconds == 300
        assert p._site_id == "ops-center"


# ===================================================================
# CoT Generation
# ===================================================================

class TestCoTGeneration:

    def test_target_to_cot_xml(self, plugin, sample_target_dict):
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)

        assert root.tag == "event"
        assert root.get("version") == "2.0"
        assert root.get("uid") == "unit-alpha"

        # Type should be friendly ground unit
        cot_type = root.get("type", "")
        assert cot_type.startswith("a-f-")

        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(34.0522)
        assert float(point.get("lon")) == pytest.approx(-118.2437)

        contact = root.find(".//contact")
        assert contact is not None
        assert contact.get("callsign") == "Alpha"

    def test_hostile_target_cot_type(self, plugin, sample_target_dict):
        sample_target_dict["alliance"] = "hostile"
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)

        cot_type = root.get("type", "")
        assert cot_type.startswith("a-h-")

    def test_unknown_alliance_cot_type(self, plugin, sample_target_dict):
        sample_target_dict["alliance"] = "unknown"
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)

        cot_type = root.get("type", "")
        assert cot_type.startswith("a-u-")

    def test_neutral_alliance_cot_type(self, plugin, sample_target_dict):
        sample_target_dict["alliance"] = "neutral"
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)

        cot_type = root.get("type", "")
        assert cot_type.startswith("a-n-")

    def test_cot_contains_stale_time(self, plugin, sample_target_dict):
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)
        assert root.get("stale") is not None

    def test_cot_contains_track_element(self, plugin, sample_target_dict):
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)
        track = root.find(".//track")
        assert track is not None
        assert float(track.get("speed")) == pytest.approx(1.5)
        assert float(track.get("course")) == pytest.approx(90.0)


# ===================================================================
# CoT Parsing (inbound)
# ===================================================================

class TestCoTParsing:

    def test_cot_to_target(self, plugin, sample_cot_xml):
        target = plugin._cot_to_target(sample_cot_xml)
        assert target is not None
        assert target["name"] == "Bravo"
        assert target["alliance"] == "friendly"
        assert target["lat"] == pytest.approx(34.0522)
        assert target["lng"] == pytest.approx(-118.2437)
        assert target["speed"] == pytest.approx(2.0)
        assert target["heading"] == pytest.approx(180.0)

    def test_cot_hostile_alliance(self, plugin):
        xml = (
            '<event version="2.0" uid="hostile-1" type="a-h-G" how="h-e" '
            'time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z" '
            'stale="2026-01-01T00:02:00Z">'
            '<point lat="35.0" lon="-117.0" hae="0" ce="10" le="10" />'
            '<detail><contact callsign="Hostile1" /></detail>'
            '</event>'
        )
        target = plugin._cot_to_target(xml)
        assert target is not None
        assert target["alliance"] == "hostile"

    def test_invalid_xml_returns_none(self, plugin):
        assert plugin._cot_to_target("not xml") is None

    def test_non_event_returns_none(self, plugin):
        assert plugin._cot_to_target("<root><child /></root>") is None


# ===================================================================
# Echo Loop Prevention
# ===================================================================

class TestEchoLoopPrevention:

    def test_tak_prefixed_targets_filtered(self, plugin):
        assert plugin._should_publish({"target_id": "tak_user-1"}) is False

    def test_non_tak_targets_pass(self, plugin):
        assert plugin._should_publish({"target_id": "unit-alpha"}) is True

    def test_empty_id_passes(self, plugin):
        assert plugin._should_publish({"target_id": ""}) is True


# ===================================================================
# Inbound Handling
# ===================================================================

class TestInboundHandling:

    def test_inbound_cot_creates_target(self, plugin, sample_cot_xml, target_tracker):
        plugin._handle_inbound_cot(sample_cot_xml)

        # Should inject into TargetTracker
        target_tracker.update_from_simulation.assert_called_once()
        call_args = target_tracker.update_from_simulation.call_args[0][0]
        assert call_args["target_id"] == "tak_ATAK-user-1"
        assert call_args["source"] == "tak"

    def test_inbound_tracks_client(self, plugin, sample_cot_xml):
        plugin._handle_inbound_cot(sample_cot_xml)

        clients = plugin.connected_clients
        assert "ATAK-user-1" in clients
        assert clients["ATAK-user-1"]["callsign"] == "Bravo"

    def test_inbound_publishes_event(self, plugin, sample_cot_xml, event_bus):
        received = []
        q = event_bus.subscribe()

        plugin._handle_inbound_cot(sample_cot_xml)

        import queue
        try:
            event = q.get(timeout=1.0)
            received.append(event)
        except queue.Empty:
            pass

        assert len(received) == 1
        assert received[0]["type"] == "tak_client_update"

    def test_inbound_invalid_xml_ignored(self, plugin, target_tracker):
        plugin._handle_inbound_cot("garbage data")
        target_tracker.update_from_simulation.assert_not_called()

    def test_inbound_increments_counter(self, plugin, sample_cot_xml):
        assert plugin._messages_received == 0
        plugin._handle_inbound_cot(sample_cot_xml)
        assert plugin._messages_received == 1


# ===================================================================
# Transport: Multicast UDP (mocked)
# ===================================================================

class TestMulticastTransport:

    def test_send_cot_multicast(self, enabled_plugin, sample_target_dict):
        mock_sock = MagicMock(spec=socket.socket)
        enabled_plugin._mcast_sock = mock_sock

        xml = enabled_plugin._target_to_cot(sample_target_dict)
        enabled_plugin._send_cot(xml)

        mock_sock.sendto.assert_called_once()
        args = mock_sock.sendto.call_args
        assert args[0][1] == ("239.2.3.1", 6969)
        # Verify it's valid XML
        ET.fromstring(args[0][0].decode("utf-8"))

    def test_multicast_send_error_handled(self, enabled_plugin):
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto.side_effect = OSError("Network unreachable")
        enabled_plugin._mcast_sock = mock_sock

        # Should not raise
        enabled_plugin._send_cot("<event />")


# ===================================================================
# Transport: TCP (mocked)
# ===================================================================

class TestTCPTransport:

    def test_send_cot_tcp(self, enabled_plugin, sample_target_dict):
        mock_sock = MagicMock(spec=socket.socket)
        enabled_plugin._tcp_sock = mock_sock
        enabled_plugin._tcp_connected = True

        xml = enabled_plugin._target_to_cot(sample_target_dict)
        enabled_plugin._send_cot(xml)

        mock_sock.sendall.assert_called_once()
        sent_bytes = mock_sock.sendall.call_args[0][0]
        ET.fromstring(sent_bytes.decode("utf-8"))

    def test_tcp_send_error_disconnects(self, enabled_plugin):
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendall.side_effect = OSError("Broken pipe")
        enabled_plugin._tcp_sock = mock_sock
        enabled_plugin._tcp_connected = True

        enabled_plugin._send_cot("<event />")

        assert enabled_plugin._tcp_connected is False

    def test_tcp_not_sent_when_disconnected(self, enabled_plugin):
        mock_sock = MagicMock(spec=socket.socket)
        enabled_plugin._tcp_sock = mock_sock
        enabled_plugin._tcp_connected = False

        enabled_plugin._send_cot("<event />")

        mock_sock.sendall.assert_not_called()


# ===================================================================
# Transport: MQTT via EventBus
# ===================================================================

class TestMQTTTransport:

    def test_send_cot_publishes_to_eventbus(self, enabled_plugin, event_bus):
        received = []
        q = event_bus.subscribe()

        enabled_plugin._send_cot("<event />")

        import queue
        try:
            event = q.get(timeout=1.0)
            received.append(event)
        except queue.Empty:
            pass

        assert len(received) == 1
        assert received[0]["type"] == "tak_cot_outbound"
        assert received[0]["data"]["topic"] == "tritium/home/cot"
        assert "<event />" in received[0]["data"]["xml"]


# ===================================================================
# Stats & Health
# ===================================================================

class TestStatsAndHealth:

    def test_stats_structure(self, plugin):
        stats = plugin.stats
        assert "enabled" in stats
        assert "running" in stats
        assert "callsign" in stats
        assert "multicast" in stats
        assert "messages_sent" in stats
        assert "messages_received" in stats
        assert "connected_clients" in stats
        assert "last_error" in stats

    def test_healthy_when_disabled(self, plugin):
        assert plugin.healthy is True

    def test_healthy_when_running(self, enabled_plugin):
        enabled_plugin._running = True
        assert enabled_plugin.healthy is True

    def test_not_healthy_when_enabled_but_not_running(self, enabled_plugin):
        enabled_plugin._running = False
        assert enabled_plugin.healthy is False


# ===================================================================
# Lifecycle
# ===================================================================

class TestLifecycle:

    def test_start_when_disabled_noop(self, plugin):
        plugin.start()
        assert plugin._running is False

    def test_stop_when_not_running_noop(self, plugin):
        plugin.stop()  # should not raise

    @patch("tak_bridge.plugin.TAKBridgePlugin._setup_multicast")
    @patch("tak_bridge.plugin.TAKBridgePlugin._setup_tcp")
    def test_start_enabled_starts_threads(self, mock_tcp, mock_mcast, enabled_plugin):
        enabled_plugin.start()
        try:
            assert enabled_plugin._running is True
            assert enabled_plugin._publish_thread is not None
            assert enabled_plugin._publish_thread.is_alive()
        finally:
            enabled_plugin.stop()

    def test_double_start_noop(self, enabled_plugin):
        with patch.object(enabled_plugin, "_setup_multicast"):
            enabled_plugin.start()
            thread = enabled_plugin._publish_thread
            enabled_plugin.start()  # should not create new thread
            assert enabled_plugin._publish_thread is thread
            enabled_plugin.stop()


# ===================================================================
# Alliance Mapping (integration with engine/comms/cot.py)
# ===================================================================

class TestAllianceMapping:

    @pytest.mark.parametrize("alliance,expected_prefix", [
        ("friendly", "a-f-"),
        ("hostile", "a-h-"),
        ("neutral", "a-n-"),
        ("unknown", "a-u-"),
    ])
    def test_alliance_to_cot_affiliation(self, plugin, sample_target_dict, alliance, expected_prefix):
        sample_target_dict["alliance"] = alliance
        xml_str = plugin._target_to_cot(sample_target_dict)
        root = ET.fromstring(xml_str)
        cot_type = root.get("type", "")
        assert cot_type.startswith(expected_prefix), f"Expected {expected_prefix}*, got {cot_type}"

    @pytest.mark.parametrize("cot_type,expected_alliance", [
        ("a-f-G-U", "friendly"),
        ("a-h-G", "hostile"),
        ("a-n-G", "neutral"),
        ("a-u-G", "unknown"),
    ])
    def test_cot_affiliation_to_alliance(self, plugin, cot_type, expected_alliance):
        xml = (
            f'<event version="2.0" uid="test-1" type="{cot_type}" how="h-e" '
            f'time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z" '
            f'stale="2026-01-01T00:02:00Z">'
            f'<point lat="34.0" lon="-118.0" hae="0" ce="10" le="10" />'
            f'<detail><contact callsign="Test" /></detail>'
            f'</event>'
        )
        target = plugin._cot_to_target(xml)
        assert target is not None
        assert target["alliance"] == expected_alliance
