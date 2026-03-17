# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Meshtastic message bridge.

Covers: text message handling, position bridging, telemetry bridging,
outbound send, message history, and node name resolution.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
import os

# Ensure addons path is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "addons", "meshtastic"))

from meshtastic_addon.message_bridge import (
    MAX_MESSAGE_HISTORY,
    MessageBridge,
    MessageType,
    MeshMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    bus.emit = bus.publish  # Alias for backward compat
    return bus


@pytest.fixture
def mock_node_manager():
    nm = MagicMock()
    nm.nodes = {}
    nm.target_tracker = MagicMock()
    nm.target_tracker.update_target = MagicMock()
    return nm


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.interface = MagicMock()
    conn.is_connected = True
    conn.send_text = AsyncMock(return_value=True)
    return conn


@pytest.fixture
def mock_mqtt_bridge():
    mqtt = MagicMock()
    mqtt.publish = MagicMock()
    return mqtt


@pytest.fixture
def bridge(mock_connection, mock_node_manager, mock_event_bus, mock_mqtt_bridge):
    return MessageBridge(
        connection=mock_connection,
        node_manager=mock_node_manager,
        event_bus=mock_event_bus,
        mqtt_bridge=mock_mqtt_bridge,
        site_id="test-site",
    )


# ---------------------------------------------------------------------------
# Mock meshtastic packets
# ---------------------------------------------------------------------------

def make_text_packet(from_id="!aabbccdd", to_id="!ffffffff", text="Hello mesh", channel=0):
    return {
        "fromId": from_id,
        "toId": to_id,
        "channel": channel,
        "decoded": {
            "portnum": "TEXT_MESSAGE_APP",
            "text": text,
        },
    }


def make_position_packet(from_id="!aabbccdd", lat_i=408500000, lng_i=-739400000, altitude=50, speed=3, heading=18000000):
    return {
        "fromId": from_id,
        "decoded": {
            "portnum": "POSITION_APP",
            "position": {
                "latitudeI": lat_i,
                "longitudeI": lng_i,
                "altitude": altitude,
                "groundSpeed": speed,
                "groundTrack": heading,
            },
        },
    }


def make_telemetry_packet(from_id="!aabbccdd", battery=85, voltage=3.7, ch_util=12.5, air_util=5.2, uptime=3600):
    return {
        "fromId": from_id,
        "decoded": {
            "portnum": "TELEMETRY_APP",
            "telemetry": {
                "deviceMetrics": {
                    "batteryLevel": battery,
                    "voltage": voltage,
                    "channelUtilization": ch_util,
                    "airUtilTx": air_util,
                    "uptimeSeconds": uptime,
                },
            },
        },
    }


def make_nodeinfo_packet(from_id="!aabbccdd", long_name="TestNode", short_name="TN", hw_model="TBEAM"):
    return {
        "fromId": from_id,
        "decoded": {
            "portnum": "NODEINFO_APP",
            "user": {
                "longName": long_name,
                "shortName": short_name,
                "hwModel": hw_model,
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests: Text message handling
# ---------------------------------------------------------------------------

class TestTextMessages:
    def test_receive_text_message(self, bridge, mock_event_bus, mock_mqtt_bridge):
        packet = make_text_packet(text="Hello world")
        bridge._on_receive(packet)

        assert bridge.messages_received == 1
        assert len(bridge._messages) == 1

        msg = bridge._messages[0]
        assert msg.text == "Hello world"
        assert msg.sender_id == "!aabbccdd"
        assert msg.type == MessageType.TEXT
        assert msg.channel == 0

        # Event bus was called
        mock_event_bus.publish.assert_called()
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == "meshtastic:message_received"

        # MQTT was published
        mock_mqtt_bridge.publish.assert_called()

    def test_receive_text_with_destination(self, bridge):
        packet = make_text_packet(to_id="!11223344", text="DM")
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert msg.destination == "!11223344"

    def test_receive_text_with_channel(self, bridge):
        packet = make_text_packet(channel=3, text="Channel 3 msg")
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert msg.channel == 3

    def test_resolve_node_name(self, bridge, mock_node_manager):
        mock_node_manager.nodes["!aabbccdd"] = {"long_name": "BaseStation"}
        packet = make_text_packet(text="Named sender")
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert msg.sender_name == "BaseStation"

    def test_resolve_unknown_node_name(self, bridge):
        packet = make_text_packet(from_id="!unknown", text="Unknown")
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert msg.sender_name == "!unknown"


# ---------------------------------------------------------------------------
# Tests: Position bridging
# ---------------------------------------------------------------------------

class TestPositionBridging:
    def test_position_report_integer_format(self, bridge, mock_node_manager):
        packet = make_position_packet(lat_i=408500000, lng_i=-739400000)
        bridge._on_receive(packet)

        assert bridge.position_reports == 1
        msg = bridge._messages[0]
        assert msg.type == MessageType.POSITION
        assert abs(msg.lat - 40.85) < 0.001
        assert abs(msg.lng - (-73.94)) < 0.001
        assert msg.altitude == 50
        assert msg.speed == 3

    def test_position_updates_node_manager(self, bridge, mock_node_manager):
        packet = make_position_packet(from_id="!node1", lat_i=408500000, lng_i=-739400000)
        bridge._on_receive(packet)

        assert "!node1" in mock_node_manager.nodes
        node = mock_node_manager.nodes["!node1"]
        assert abs(node["lat"] - 40.85) < 0.001
        assert abs(node["lng"] - (-73.94)) < 0.001

    def test_position_updates_target_tracker(self, bridge, mock_node_manager):
        packet = make_position_packet(from_id="!node1")
        bridge._on_receive(packet)

        mock_node_manager.target_tracker.update_target.assert_called_once()
        target = mock_node_manager.target_tracker.update_target.call_args[0][0]
        assert target["target_id"] == "mesh_node1"
        assert target["source"] == "mesh"
        assert target["alliance"] == "friendly"

    def test_position_with_heading_conversion(self, bridge):
        # groundTrack in 1e-5 degrees (e.g., 18000000 = 180.0 degrees)
        packet = make_position_packet(heading=18000000)
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert abs(msg.heading - 180.0) < 0.1

    def test_position_float_passthrough(self, bridge):
        """If lat/lng are already floats, don't re-scale."""
        packet = {
            "fromId": "!node2",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {
                    "latitudeI": 40.85,
                    "longitudeI": -73.94,
                },
            },
        }
        bridge._on_receive(packet)

        msg = bridge._messages[0]
        assert abs(msg.lat - 40.85) < 0.001

    def test_position_missing_lat_lng_ignored(self, bridge):
        packet = {
            "fromId": "!node3",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {},
            },
        }
        bridge._on_receive(packet)
        assert bridge.position_reports == 0
        assert len(bridge._messages) == 0

    def test_position_emits_event(self, bridge, mock_event_bus):
        packet = make_position_packet()
        bridge._on_receive(packet)

        call_topics = [c[0][0] for c in mock_event_bus.publish.call_args_list]
        assert "meshtastic:position_received" in call_topics


# ---------------------------------------------------------------------------
# Tests: Telemetry bridging
# ---------------------------------------------------------------------------

class TestTelemetryBridging:
    def test_telemetry_report(self, bridge, mock_event_bus):
        packet = make_telemetry_packet(battery=85, voltage=3.7, ch_util=12.5, air_util=5.2)
        bridge._on_receive(packet)

        assert bridge.telemetry_reports == 1
        msg = bridge._messages[0]
        assert msg.type == MessageType.TELEMETRY
        assert msg.battery == 85
        assert msg.voltage == 3.7
        assert msg.channel_util == 12.5
        assert msg.air_util == 5.2

    def test_telemetry_updates_node_manager(self, bridge, mock_node_manager):
        packet = make_telemetry_packet(from_id="!node1", battery=72, uptime=7200)
        bridge._on_receive(packet)

        node = mock_node_manager.nodes["!node1"]
        assert node["battery"] == 72
        assert node["uptime"] == 7200

    def test_telemetry_emits_event(self, bridge, mock_event_bus):
        packet = make_telemetry_packet()
        bridge._on_receive(packet)

        call_topics = [c[0][0] for c in mock_event_bus.publish.call_args_list]
        assert "meshtastic:telemetry_received" in call_topics

    def test_telemetry_publishes_mqtt(self, bridge, mock_mqtt_bridge):
        packet = make_telemetry_packet(from_id="!node1")
        bridge._on_receive(packet)

        mock_mqtt_bridge.publish.assert_called()
        topic = mock_mqtt_bridge.publish.call_args[0][0]
        assert "meshtastic/!node1/telemetry" in topic


# ---------------------------------------------------------------------------
# Tests: Node info
# ---------------------------------------------------------------------------

class TestNodeInfo:
    def test_nodeinfo_updates_node_manager(self, bridge, mock_node_manager):
        packet = make_nodeinfo_packet(from_id="!node1", long_name="Alpha", short_name="AL")
        bridge._on_receive(packet)

        node = mock_node_manager.nodes["!node1"]
        assert node["long_name"] == "Alpha"
        assert node["short_name"] == "AL"
        assert node["hw_model"] == "TBEAM"


# ---------------------------------------------------------------------------
# Tests: Outbound messaging
# ---------------------------------------------------------------------------

class TestOutboundMessaging:
    @pytest.mark.asyncio
    async def test_send_text_broadcast(self, bridge, mock_connection, mock_event_bus):
        ok = await bridge.send_text("Test broadcast")

        assert ok is True
        assert bridge.messages_sent == 1
        mock_connection.send_text.assert_awaited_once_with("Test broadcast", destination=None)

        # Recorded in history
        msg = bridge._messages[0]
        assert msg.text == "Test broadcast"
        assert msg.sender_id == "local"
        assert msg.destination == "broadcast"

    @pytest.mark.asyncio
    async def test_send_text_direct(self, bridge, mock_connection):
        ok = await bridge.send_text("DM", destination="!11223344")

        assert ok is True
        mock_connection.send_text.assert_awaited_once_with("DM", destination="!11223344")

        msg = bridge._messages[0]
        assert msg.destination == "!11223344"

    @pytest.mark.asyncio
    async def test_send_fails_no_connection(self):
        bridge = MessageBridge(connection=None)
        ok = await bridge.send_text("No conn")

        assert ok is False
        assert bridge.messages_sent == 0

    @pytest.mark.asyncio
    async def test_send_records_event(self, bridge, mock_event_bus):
        await bridge.send_text("Event test")

        call_topics = [c[0][0] for c in mock_event_bus.publish.call_args_list]
        assert "meshtastic:message_sent" in call_topics


# ---------------------------------------------------------------------------
# Tests: Message history
# ---------------------------------------------------------------------------

class TestMessageHistory:
    def test_get_messages_empty(self, bridge):
        msgs = bridge.get_messages()
        assert msgs == []

    def test_get_messages_returns_dicts(self, bridge):
        packet = make_text_packet(text="Msg 1")
        bridge._on_receive(packet)

        msgs = bridge.get_messages()
        assert len(msgs) == 1
        assert isinstance(msgs[0], dict)
        assert msgs[0]["text"] == "Msg 1"

    def test_get_messages_limit(self, bridge):
        for i in range(10):
            bridge._on_receive(make_text_packet(text=f"Msg {i}"))

        msgs = bridge.get_messages(limit=3)
        assert len(msgs) == 3
        # Newest 3
        assert msgs[-1]["text"] == "Msg 9"

    def test_get_messages_filter_type(self, bridge):
        bridge._on_receive(make_text_packet(text="Text"))
        bridge._on_receive(make_position_packet())
        bridge._on_receive(make_telemetry_packet())

        text_msgs = bridge.get_messages(msg_type="text")
        assert len(text_msgs) == 1
        assert text_msgs[0]["type"] == "text"

        pos_msgs = bridge.get_messages(msg_type="position")
        assert len(pos_msgs) == 1

    def test_get_messages_since(self, bridge):
        bridge._on_receive(make_text_packet(text="Old"))
        cutoff = time.time() + 0.01
        # Tiny sleep to ensure timestamp difference
        import time as _time
        _time.sleep(0.02)
        bridge._on_receive(make_text_packet(text="New"))

        msgs = bridge.get_messages(since=cutoff)
        assert len(msgs) == 1
        assert msgs[0]["text"] == "New"

    def test_history_capped_at_max(self, bridge):
        for i in range(MAX_MESSAGE_HISTORY + 50):
            bridge._on_receive(make_text_packet(text=f"Msg {i}"))

        assert len(bridge._messages) == MAX_MESSAGE_HISTORY
        # Oldest should be gone
        assert bridge._messages[0].text == "Msg 50"

    def test_get_stats(self, bridge):
        bridge._on_receive(make_text_packet(text="Text"))
        bridge._on_receive(make_position_packet())
        bridge._on_receive(make_telemetry_packet())

        stats = bridge.get_stats()
        assert stats["messages_received"] == 1
        assert stats["position_reports"] == 1
        assert stats["telemetry_reports"] == 1
        assert stats["history_size"] == 3


# ---------------------------------------------------------------------------
# Tests: MeshMessage dataclass
# ---------------------------------------------------------------------------

class TestMeshMessage:
    def test_to_dict_minimal(self):
        msg = MeshMessage(
            sender_id="!abc",
            sender_name="Test",
            text="Hello",
            timestamp=1000.0,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "!abc"
        assert d["text"] == "Hello"
        assert d["timestamp"] == 1000.0
        assert "lat" not in d
        assert "battery" not in d

    def test_to_dict_with_position(self):
        msg = MeshMessage(
            sender_id="!abc",
            sender_name="Test",
            text="Pos",
            timestamp=1000.0,
            lat=40.85,
            lng=-73.94,
            altitude=50,
            speed=3.0,
        )
        d = msg.to_dict()
        assert d["lat"] == 40.85
        assert d["lng"] == -73.94
        assert d["altitude"] == 50
        assert d["speed"] == 3.0

    def test_to_dict_with_telemetry(self):
        msg = MeshMessage(
            sender_id="!abc",
            sender_name="Test",
            text="Tel",
            timestamp=1000.0,
            battery=85,
            voltage=3.7,
        )
        d = msg.to_dict()
        assert d["battery"] == 85
        assert d["voltage"] == 3.7


# ---------------------------------------------------------------------------
# Tests: Dispatch routing
# ---------------------------------------------------------------------------

class TestPacketDispatch:
    def test_unknown_portnum_ignored(self, bridge):
        packet = {"fromId": "!x", "decoded": {"portnum": "UNKNOWN_APP"}}
        bridge._on_receive(packet)

        assert bridge.messages_received == 0
        assert len(bridge._messages) == 0

    def test_empty_packet_ignored(self, bridge):
        bridge._on_receive(None)
        bridge._on_receive({})

        assert bridge.messages_received == 0

    def test_legacy_callback(self, bridge):
        packet = make_text_packet(text="Legacy")
        bridge._on_receive_legacy(packet)

        assert bridge.messages_received == 1
        assert bridge._messages[0].text == "Legacy"


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_register_without_interface(self, mock_node_manager, mock_event_bus):
        """Bridge should work in passive mode without a connected interface."""
        conn = MagicMock()
        conn.interface = None
        bridge = MessageBridge(
            connection=conn,
            node_manager=mock_node_manager,
            event_bus=mock_event_bus,
        )
        bridge.register_callbacks()
        assert not bridge._registered

    def test_register_without_pubsub(self, bridge):
        """If pubsub not installed, should try legacy callback."""
        with patch.dict("sys.modules", {"pubsub": None}):
            # This should not raise
            bridge.register_callbacks()

    def test_unregister_when_not_registered(self, bridge):
        """Should be safe to unregister when not registered."""
        bridge._registered = False
        bridge.unregister_callbacks()  # Should not raise


# ---------------------------------------------------------------------------
# Tests: MQTT publishing
# ---------------------------------------------------------------------------

class TestMQTTPublishing:
    def test_text_publishes_to_correct_topic(self, bridge, mock_mqtt_bridge):
        packet = make_text_packet(from_id="!node1")
        bridge._on_receive(packet)

        topic = mock_mqtt_bridge.publish.call_args[0][0]
        assert topic == "tritium/test-site/meshtastic/!node1/messages"

    def test_position_publishes_to_correct_topic(self, bridge, mock_mqtt_bridge):
        packet = make_position_packet(from_id="!node2")
        bridge._on_receive(packet)

        topic = mock_mqtt_bridge.publish.call_args[0][0]
        assert topic == "tritium/test-site/meshtastic/!node2/position"

    def test_no_mqtt_bridge_no_error(self):
        """Bridge should work fine without MQTT."""
        bridge = MessageBridge(mqtt_bridge=None)
        packet = make_text_packet()
        bridge._on_receive(packet)  # Should not raise
        assert bridge.messages_received == 1
