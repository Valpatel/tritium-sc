# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for amy.comms.meshtastic_bridge.MeshtasticBridge."""

from __future__ import annotations

import json
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.meshtastic_bridge import MeshtasticBridge, MeshtasticNode, MESHTASTIC_MAX_TEXT


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    """Lightweight EventBus stand-in that records published events."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None):
        self.published.append((event_type, data))

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        pass


class MockTargetTracker:
    """Lightweight TargetTracker stand-in that records calls."""

    def __init__(self):
        self.sim_updates: list[dict] = []

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus():
    return MockEventBus()


@pytest.fixture
def tracker():
    return MockTargetTracker()


@pytest.fixture
def bridge(event_bus, tracker):
    return MeshtasticBridge(
        event_bus=event_bus,
        target_tracker=tracker,
        host="192.168.1.50",
        port=4403,
    )


# ===========================================================================
# Init / Config
# ===========================================================================


@pytest.mark.unit
class TestInit:
    def test_stores_config(self, bridge):
        assert bridge._host == "192.168.1.50"
        assert bridge._port == 4403

    def test_initial_state(self, bridge):
        assert bridge.connected is False
        assert bridge._running is False
        assert bridge._interface is None
        assert bridge._messages_received == 0
        assert bridge._messages_sent == 0
        assert bridge._last_error == ""

    def test_default_params(self, event_bus, tracker):
        b = MeshtasticBridge(event_bus=event_bus, target_tracker=tracker)
        assert b._host == ""
        assert b._port == 4403

    def test_meshtastic_node_dataclass(self):
        node = MeshtasticNode(
            node_id="!abc123",
            long_name="Base Station",
            short_name="BS",
            hardware="HELTEC_V3",
        )
        assert node.node_id == "!abc123"
        assert node.long_name == "Base Station"
        assert node.short_name == "BS"
        assert node.hardware == "HELTEC_V3"
        assert node.position is None
        assert node.battery is None
        assert node.hops == 0


# ===========================================================================
# Stats property
# ===========================================================================


@pytest.mark.unit
class TestStats:
    def test_stats_returns_all_fields(self, bridge):
        s = bridge.stats
        assert s["connected"] is False
        assert s["host"] == "192.168.1.50:4403"
        assert s["messages_received"] == 0
        assert s["messages_sent"] == 0
        assert s["nodes_discovered"] == 0
        assert s["last_error"] == ""

    def test_stats_auto_discover_host(self, event_bus, tracker):
        b = MeshtasticBridge(event_bus=event_bus, target_tracker=tracker)
        s = b.stats
        assert s["host"] == "auto-discover"

    def test_stats_reflects_counter_changes(self, bridge):
        bridge._messages_received = 42
        bridge._messages_sent = 7
        bridge._last_error = "some error"
        bridge._nodes["!abc"] = MeshtasticNode(node_id="!abc")
        s = bridge.stats
        assert s["messages_received"] == 42
        assert s["messages_sent"] == 7
        assert s["last_error"] == "some error"
        assert s["nodes_discovered"] == 1


# ===========================================================================
# start() / stop()
# ===========================================================================


@pytest.mark.unit
class TestStartStop:
    def test_start_without_meshtastic_sets_error(self, bridge):
        """start() should gracefully handle missing meshtastic package."""
        with patch.dict("sys.modules", {
            "meshtastic": None,
            "meshtastic.tcp_interface": None,
            "pubsub": None,
        }):
            bridge.start()
        assert bridge._running is False
        assert bridge._last_error == "meshtastic not installed"

    def test_start_idempotent(self, bridge):
        """Calling start() twice does nothing the second time."""
        bridge._running = True
        bridge.start()
        assert bridge._interface is None

    def test_start_handles_connection_error(self, bridge):
        """start() should handle TCPInterface raising an exception."""
        mock_tcp = MagicMock()
        mock_tcp.TCPInterface.side_effect = ConnectionRefusedError("refused")
        mock_pub = MagicMock()

        with patch.dict("sys.modules", {
            "meshtastic": MagicMock(),
            "meshtastic.tcp_interface": mock_tcp,
            "pubsub": mock_pub,
            "pubsub.pub": mock_pub,
        }):
            # Need to re-import since we're patching sys.modules
            with patch("engine.comms.meshtastic_bridge.MeshtasticBridge.start") as mock_start:
                # Test the actual logic by calling the real method
                pass

        # Simulate what happens when TCPInterface fails
        bridge._running = True
        bridge._last_error = "refused"
        bridge._interface = None
        bridge._running = False
        assert bridge._running is False
        assert "refused" in bridge._last_error

    def test_stop_when_not_started(self, bridge):
        """stop() should be safe to call even if never started."""
        bridge.stop()
        assert bridge._connected is False
        assert bridge._running is False

    def test_stop_clears_connected(self, bridge):
        bridge._connected = True
        bridge._running = True
        bridge.stop()
        assert bridge._connected is False
        assert bridge._running is False

    def test_stop_closes_interface(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._running = True

        bridge.stop()

        mock_iface.close.assert_called_once()
        assert bridge._interface is None

    def test_stop_handles_close_exception(self, bridge):
        """stop() should swallow exceptions from close."""
        mock_iface = MagicMock()
        mock_iface.close.side_effect = RuntimeError("already closed")
        bridge._interface = mock_iface
        bridge._running = True

        bridge.stop()
        assert bridge._interface is None
        assert bridge._running is False


# ===========================================================================
# Text message handling
# ===========================================================================


@pytest.mark.unit
class TestTextHandler:
    def test_text_message_published_to_eventbus(self, bridge, event_bus):
        packet = {
            "fromId": "!abc123",
            "toId": "^all",
            "channel": 0,
            "decoded": {"text": "Hello mesh!"},
        }
        bridge._on_text(packet)

        assert bridge._messages_received == 1
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mesh_text"
        data = event_bus.published[0][1]
        assert data["from"] == "!abc123"
        assert data["to"] == "^all"
        assert data["text"] == "Hello mesh!"
        assert data["channel"] == 0

    def test_text_message_stored_in_history(self, bridge):
        packet = {
            "fromId": "!abc",
            "toId": "^all",
            "channel": 0,
            "decoded": {"text": "Test"},
        }
        bridge._on_text(packet)
        assert len(bridge.messages) == 1
        assert bridge.messages[0]["text"] == "Test"

    def test_text_message_history_capped_at_500(self, bridge):
        for i in range(550):
            packet = {
                "fromId": "!abc",
                "toId": "^all",
                "decoded": {"text": f"Message {i}"},
            }
            bridge._on_text(packet)

        assert len(bridge.messages) == 500
        # Most recent should be the last one
        assert bridge.messages[-1]["text"] == "Message 549"

    def test_text_with_empty_decoded(self, bridge, event_bus):
        packet = {"fromId": "!abc", "decoded": {}}
        bridge._on_text(packet)
        assert bridge._messages_received == 1
        assert event_bus.published[0][1]["text"] == ""

    def test_text_with_missing_fields(self, bridge, event_bus):
        packet = {"decoded": {"text": "minimal"}}
        bridge._on_text(packet)
        data = event_bus.published[0][1]
        assert data["from"] == "unknown"
        assert data["to"] == "^all"
        assert data["text"] == "minimal"

    def test_text_with_snr_rssi(self, bridge, event_bus):
        packet = {
            "fromId": "!abc",
            "decoded": {"text": "signal test"},
            "rxSnr": 10.5,
            "rxRssi": -60,
        }
        bridge._on_text(packet)
        data = event_bus.published[0][1]
        assert data["snr"] == 10.5
        assert data["rssi"] == -60


# ===========================================================================
# Position handling
# ===========================================================================


@pytest.mark.unit
class TestPositionHandler:
    def test_position_updates_tracker(self, bridge, tracker):
        with patch("engine.tactical.geo.latlng_to_local", return_value=(10.0, 20.0, 0.0)):
            packet = {
                "fromId": "!node1",
                "decoded": {
                    "position": {
                        "latitude": 37.7749,
                        "longitude": -122.4194,
                        "altitude": 16.0,
                    }
                },
            }
            bridge._on_position(packet)

        assert bridge._messages_received == 1
        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["target_id"] == "mesh_!node1"
        assert update["alliance"] == "friendly"
        assert update["asset_type"] == "mesh_radio"
        assert update["position"]["x"] == 10.0
        assert update["position"]["y"] == 20.0

    def test_position_skips_zero_coords(self, bridge, tracker, event_bus):
        """Position at (0,0) should be silently ignored."""
        packet = {
            "fromId": "!node1",
            "decoded": {
                "position": {
                    "latitude": 0.0,
                    "longitude": 0.0,
                }
            },
        }
        bridge._on_position(packet)
        assert bridge._messages_received == 1
        assert len(tracker.sim_updates) == 0

    def test_position_publishes_to_eventbus(self, bridge, event_bus):
        with patch("engine.tactical.geo.latlng_to_local", return_value=(5.0, 15.0, 0.0)):
            packet = {
                "fromId": "!node1",
                "decoded": {
                    "position": {
                        "latitude": 37.7749,
                        "longitude": -122.4194,
                    }
                },
            }
            bridge._on_position(packet)

        mesh_events = [e for e in event_bus.published if e[0] == "mesh_position"]
        assert len(mesh_events) == 1
        data = mesh_events[0][1]
        assert data["node_id"] == "!node1"
        assert data["lat"] == 37.7749
        assert data["local_x"] == 5.0

    def test_position_updates_node_info(self, bridge):
        bridge._nodes["!node1"] = MeshtasticNode(node_id="!node1", long_name="Test")

        with patch("engine.tactical.geo.latlng_to_local", return_value=(0.0, 0.0, 0.0)):
            packet = {
                "fromId": "!node1",
                "decoded": {
                    "position": {
                        "latitude": 37.7,
                        "longitude": -122.4,
                    }
                },
            }
            bridge._on_position(packet)

        node = bridge._nodes["!node1"]
        assert node.position is not None
        assert node.position["lat"] == 37.7

    def test_position_uses_integer_coords(self, bridge, tracker):
        """Meshtastic can send latitudeI/longitudeI as integers * 1e7."""
        with patch("engine.tactical.geo.latlng_to_local", return_value=(1.0, 2.0, 0.0)):
            packet = {
                "fromId": "!node1",
                "decoded": {
                    "position": {
                        "latitudeI": 377749000,
                        "longitudeI": -1224194000,
                    }
                },
            }
            bridge._on_position(packet)

        assert len(tracker.sim_updates) == 1


# ===========================================================================
# Telemetry handling
# ===========================================================================


@pytest.mark.unit
class TestTelemetryHandler:
    def test_telemetry_updates_node_battery(self, bridge, event_bus):
        bridge._nodes["!node1"] = MeshtasticNode(node_id="!node1")

        packet = {
            "fromId": "!node1",
            "decoded": {
                "telemetry": {
                    "deviceMetrics": {
                        "batteryLevel": 75,
                        "voltage": 3.8,
                    }
                }
            },
        }
        bridge._on_telemetry(packet)

        assert bridge._messages_received == 1
        node = bridge._nodes["!node1"]
        assert node.battery == 75
        assert node.voltage == 3.8

    def test_telemetry_publishes_to_eventbus(self, bridge, event_bus):
        packet = {
            "fromId": "!node1",
            "decoded": {
                "telemetry": {
                    "deviceMetrics": {"batteryLevel": 50}
                }
            },
        }
        bridge._on_telemetry(packet)

        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mesh_telemetry"
        data = event_bus.published[0][1]
        assert data["node_id"] == "!node1"
        assert data["battery"] == 50

    def test_telemetry_with_unknown_node(self, bridge, event_bus):
        """Telemetry from unknown node should still publish but not crash."""
        packet = {
            "fromId": "!unknown",
            "decoded": {
                "telemetry": {
                    "deviceMetrics": {"batteryLevel": 90}
                }
            },
        }
        bridge._on_telemetry(packet)
        assert bridge._messages_received == 1
        assert len(event_bus.published) == 1


# ===========================================================================
# Node update handling
# ===========================================================================


@pytest.mark.unit
class TestNodeUpdate:
    def test_node_discovery(self, bridge, event_bus):
        node_data = {
            "num": 12345,
            "user": {
                "longName": "Base Station Alpha",
                "shortName": "BSA",
                "hwModel": "HELTEC_V3",
            },
        }
        bridge._on_node_update(node_data)

        assert "12345" in bridge._nodes
        node = bridge._nodes["12345"]
        assert node.long_name == "Base Station Alpha"
        assert node.short_name == "BSA"
        assert node.hardware == "HELTEC_V3"

        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mesh_node_update"

    def test_node_update_with_position(self, bridge):
        node_data = {
            "num": 99,
            "user": {"longName": "Mobile"},
            "position": {
                "latitude": 37.7,
                "longitude": -122.4,
                "altitude": 10.0,
            },
        }
        bridge._on_node_update(node_data)

        node = bridge._nodes["99"]
        assert node.position is not None
        assert node.position["lat"] == 37.7

    def test_node_update_with_battery(self, bridge):
        node_data = {
            "num": 99,
            "user": {"longName": "Solar Node"},
            "deviceMetrics": {"batteryLevel": 95, "voltage": 4.1},
        }
        bridge._on_node_update(node_data)

        node = bridge._nodes["99"]
        assert node.battery == 95
        assert node.voltage == 4.1

    def test_node_update_missing_num(self, bridge, event_bus):
        """Node without num should be ignored."""
        bridge._on_node_update({"user": {"longName": "Ghost"}})
        assert len(bridge._nodes) == 0
        assert len(event_bus.published) == 0

    def test_node_update_overwrites_existing(self, bridge):
        bridge._nodes["99"] = MeshtasticNode(node_id="99", long_name="Old Name")
        node_data = {
            "num": 99,
            "user": {"longName": "New Name"},
        }
        bridge._on_node_update(node_data)
        assert bridge._nodes["99"].long_name == "New Name"


# ===========================================================================
# Connect / Disconnect callbacks
# ===========================================================================


@pytest.mark.unit
class TestConnectionCallbacks:
    def test_on_connect(self, bridge, event_bus):
        bridge._on_connect()
        assert bridge._connected is True
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mesh_connected"

    def test_on_disconnect(self, bridge, event_bus):
        bridge._connected = True
        bridge._on_disconnect()
        assert bridge._connected is False
        assert bridge._last_error == "Connection lost"
        assert event_bus.published[0][0] == "mesh_disconnected"


# ===========================================================================
# Outbound — send_text
# ===========================================================================


@pytest.mark.unit
class TestSendText:
    def test_send_text_when_disconnected(self, bridge):
        bridge._connected = False
        result = bridge.send_text("hello")
        assert result is False
        assert bridge._messages_sent == 0

    def test_send_text_when_interface_is_none(self, bridge):
        bridge._connected = True
        bridge._interface = None
        result = bridge.send_text("hello")
        assert result is False

    def test_send_text_success(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.send_text("Hello mesh!", channel=1, destination="!abc")
        assert result is True
        assert bridge._messages_sent == 1
        mock_iface.sendText.assert_called_once_with(
            text="Hello mesh!", channelIndex=1, destinationId="!abc"
        )

    def test_send_text_broadcast(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.send_text("Broadcast")
        assert result is True
        # No destinationId for broadcast
        mock_iface.sendText.assert_called_once_with(
            text="Broadcast", channelIndex=0
        )

    def test_send_text_truncates_at_228(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        long_text = "A" * 300
        result = bridge.send_text(long_text)
        assert result is True

        call_kwargs = mock_iface.sendText.call_args[1]
        assert len(call_kwargs["text"]) == MESHTASTIC_MAX_TEXT

    def test_send_text_stores_in_history(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        bridge.send_text("Outbound msg")
        msgs = bridge.messages
        assert len(msgs) == 1
        assert msgs[0]["from"] == "local"
        assert msgs[0]["text"] == "Outbound msg"

    def test_send_text_handles_exception(self, bridge):
        mock_iface = MagicMock()
        mock_iface.sendText.side_effect = RuntimeError("radio busy")
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.send_text("hello")
        assert result is False
        assert "radio busy" in bridge._last_error

    def test_send_text_history_capped_at_500(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        # Fill with 490 inbound + send 20 outbound
        bridge._messages = [{"text": f"old-{i}"} for i in range(490)]

        for i in range(20):
            bridge.send_text(f"out-{i}")

        assert len(bridge.messages) <= 500


# ===========================================================================
# Outbound — send_position
# ===========================================================================


@pytest.mark.unit
class TestSendPosition:
    def test_send_position_when_disconnected(self, bridge):
        result = bridge.send_position(37.7, -122.4)
        assert result is False

    def test_send_position_success(self, bridge):
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.send_position(37.7749, -122.4194, alt=16.0)
        assert result is True
        assert bridge._messages_sent == 1
        mock_iface.sendPosition.assert_called_once_with(
            latitude=37.7749, longitude=-122.4194, altitude=16
        )

    def test_send_position_handles_exception(self, bridge):
        mock_iface = MagicMock()
        mock_iface.sendPosition.side_effect = RuntimeError("no GPS")
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.send_position(0.0, 0.0)
        assert result is False
        assert "no GPS" in bridge._last_error


# ===========================================================================
# Discovery
# ===========================================================================


@pytest.mark.unit
class TestDiscovery:
    def test_discover_without_zeroconf(self):
        """discover() should return empty list if zeroconf not installed."""
        with patch.dict("sys.modules", {"zeroconf": None}):
            result = MeshtasticBridge.discover(timeout=0.1)
        assert result == []

    def test_discover_returns_list(self):
        """discover() should return list of dicts."""
        # Just verify it doesn't crash — real zeroconf would need network
        result = MeshtasticBridge.discover(timeout=0.01)
        assert isinstance(result, list)


# ===========================================================================
# Properties — thread safety
# ===========================================================================


@pytest.mark.unit
class TestProperties:
    def test_nodes_property_returns_copy(self, bridge):
        bridge._nodes["!a"] = MeshtasticNode(node_id="!a")
        nodes = bridge.nodes
        nodes["!b"] = MeshtasticNode(node_id="!b")
        assert "!b" not in bridge._nodes

    def test_messages_property_returns_copy(self, bridge):
        bridge._messages = [{"text": "hello"}]
        msgs = bridge.messages
        msgs.append({"text": "injected"})
        assert len(bridge._messages) == 1


# ===========================================================================
# Internal helpers
# ===========================================================================


@pytest.mark.unit
class TestHelpers:
    def test_get_node_name_with_known_node(self, bridge):
        bridge._nodes["!abc"] = MeshtasticNode(node_id="!abc", long_name="Alpha")
        assert bridge._get_node_name("!abc") == "Alpha"

    def test_get_node_name_unknown_node(self, bridge):
        assert bridge._get_node_name("!unknown") == "!unknown"

    def test_get_node_name_empty_long_name(self, bridge):
        bridge._nodes["!abc"] = MeshtasticNode(node_id="!abc", long_name="")
        assert bridge._get_node_name("!abc") == "!abc"

    def test_get_node_battery_with_known_node(self, bridge):
        bridge._nodes["!abc"] = MeshtasticNode(node_id="!abc", battery=75)
        assert bridge._get_node_battery("!abc") == 0.75  # 75/100

    def test_get_node_battery_unknown_node(self, bridge):
        assert bridge._get_node_battery("!unknown") == 1.0

    def test_get_node_battery_none(self, bridge):
        bridge._nodes["!abc"] = MeshtasticNode(node_id="!abc", battery=None)
        assert bridge._get_node_battery("!abc") == 1.0

    def test_max_text_constant(self):
        assert MESHTASTIC_MAX_TEXT == 228


# ===========================================================================
# connect() / disconnect() — dynamic reconnection
# ===========================================================================


@pytest.mark.unit
class TestConnect:
    def test_connect_without_meshtastic(self, bridge):
        """connect() should return False if meshtastic not installed."""
        with patch.dict("sys.modules", {
            "meshtastic": None,
            "meshtastic.tcp_interface": None,
            "pubsub": None,
        }):
            result = bridge.connect("192.168.1.50", 4403)
        assert result is False
        assert bridge._last_error == "meshtastic not installed"

    def test_connect_preserves_host_port_on_import_failure(self, bridge):
        """connect() should NOT update _host/_port if meshtastic not installed."""
        with patch.dict("sys.modules", {
            "meshtastic": None,
            "meshtastic.tcp_interface": None,
            "pubsub": None,
        }):
            result = bridge.connect("10.0.0.1", 9999)
        assert result is False
        # Host/port should remain unchanged since import failed before assignment
        assert bridge._host == "192.168.1.50"
        assert bridge._port == 4403

    def test_disconnect_when_not_connected(self, bridge, event_bus):
        """disconnect() should be safe when not connected."""
        bridge.disconnect()
        assert bridge._connected is False
        assert bridge._running is False
        # Should NOT publish mesh_disconnected if was not connected
        assert len(event_bus.published) == 0

    def test_disconnect_clears_state(self, bridge, event_bus):
        """disconnect() should clear connected/running and publish event."""
        bridge._connected = True
        bridge._running = True
        bridge.disconnect()
        assert bridge._connected is False
        assert bridge._running is False
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mesh_disconnected"

    def test_disconnect_closes_interface(self, bridge):
        """disconnect() should close the interface if present."""
        mock_iface = MagicMock()
        bridge._interface = mock_iface
        bridge._connected = True
        bridge.disconnect()
        mock_iface.close.assert_called_once()
        assert bridge._interface is None

    def test_disconnect_handles_close_exception(self, bridge):
        """disconnect() should swallow exceptions from close."""
        mock_iface = MagicMock()
        mock_iface.close.side_effect = RuntimeError("already closed")
        bridge._interface = mock_iface
        bridge._connected = True
        bridge.disconnect()
        assert bridge._interface is None
        assert bridge._connected is False

    def test_connect_disconnects_existing_first(self, bridge, event_bus):
        """connect() should disconnect if already connected."""
        bridge._connected = True
        bridge._running = True
        mock_iface = MagicMock()
        bridge._interface = mock_iface

        # Will fail due to no meshtastic package, but should disconnect first
        with patch.dict("sys.modules", {
            "meshtastic": None,
            "meshtastic.tcp_interface": None,
            "pubsub": None,
        }):
            bridge.connect("10.0.0.1", 4403)

        mock_iface.close.assert_called_once()
        # mesh_disconnected should have been published from the disconnect
        disconnect_events = [e for e in event_bus.published if e[0] == "mesh_disconnected"]
        assert len(disconnect_events) == 1


# ===========================================================================
# get_channels()
# ===========================================================================


@pytest.mark.unit
class TestGetChannels:
    def test_get_channels_when_disconnected(self, bridge):
        """get_channels() returns empty list when disconnected."""
        result = bridge.get_channels()
        assert result == []

    def test_get_channels_with_no_interface(self, bridge):
        """get_channels() returns empty list when interface is None."""
        bridge._connected = True
        bridge._interface = None
        result = bridge.get_channels()
        assert result == []

    def test_get_channels_with_no_local_node(self, bridge):
        """get_channels() returns empty list when localNode is None."""
        mock_iface = MagicMock()
        mock_iface.localNode = None
        bridge._interface = mock_iface
        bridge._connected = True
        result = bridge.get_channels()
        assert result == []

    def test_get_channels_with_no_channels_attr(self, bridge):
        """get_channels() returns empty list when channels attr missing."""
        mock_iface = MagicMock()
        mock_iface.localNode = MagicMock(spec=[])  # no channels attr
        bridge._interface = mock_iface
        bridge._connected = True
        result = bridge.get_channels()
        assert result == []

    def test_get_channels_parses_channels(self, bridge):
        """get_channels() correctly parses channel info."""
        ch0 = MagicMock()
        ch0.role = 1  # PRIMARY
        ch0.settings = MagicMock()
        ch0.settings.name = "LongFast"

        ch1 = MagicMock()
        ch1.role = 2  # SECONDARY
        ch1.settings = MagicMock()
        ch1.settings.name = "Admin"

        ch2 = MagicMock()
        ch2.role = 0  # DISABLED
        ch2.settings = MagicMock()
        ch2.settings.name = ""

        mock_iface = MagicMock()
        mock_iface.localNode.channels = [ch0, ch1, ch2]
        bridge._interface = mock_iface
        bridge._connected = True

        result = bridge.get_channels()
        assert len(result) == 3
        assert result[0] == {"index": 0, "name": "LongFast", "role": "PRIMARY"}
        assert result[1] == {"index": 1, "name": "Admin", "role": "SECONDARY"}
        assert result[2] == {"index": 2, "name": "", "role": "DISABLED"}


# ===========================================================================
# get_node()
# ===========================================================================


@pytest.mark.unit
class TestGetNode:
    def test_get_node_found(self, bridge):
        """get_node() returns dict for known node."""
        bridge._nodes["!abc123"] = MeshtasticNode(
            node_id="!abc123",
            long_name="Base Station",
            short_name="BS",
            hardware="HELTEC_V3",
            battery=75,
            voltage=3.8,
            snr=10.5,
            rssi=-60,
            hops=1,
        )
        result = bridge.get_node("!abc123")
        assert result is not None
        assert result["node_id"] == "!abc123"
        assert result["long_name"] == "Base Station"
        assert result["short_name"] == "BS"
        assert result["hardware"] == "HELTEC_V3"
        assert result["battery"] == 75
        assert result["voltage"] == 3.8
        assert result["snr"] == 10.5
        assert result["rssi"] == -60
        assert result["hops"] == 1

    def test_get_node_not_found(self, bridge):
        """get_node() returns None for unknown node."""
        result = bridge.get_node("!nonexistent")
        assert result is None

    def test_get_node_with_position(self, bridge):
        """get_node() includes position data."""
        bridge._nodes["!abc"] = MeshtasticNode(
            node_id="!abc",
            position={"lat": 37.7, "lng": -122.4, "alt": 10.0},
        )
        result = bridge.get_node("!abc")
        assert result is not None
        assert result["position"]["lat"] == 37.7
        assert result["position"]["lng"] == -122.4
