# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine.comms.meshcore_bridge.MeshCoreBridge.

TDD — written before implementation.
"""

from __future__ import annotations

import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.meshcore_bridge import MeshCoreBridge, MeshCoreNode


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
    return MeshCoreBridge(
        event_bus=event_bus,
        target_tracker=tracker,
        serial_port="/dev/ttyUSB0",
    )


# ===========================================================================
# Init / Config
# ===========================================================================


@pytest.mark.unit
class TestInit:
    def test_stores_config(self, bridge):
        assert bridge._serial_port == "/dev/ttyUSB0"

    def test_initial_state(self, bridge):
        assert bridge.connected is False
        assert bridge._running is False
        assert bridge._serial is None
        assert bridge._frames_received == 0
        assert bridge._last_error == ""

    def test_default_params(self, event_bus, tracker):
        b = MeshCoreBridge(event_bus=event_bus, target_tracker=tracker)
        assert b._serial_port == ""

    def test_meshcore_node_dataclass(self):
        node = MeshCoreNode(
            node_id="mc_001",
            name="Relay Alpha",
            hardware="meshcore",
        )
        assert node.node_id == "mc_001"
        assert node.name == "Relay Alpha"
        assert node.hardware == "meshcore"
        assert node.position is None
        assert node.battery is None
        assert node.rssi is None


# ===========================================================================
# Graceful import failure
# ===========================================================================


@pytest.mark.unit
class TestGracefulImport:
    def test_bridge_creates_without_serial(self, event_bus, tracker):
        """MeshCoreBridge should instantiate even if serial package is missing."""
        b = MeshCoreBridge(
            event_bus=event_bus,
            target_tracker=tracker,
            serial_port="/dev/ttyUSB0",
        )
        assert b is not None
        assert b.connected is False

    def test_start_without_serial_package(self, bridge):
        """start() should gracefully handle missing serial package."""
        with patch.dict("sys.modules", {"serial": None}):
            bridge.start()
        assert bridge._running is False
        assert bridge._last_error == "pyserial not installed"


# ===========================================================================
# Stats property
# ===========================================================================


@pytest.mark.unit
class TestStats:
    def test_stats_returns_all_fields(self, bridge):
        s = bridge.stats
        assert s["connected"] is False
        assert s["serial_port"] == "/dev/ttyUSB0"
        assert s["frames_received"] == 0
        assert s["nodes_discovered"] == 0
        assert s["last_error"] == ""

    def test_stats_reflects_changes(self, bridge):
        bridge._frames_received = 42
        bridge._last_error = "timeout"
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001")
        s = bridge.stats
        assert s["frames_received"] == 42
        assert s["last_error"] == "timeout"
        assert s["nodes_discovered"] == 1


# ===========================================================================
# start() / stop()
# ===========================================================================


@pytest.mark.unit
class TestStartStop:
    def test_start_idempotent(self, bridge):
        """Calling start() twice does nothing the second time."""
        bridge._running = True
        bridge.start()
        assert bridge._serial is None

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

    def test_stop_closes_serial(self, bridge):
        mock_serial = MagicMock()
        bridge._serial = mock_serial
        bridge._running = True
        bridge.stop()
        mock_serial.close.assert_called_once()
        assert bridge._serial is None

    def test_stop_handles_close_exception(self, bridge):
        """stop() should swallow exceptions from close."""
        mock_serial = MagicMock()
        mock_serial.close.side_effect = RuntimeError("already closed")
        bridge._serial = mock_serial
        bridge._running = True
        bridge.stop()
        assert bridge._serial is None
        assert bridge._running is False


# ===========================================================================
# Frame processing — node discovery
# ===========================================================================


@pytest.mark.unit
class TestNodeDiscovery:
    def test_node_discovery_publishes_event(self, bridge, event_bus):
        """Processing a node discovery frame should publish to EventBus."""
        frame = {
            "type": "node_info",
            "node_id": "mc_001",
            "name": "Relay Alpha",
            "hardware": "meshcore_v1",
        }
        bridge.process_frame(frame)

        events = [e for e in event_bus.published if e[0] == "meshcore:node_discovered"]
        assert len(events) == 1
        data = events[0][1]
        assert data["node_id"] == "mc_001"
        assert data["name"] == "Relay Alpha"

    def test_node_stored_internally(self, bridge):
        frame = {
            "type": "node_info",
            "node_id": "mc_002",
            "name": "Mobile Unit",
            "hardware": "meshcore_v2",
        }
        bridge.process_frame(frame)
        assert "mc_002" in bridge._nodes
        node = bridge._nodes["mc_002"]
        assert node.name == "Mobile Unit"
        assert node.hardware == "meshcore_v2"

    def test_node_registered_in_tracker(self, bridge, tracker):
        """Discovered node should appear in TargetTracker."""
        frame = {
            "type": "node_info",
            "node_id": "mc_003",
            "name": "Sensor Node",
            "hardware": "meshcore_v1",
        }
        bridge.process_frame(frame)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["target_id"] == "meshcore_mc_003"
        assert update["alliance"] == "friendly"
        assert update["asset_type"] == "mesh_radio"
        assert update["status"] == "active"


# ===========================================================================
# Frame processing — position update
# ===========================================================================


@pytest.mark.unit
class TestPositionUpdate:
    def test_position_update_converts_coords(self, bridge, tracker):
        """Position updates should convert lat/lng to local coordinates."""
        # First register the node
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        with patch("engine.tactical.geo.latlng_to_local", return_value=(15.0, 25.0, 0.0)):
            frame = {
                "type": "position",
                "node_id": "mc_001",
                "lat": 37.7749,
                "lng": -122.4194,
                "alt": 16.0,
            }
            bridge.process_frame(frame)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["position"]["x"] == 15.0
        assert update["position"]["y"] == 25.0

    def test_position_publishes_event(self, bridge, event_bus):
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        with patch("engine.tactical.geo.latlng_to_local", return_value=(5.0, 10.0, 0.0)):
            frame = {
                "type": "position",
                "node_id": "mc_001",
                "lat": 37.7749,
                "lng": -122.4194,
            }
            bridge.process_frame(frame)

        events = [e for e in event_bus.published if e[0] == "meshcore:position_update"]
        assert len(events) == 1
        data = events[0][1]
        assert data["node_id"] == "mc_001"
        assert data["lat"] == 37.7749
        assert data["local_x"] == 5.0
        assert data["local_y"] == 10.0

    def test_position_updates_node_state(self, bridge):
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        with patch("engine.tactical.geo.latlng_to_local", return_value=(0.0, 0.0, 0.0)):
            frame = {
                "type": "position",
                "node_id": "mc_001",
                "lat": 37.7,
                "lng": -122.4,
            }
            bridge.process_frame(frame)

        node = bridge._nodes["mc_001"]
        assert node.position is not None
        assert node.position["lat"] == 37.7

    def test_position_skips_zero_coords(self, bridge, tracker):
        """Position at (0,0) should be silently ignored."""
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        frame = {
            "type": "position",
            "node_id": "mc_001",
            "lat": 0.0,
            "lng": 0.0,
        }
        bridge.process_frame(frame)
        assert len(tracker.sim_updates) == 0


# ===========================================================================
# Protocol metadata
# ===========================================================================


@pytest.mark.unit
class TestProtocolMetadata:
    def test_protocol_metadata_on_node_discovery(self, bridge, tracker):
        """Discovered node should have mesh_protocol='meshcore' in tracker."""
        frame = {
            "type": "node_info",
            "node_id": "mc_010",
            "name": "Protocol Test",
        }
        bridge.process_frame(frame)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["asset_type"] == "mesh_radio"
        assert update.get("metadata", {}).get("mesh_protocol") == "meshcore"

    def test_protocol_metadata_on_position(self, bridge, tracker):
        """Position updates should also carry meshcore metadata."""
        bridge._nodes["mc_010"] = MeshCoreNode(node_id="mc_010", name="Test")

        with patch("engine.tactical.geo.latlng_to_local", return_value=(1.0, 2.0, 0.0)):
            frame = {
                "type": "position",
                "node_id": "mc_010",
                "lat": 37.7,
                "lng": -122.4,
            }
            bridge.process_frame(frame)

        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update.get("metadata", {}).get("mesh_protocol") == "meshcore"


# ===========================================================================
# Text message handling
# ===========================================================================


@pytest.mark.unit
class TestTextMessage:
    def test_text_message_publishes_event(self, bridge, event_bus):
        frame = {
            "type": "text",
            "node_id": "mc_001",
            "text": "Hello from MeshCore!",
        }
        bridge.process_frame(frame)

        events = [e for e in event_bus.published if e[0] == "meshcore:text_message"]
        assert len(events) == 1
        data = events[0][1]
        assert data["node_id"] == "mc_001"
        assert data["text"] == "Hello from MeshCore!"

    def test_text_message_stored(self, bridge):
        frame = {
            "type": "text",
            "node_id": "mc_001",
            "text": "Test message",
        }
        bridge.process_frame(frame)
        assert len(bridge.messages) == 1
        assert bridge.messages[0]["text"] == "Test message"


# ===========================================================================
# Telemetry handling
# ===========================================================================


@pytest.mark.unit
class TestTelemetry:
    def test_telemetry_updates_battery(self, bridge):
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        frame = {
            "type": "telemetry",
            "node_id": "mc_001",
            "battery": 85,
            "rssi": -70,
        }
        bridge.process_frame(frame)

        node = bridge._nodes["mc_001"]
        assert node.battery == 85
        assert node.rssi == -70

    def test_telemetry_publishes_event(self, bridge, event_bus):
        bridge._nodes["mc_001"] = MeshCoreNode(node_id="mc_001", name="Test")

        frame = {
            "type": "telemetry",
            "node_id": "mc_001",
            "battery": 50,
        }
        bridge.process_frame(frame)

        events = [e for e in event_bus.published if e[0] == "meshcore:telemetry"]
        assert len(events) == 1


# ===========================================================================
# Properties — thread safety
# ===========================================================================


@pytest.mark.unit
class TestProperties:
    def test_nodes_property_returns_copy(self, bridge):
        bridge._nodes["mc_a"] = MeshCoreNode(node_id="mc_a")
        nodes = bridge.nodes
        nodes["mc_b"] = MeshCoreNode(node_id="mc_b")
        assert "mc_b" not in bridge._nodes

    def test_messages_property_returns_copy(self, bridge):
        bridge._messages = [{"text": "hello"}]
        msgs = bridge.messages
        msgs.append({"text": "injected"})
        assert len(bridge._messages) == 1
