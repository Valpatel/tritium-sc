"""Unit tests for amy.mqtt_bridge.MQTTBridge."""

from __future__ import annotations

import json
import queue
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from amy.mqtt_bridge import MQTTBridge


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
        self.detections: list[dict] = []
        self.sim_updates: list[dict] = []

    def update_from_detection(self, data: dict) -> None:
        self.detections.append(data)

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)


def _make_msg(topic: str, payload: dict) -> MagicMock:
    """Create a mock MQTT message with the given topic and JSON payload."""
    msg = MagicMock()
    msg.topic = topic
    msg.payload = json.dumps(payload).encode("utf-8")
    return msg


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
    return MQTTBridge(
        event_bus=event_bus,
        target_tracker=tracker,
        site_id="home",
        broker_host="192.168.1.100",
        broker_port=1883,
        username="admin",
        password="secret",
    )


# ===========================================================================
# Init / Config
# ===========================================================================


@pytest.mark.unit
class TestInit:
    def test_stores_config(self, bridge):
        assert bridge._site == "home"
        assert bridge._broker_host == "192.168.1.100"
        assert bridge._broker_port == 1883
        assert bridge._username == "admin"
        assert bridge._password == "secret"

    def test_initial_state(self, bridge):
        assert bridge.connected is False
        assert bridge._running is False
        assert bridge._client is None
        assert bridge._messages_received == 0
        assert bridge._messages_published == 0
        assert bridge._last_error == ""

    def test_default_params(self, event_bus, tracker):
        b = MQTTBridge(event_bus=event_bus, target_tracker=tracker)
        assert b._site == "home"
        assert b._broker_host == "localhost"
        assert b._broker_port == 1883
        assert b._username == ""
        assert b._password == ""


# ===========================================================================
# Stats property
# ===========================================================================


@pytest.mark.unit
class TestStats:
    def test_stats_returns_all_fields(self, bridge):
        s = bridge.stats
        assert s["connected"] is False
        assert s["broker"] == "192.168.1.100:1883"
        assert s["site_id"] == "home"
        assert s["messages_received"] == 0
        assert s["messages_published"] == 0
        assert s["last_error"] == ""

    def test_stats_reflects_counter_changes(self, bridge):
        bridge._messages_received = 42
        bridge._messages_published = 7
        bridge._last_error = "some error"
        s = bridge.stats
        assert s["messages_received"] == 42
        assert s["messages_published"] == 7
        assert s["last_error"] == "some error"


# ===========================================================================
# start() / stop()
# ===========================================================================


def _make_paho_mock(mock_client: MagicMock | None = None) -> dict:
    """Build a sys.modules dict that makes ``import paho.mqtt.client`` work.

    Returns a dict suitable for ``patch.dict('sys.modules', ...)``.
    The ``Client`` callable on the fake module returns *mock_client* (or a
    fresh MagicMock if not given).
    """
    if mock_client is None:
        mock_client = MagicMock()
    mqtt_client_mod = MagicMock()
    mqtt_client_mod.Client.return_value = mock_client
    mqtt_mod = MagicMock()
    mqtt_mod.client = mqtt_client_mod
    paho_mod = MagicMock()
    paho_mod.mqtt = mqtt_mod
    return {
        "paho": paho_mod,
        "paho.mqtt": mqtt_mod,
        "paho.mqtt.client": mqtt_client_mod,
    }, mqtt_client_mod, mock_client


@pytest.mark.unit
class TestStartStop:
    def test_start_connects_and_sets_callbacks(self, bridge):
        """start() should create client, set credentials, connect, and loop_start."""
        mock_client = MagicMock()
        modules, mqtt_mod, _ = _make_paho_mock(mock_client)
        with patch.dict("sys.modules", modules):
            bridge.start()

            mqtt_mod.Client.assert_called_once()
            mock_client.username_pw_set.assert_called_once_with("admin", "secret")
            mock_client.connect.assert_called_once_with("192.168.1.100", 1883, keepalive=60)
            mock_client.loop_start.assert_called_once()
            assert bridge._running is True

    def test_start_without_paho_sets_error(self, bridge):
        """start() should gracefully handle missing paho-mqtt."""
        with patch.dict("sys.modules", {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            bridge.start()
        # Module is None -> ImportError during `import paho.mqtt.client as mqtt`
        # The bridge should set the error and not crash
        assert bridge._running is False or bridge._last_error != ""

    def test_start_idempotent(self, bridge):
        """Calling start() twice does nothing the second time."""
        bridge._running = True
        modules, _, _ = _make_paho_mock()
        with patch.dict("sys.modules", modules):
            bridge.start()  # should return immediately
        # Client should still be None (no new client created)
        assert bridge._client is None

    def test_start_handles_connection_error(self, bridge):
        """start() should handle connect() raising an exception."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = ConnectionRefusedError("refused")
        modules, _, _ = _make_paho_mock(mock_client)
        with patch.dict("sys.modules", modules):
            bridge.start()

            assert bridge._running is False
            assert "refused" in bridge._last_error

    def test_stop_disconnects_cleanly(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._running = True
        bridge._connected = True

        bridge.stop()

        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()
        assert bridge._client is None
        assert bridge._connected is False
        assert bridge._running is False

    def test_stop_when_not_started(self, bridge):
        """stop() should be safe to call even if never started."""
        bridge.stop()
        assert bridge._connected is False
        assert bridge._running is False

    def test_stop_handles_disconnect_exception(self, bridge):
        """stop() should swallow exceptions from disconnect."""
        mock_client = MagicMock()
        mock_client.disconnect.side_effect = RuntimeError("already disconnected")
        bridge._client = mock_client
        bridge._running = True

        bridge.stop()

        assert bridge._client is None
        assert bridge._running is False

    def test_start_no_credentials(self, event_bus, tracker):
        """start() should not call username_pw_set when username is empty."""
        b = MQTTBridge(event_bus=event_bus, target_tracker=tracker)
        mock_client = MagicMock()
        modules, _, _ = _make_paho_mock(mock_client)
        with patch.dict("sys.modules", modules):
            b.start()

            mock_client.username_pw_set.assert_not_called()


# ===========================================================================
# _on_connect / _on_disconnect callbacks
# ===========================================================================


@pytest.mark.unit
class TestConnectionCallbacks:
    def test_on_connect_success(self, bridge, event_bus):
        mock_client = MagicMock()
        bridge._on_connect(mock_client, None, {}, 0)

        assert bridge._connected is True
        mock_client.subscribe.assert_called_once()
        # Check subscriptions list
        subs = mock_client.subscribe.call_args[0][0]
        assert len(subs) == 7
        topics = {s[0]: s[1] for s in subs}
        assert "tritium/home/cameras/+/detections" in topics
        assert "tritium/home/cameras/+/status" in topics
        assert "tritium/home/robots/+/telemetry" in topics
        assert "tritium/home/robots/+/status" in topics
        assert "tritium/home/robots/+/command/ack" in topics
        assert "tritium/home/sensors/+/events" in topics
        assert "tritium/home/sensors/+/status" in topics
        # High-rate data at QoS 0, status/events/ack at QoS 1
        assert topics["tritium/home/cameras/+/detections"] == 0
        assert topics["tritium/home/robots/+/telemetry"] == 0
        assert topics["tritium/home/cameras/+/status"] == 1
        assert topics["tritium/home/robots/+/status"] == 1
        assert topics["tritium/home/robots/+/command/ack"] == 1
        assert topics["tritium/home/sensors/+/events"] == 1
        assert topics["tritium/home/sensors/+/status"] == 1
        # Check EventBus got the connected event
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mqtt_connected"
        assert event_bus.published[0][1]["broker"] == "192.168.1.100"

    def test_on_connect_failure(self, bridge, event_bus):
        mock_client = MagicMock()
        bridge._on_connect(mock_client, None, {}, 5)

        assert bridge._connected is False
        mock_client.subscribe.assert_not_called()
        assert "rc=5" in bridge._last_error
        # No event should be published on failure
        assert len(event_bus.published) == 0

    def test_on_disconnect_clean(self, bridge, event_bus):
        bridge._connected = True
        bridge._on_disconnect(None, None, 0)

        assert bridge._connected is False
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mqtt_disconnected"

    def test_on_disconnect_unexpected(self, bridge, event_bus):
        bridge._connected = True
        bridge._on_disconnect(None, None, 7)

        assert bridge._connected is False
        assert "Unexpected disconnect" in bridge._last_error
        assert event_bus.published[0][0] == "mqtt_disconnected"


# ===========================================================================
# _on_message routing
# ===========================================================================


@pytest.mark.unit
class TestMessageRouting:
    def test_camera_detection(self, bridge, tracker, event_bus):
        payload = {
            "boxes": [
                {"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.3},
                {"label": "car", "confidence": 0.7, "center_x": 0.1, "center_y": 0.8},
            ]
        }
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 2
        assert tracker.detections[0]["class_name"] == "person"
        assert tracker.detections[0]["source_camera"] == "cam1"
        assert tracker.detections[1]["class_name"] == "car"
        # EventBus should get the detection event
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mqtt_camera_detection"
        assert event_bus.published[0][1]["camera_id"] == "cam1"
        assert event_bus.published[0][1]["detection_count"] == 2

    def test_camera_detection_empty_boxes(self, bridge, tracker, event_bus):
        payload = {"boxes": []}
        msg = _make_msg("tritium/home/cameras/cam2/detections", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.detections) == 0
        assert event_bus.published[0][1]["detection_count"] == 0

    def test_camera_detection_missing_boxes_key(self, bridge, tracker, event_bus):
        payload = {"something_else": True}
        msg = _make_msg("tritium/home/cameras/cam3/detections", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.detections) == 0
        assert event_bus.published[0][1]["detection_count"] == 0

    def test_robot_telemetry(self, bridge, tracker, event_bus):
        payload = {
            "name": "Rover Alpha",
            "position": {"x": 3.5, "y": -2.1},
            "heading": 90.0,
            "speed": 1.2,
            "battery": 0.85,
            "status": "patrolling",
            "asset_type": "rover",
        }
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.sim_updates) == 1
        update = tracker.sim_updates[0]
        assert update["target_id"] == "mqtt_rover1"
        assert update["name"] == "Rover Alpha"
        assert update["alliance"] == "friendly"
        assert update["position"]["x"] == 3.5
        assert update["battery"] == 0.85
        # EventBus
        assert event_bus.published[0][0] == "mqtt_robot_telemetry"
        assert event_bus.published[0][1]["robot_id"] == "rover1"

    def test_robot_telemetry_defaults(self, bridge, tracker):
        """Robot telemetry with minimal payload should use defaults."""
        payload = {}
        msg = _make_msg("tritium/home/robots/rover2/telemetry", payload)
        bridge._on_message(None, None, msg)

        update = tracker.sim_updates[0]
        assert update["target_id"] == "mqtt_rover2"
        assert update["name"] == "rover2"
        assert update["asset_type"] == "rover"
        assert update["battery"] == 1.0
        assert update["status"] == "active"

    def test_sensor_event(self, bridge, event_bus):
        payload = {"event_type": "motion", "zone": "north_fence", "magnitude": 0.8}
        msg = _make_msg("tritium/home/sensors/pir01/events", payload)
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mqtt_sensor_event"
        data = event_bus.published[0][1]
        assert data["sensor_id"] == "pir01"
        assert data["event_type"] == "motion"
        assert data["zone"] == "north_fence"

    def test_sensor_event_default_type(self, bridge, event_bus):
        payload = {"reading": 42}
        msg = _make_msg("tritium/home/sensors/temp01/events", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][1]["event_type"] == "unknown"

    def test_device_status_camera(self, bridge, event_bus):
        payload = {"online": True, "fps": 30}
        msg = _make_msg("tritium/home/cameras/cam1/status", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][0] == "mqtt_device_status"
        data = event_bus.published[0][1]
        assert data["category"] == "camera"
        assert data["device_id"] == "cam1"
        assert data["online"] is True

    def test_device_status_robot(self, bridge, event_bus):
        payload = {"state": "idle"}
        msg = _make_msg("tritium/home/robots/rover1/status", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][0] == "mqtt_device_status"
        assert event_bus.published[0][1]["category"] == "robot"

    def test_device_status_sensor(self, bridge, event_bus):
        payload = {"battery": 0.45}
        msg = _make_msg("tritium/home/sensors/pir01/status", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][0] == "mqtt_device_status"
        assert event_bus.published[0][1]["category"] == "sensor"

    def test_bad_json(self, bridge, tracker, event_bus):
        """Bad JSON should not crash and should increment counter."""
        msg = MagicMock()
        msg.topic = "tritium/home/cameras/cam1/detections"
        msg.payload = b"not-json{{"
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 0
        assert len(event_bus.published) == 0

    def test_bad_unicode(self, bridge, tracker, event_bus):
        """Invalid UTF-8 payload should not crash."""
        msg = MagicMock()
        msg.topic = "tritium/home/cameras/cam1/detections"
        msg.payload = b"\xff\xfe"
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 0

    def test_short_topic(self, bridge, tracker, event_bus):
        """Topic with fewer than 5 parts should be silently ignored."""
        msg = _make_msg("tritium/home/cameras", {"x": 1})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 0
        assert len(event_bus.published) == 0

    def test_very_short_topic(self, bridge, tracker, event_bus):
        """Single-segment topic should be silently ignored."""
        msg = _make_msg("hello", {"x": 1})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(event_bus.published) == 0

    def test_unknown_category(self, bridge, tracker, event_bus):
        """Unknown category in topic should be silently ignored."""
        msg = _make_msg("tritium/home/unknown_cat/dev1/events", {"x": 1})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 0
        assert len(tracker.sim_updates) == 0
        assert len(event_bus.published) == 0

    def test_unknown_action(self, bridge, tracker, event_bus):
        """Known category but unknown action should be silently ignored."""
        msg = _make_msg("tritium/home/cameras/cam1/reboot", {"x": 1})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(event_bus.published) == 0

    def test_handler_exception_is_caught(self, bridge, event_bus):
        """If a handler raises, the exception should be caught gracefully."""
        # Make tracker.update_from_detection raise
        bridge._tracker.update_from_detection = MagicMock(
            side_effect=RuntimeError("boom")
        )
        payload = {"boxes": [{"label": "person", "confidence": 0.9}]}
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)

        # Should not raise
        bridge._on_message(None, None, msg)
        assert bridge._messages_received == 1

    def test_message_counter_increments(self, bridge):
        """Each message should increment the received counter."""
        for i in range(5):
            msg = _make_msg("tritium/home/sensors/s1/events", {"n": i})
            bridge._on_message(None, None, msg)
        assert bridge._messages_received == 5


# ===========================================================================
# Outbound publishing
# ===========================================================================


@pytest.mark.unit
class TestOutboundPublish:
    def test_publish_does_nothing_when_disconnected(self, bridge):
        """_publish should be a no-op when not connected."""
        bridge._connected = False
        bridge._client = MagicMock()
        bridge._publish("some/topic", {"data": 1})

        bridge._client.publish.assert_not_called()
        assert bridge._messages_published == 0

    def test_publish_does_nothing_when_client_is_none(self, bridge):
        """_publish should be a no-op when client is None."""
        bridge._connected = True
        bridge._client = None
        bridge._publish("some/topic", {"data": 1})

        assert bridge._messages_published == 0

    def test_publish_sends_json(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge._publish("tritium/home/test", {"key": "value"})

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == "tritium/home/test"
        payload = json.loads(call_args[0][1])
        assert payload["key"] == "value"
        assert call_args[1]["qos"] == 0
        assert call_args[1]["retain"] is False
        assert bridge._messages_published == 1

    def test_publish_with_qos_and_retain(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge._publish("tritium/home/test", {"key": "value"}, qos=1, retain=True)

        call_args = mock_client.publish.call_args
        assert call_args[1]["qos"] == 1
        assert call_args[1]["retain"] is True

    def test_publish_handles_exception(self, bridge):
        mock_client = MagicMock()
        mock_client.publish.side_effect = RuntimeError("network down")
        bridge._client = mock_client
        bridge._connected = True

        bridge._publish("topic", {"data": 1})
        # Counter should NOT increment on error
        assert bridge._messages_published == 0

    def test_publish_dispatch(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_dispatch("rover1", 10.5, -3.2)

        # Should publish to both robot command and amy/dispatch topics
        assert mock_client.publish.call_count == 2
        # First call: robot command (QoS 1 — commands must be delivered)
        first_call = mock_client.publish.call_args_list[0]
        assert first_call[0][0] == "tritium/home/robots/rover1/command"
        payload1 = json.loads(first_call[0][1])
        assert payload1["command"] == "dispatch"
        assert payload1["x"] == 10.5
        assert payload1["y"] == -3.2
        assert "timestamp" in payload1
        assert first_call[1]["qos"] == 1
        # Second call: amy dispatch (QoS 0 — monitoring/audit)
        second_call = mock_client.publish.call_args_list[1]
        assert second_call[0][0] == "tritium/home/amy/dispatch"
        payload2 = json.loads(second_call[0][1])
        assert payload2["robot_id"] == "rover1"
        assert payload2["destination"] == {"x": 10.5, "y": -3.2}
        assert second_call[1]["qos"] == 0

    def test_publish_patrol(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        waypoints = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
        bridge.publish_patrol("rover2", waypoints)

        mock_client.publish.assert_called_once()
        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/robots/rover2/command"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["command"] == "patrol"
        assert len(payload["waypoints"]) == 3
        assert payload["waypoints"][0] == {"x": 1.0, "y": 2.0}
        assert payload["waypoints"][2] == {"x": 5.0, "y": 6.0}
        assert "timestamp" in payload
        assert mock_client.publish.call_args[1]["qos"] == 1

    def test_publish_recall(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_recall("rover3")

        mock_client.publish.assert_called_once()
        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/robots/rover3/command"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["command"] == "recall"
        assert "timestamp" in payload
        assert mock_client.publish.call_args[1]["qos"] == 1

    def test_publish_alert(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_alert({"level": "high", "message": "Intruder detected"})

        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/amy/alerts"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["level"] == "high"
        assert payload["message"] == "Intruder detected"
        assert "timestamp" in payload
        assert mock_client.publish.call_args[1]["qos"] == 1

    def test_publish_speech(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_speech("Hostile detected in sector 4")

        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/amy/speech"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["text"] == "Hostile detected in sector 4"
        assert "timestamp" in payload

    def test_publish_thought(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_thought("Analyzing movement pattern...")

        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/amy/thoughts"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["text"] == "Analyzing movement pattern..."
        assert "timestamp" in payload

    def test_publish_target_update(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        target = {"target_id": "det_person_1", "alliance": "hostile"}
        bridge.publish_target_update(target)

        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/targets/update"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["target_id"] == "det_person_1"
        assert payload["alliance"] == "hostile"
        assert "timestamp" in payload

    def test_publish_escalation(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_escalation({"level": "elevated", "reason": "Multiple hostiles"})

        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/home/escalation/change"
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["level"] == "elevated"
        assert payload["reason"] == "Multiple hostiles"
        assert "timestamp" in payload
        assert mock_client.publish.call_args[1]["qos"] == 1
        assert mock_client.publish.call_args[1]["retain"] is True

    def test_published_counter_increments(self, bridge):
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_speech("hello")
        bridge.publish_thought("thinking")
        bridge.publish_alert({"msg": "alert"})

        assert bridge._messages_published == 3


# ===========================================================================
# Topic with different site_id
# ===========================================================================


@pytest.mark.unit
class TestSiteId:
    def test_subscribe_uses_site_id(self, event_bus, tracker):
        b = MQTTBridge(event_bus=event_bus, target_tracker=tracker, site_id="hq")
        mock_client = MagicMock()
        b._on_connect(mock_client, None, {}, 0)

        subs = mock_client.subscribe.call_args[0][0]
        topics = [s[0] for s in subs]
        assert all("tritium/hq/" in t for t in topics)

    def test_publish_uses_site_id(self, event_bus, tracker):
        b = MQTTBridge(event_bus=event_bus, target_tracker=tracker, site_id="hq")
        mock_client = MagicMock()
        b._client = mock_client
        b._connected = True

        b.publish_speech("test")
        topic = mock_client.publish.call_args[0][0]
        assert topic == "tritium/hq/amy/speech"

    def test_inbound_routes_any_site(self, event_bus, tracker):
        """_on_message parses topic parts regardless of site value."""
        b = MQTTBridge(event_bus=event_bus, target_tracker=tracker, site_id="hq")
        payload = {"boxes": [{"label": "person", "confidence": 0.9}]}
        # Note: the incoming topic uses "hq" as site
        msg = _make_msg("tritium/hq/cameras/cam1/detections", payload)
        b._on_message(None, None, msg)

        assert len(tracker.detections) == 1


# ===========================================================================
# Edge cases — Topic parsing
# ===========================================================================


@pytest.mark.unit
class TestTopicEdgeCases:
    def test_topic_exactly_four_parts(self, bridge, event_bus, tracker):
        """Topic with exactly 4 parts (missing action) should be ignored."""
        msg = _make_msg("tritium/home/cameras/cam1", {"x": 1})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(tracker.detections) == 0
        assert len(event_bus.published) == 0

    def test_topic_six_parts(self, bridge, tracker, event_bus):
        """Topic with 6+ parts — category/device/action still parsed from parts 2/3/4."""
        payload = {"boxes": [{"label": "dog", "confidence": 0.8}]}
        msg = _make_msg("tritium/home/cameras/cam1/detections/extra", payload)
        bridge._on_message(None, None, msg)

        # parts[4] == "detections", so it should still route correctly
        assert len(tracker.detections) == 1
        assert tracker.detections[0]["class_name"] == "dog"

    def test_topic_empty_device_id(self, bridge, tracker, event_bus):
        """Topic with empty device_id segment (consecutive slashes)."""
        payload = {"boxes": [{"label": "person", "confidence": 0.9}]}
        msg = _make_msg("tritium/home/cameras//detections", payload)
        bridge._on_message(None, None, msg)

        # Empty device_id is technically valid — code passes it through
        assert len(tracker.detections) == 1
        assert tracker.detections[0]["source_camera"] == ""

    def test_topic_device_id_with_dots(self, bridge, tracker, event_bus):
        """Device ID containing dots should be handled."""
        payload = {"event_type": "motion"}
        msg = _make_msg("tritium/home/sensors/sensor.v2.1/events", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][1]["sensor_id"] == "sensor.v2.1"

    def test_topic_device_id_with_dashes_underscores(self, bridge, tracker, event_bus):
        """Device ID with dashes and underscores."""
        payload = {"state": "online"}
        msg = _make_msg("tritium/home/cameras/front-door_cam-01/status", payload)
        bridge._on_message(None, None, msg)

        assert event_bus.published[0][1]["device_id"] == "front-door_cam-01"


# ===========================================================================
# Edge cases — Payload content
# ===========================================================================


@pytest.mark.unit
class TestPayloadEdgeCases:
    def test_camera_detection_box_missing_all_fields(self, bridge, tracker):
        """A detection box with no fields should use defaults."""
        payload = {"boxes": [{}]}
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.detections) == 1
        det = tracker.detections[0]
        assert det["class_name"] == "unknown"
        assert det["confidence"] == 0.5
        assert det["center_x"] == 0.5
        assert det["center_y"] == 0.5

    def test_camera_detection_many_boxes(self, bridge, tracker, event_bus):
        """Large number of detections in a single message."""
        boxes = [
            {"label": f"obj_{i}", "confidence": 0.6, "center_x": i * 0.01}
            for i in range(100)
        ]
        payload = {"boxes": boxes}
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.detections) == 100
        assert event_bus.published[0][1]["detection_count"] == 100

    def test_robot_telemetry_position_as_list(self, bridge, tracker):
        """Robot sends position as [x, y] list instead of {x, y} dict.

        The bridge passes position through to tracker which calls
        position.get("x", 0.0). A list has no .get() method, so this
        should be caught by the exception handler.
        """
        payload = {"position": [3.5, -2.1]}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        # Should not raise — caught by except in _on_message
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        # The tracker update may or may not have succeeded depending on
        # whether the exception was caught. The key point is no crash.

    def test_robot_telemetry_missing_position(self, bridge, tracker):
        """Robot telemetry with no position field at all."""
        payload = {"name": "Rover No-GPS", "battery": 0.3}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.sim_updates) == 1
        # position defaults to {} so pos.get("x", 0.0) -> 0.0
        assert tracker.sim_updates[0]["position"] == {}

    def test_payload_with_extra_fields(self, bridge, tracker, event_bus):
        """Payloads with unexpected extra fields should not crash."""
        payload = {
            "boxes": [{"label": "person", "confidence": 0.9}],
            "frame_number": 12345,
            "processing_time_ms": 42,
            "metadata": {"camera_firmware": "v2.1"},
        }
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.detections) == 1
        # Extra fields are passed through in the EventBus payload via "boxes"
        assert event_bus.published[0][1]["boxes"] == payload["boxes"]

    def test_sensor_event_extra_fields_forwarded(self, bridge, event_bus):
        """Extra fields in sensor event payload are forwarded to EventBus."""
        payload = {
            "event_type": "sound",
            "decibels": 85,
            "frequency_hz": 440,
            "custom_field": "hello",
        }
        msg = _make_msg("tritium/home/sensors/mic01/events", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        assert data["decibels"] == 85
        assert data["frequency_hz"] == 440
        assert data["custom_field"] == "hello"

    def test_unicode_device_name(self, bridge, tracker, event_bus):
        """Unicode characters in device names and payloads."""
        payload = {"name": "Rover \u03b1\u03b2\u03b3", "position": {"x": 1, "y": 2}}
        msg = _make_msg("tritium/home/robots/rover-\u00e9/telemetry", payload)
        bridge._on_message(None, None, msg)

        assert len(tracker.sim_updates) == 1
        assert tracker.sim_updates[0]["name"] == "Rover \u03b1\u03b2\u03b3"
        assert event_bus.published[0][1]["robot_id"] == "rover-\u00e9"

    def test_device_status_extra_fields_forwarded(self, bridge, event_bus):
        """Device status with extra fields are forwarded via **payload spread."""
        payload = {"online": True, "fps": 30, "temperature_c": 42.5}
        msg = _make_msg("tritium/home/cameras/cam1/status", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        assert data["temperature_c"] == 42.5
        assert data["fps"] == 30

    def test_empty_payload_object(self, bridge, event_bus):
        """Empty JSON object {} as payload should not crash."""
        msg = _make_msg("tritium/home/sensors/s1/events", {})
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert event_bus.published[0][1]["event_type"] == "unknown"

    def test_nested_payload_key_collision(self, bridge, event_bus):
        """Payload with key that collides with the wrapper key.

        Explicit keys (sensor_id, event_type) are set AFTER **payload spread,
        so they cannot be overwritten by untrusted payload data.
        """
        payload = {"event_type": "evil_type", "sensor_id": "spoofed"}
        msg = _make_msg("tritium/home/sensors/real_id/events", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        # Explicit keys override payload keys (set after **payload spread)
        assert data["sensor_id"] == "real_id"
        assert data["event_type"] == "evil_type"  # event_type is extracted from payload, not topic


# ===========================================================================
# Edge cases — start/stop lifecycle
# ===========================================================================


@pytest.mark.unit
class TestLifecycleEdgeCases:
    def test_start_failure_cleans_up_client(self, bridge):
        """start() should set _client to None when connect() fails."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = OSError("Connection refused")
        modules, _, _ = _make_paho_mock(mock_client)
        with patch.dict("sys.modules", modules):
            bridge.start()

        assert bridge._running is False
        assert bridge._client is None  # Bug fix: was left dangling before

    def test_double_stop_is_safe(self, bridge):
        """Calling stop() twice should not raise."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._running = True
        bridge._connected = True

        bridge.stop()
        bridge.stop()  # Second call should be harmless

        assert bridge._client is None
        assert bridge._connected is False

    def test_start_after_stop(self, bridge):
        """start() after stop() should create a fresh client."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        call_count = [0]

        def make_client(*args, **kwargs):
            call_count[0] += 1
            return mock_client1 if call_count[0] == 1 else mock_client2

        modules, mqtt_mod, _ = _make_paho_mock(mock_client1)
        mqtt_mod.Client.side_effect = make_client

        with patch.dict("sys.modules", modules):
            bridge.start()
            bridge.stop()
            bridge.start()

        # Should have created two separate clients
        assert mqtt_mod.Client.call_count == 2
        assert bridge._running is True

    def test_stop_handles_loop_stop_exception(self, bridge):
        """stop() should handle loop_stop() raising (e.g. thread not started)."""
        mock_client = MagicMock()
        mock_client.loop_stop.side_effect = RuntimeError("thread not started")
        bridge._client = mock_client
        bridge._running = True

        bridge.stop()

        assert bridge._client is None
        assert bridge._running is False


# ===========================================================================
# Edge cases — Reconnect behavior
# ===========================================================================


@pytest.mark.unit
class TestReconnect:
    def test_on_connect_resubscribes_on_reconnect(self, bridge, event_bus):
        """Simulates auto-reconnect: _on_connect called a second time."""
        mock_client = MagicMock()

        # First connection
        bridge._on_connect(mock_client, None, {}, 0)
        assert bridge._connected is True
        assert mock_client.subscribe.call_count == 1

        # Simulate disconnect
        bridge._on_disconnect(mock_client, None, 7)
        assert bridge._connected is False

        # Auto-reconnect triggers _on_connect again
        bridge._on_connect(mock_client, None, {}, 0)
        assert bridge._connected is True
        assert mock_client.subscribe.call_count == 2

        # Should have mqtt_connected, mqtt_disconnected, mqtt_connected
        event_types = [e[0] for e in event_bus.published]
        assert event_types == ["mqtt_connected", "mqtt_disconnected", "mqtt_connected"]

    def test_on_connect_failure_after_success(self, bridge, event_bus):
        """Reconnect attempt can fail (rc != 0)."""
        mock_client = MagicMock()

        # First: successful connect
        bridge._on_connect(mock_client, None, {}, 0)
        assert bridge._connected is True

        # Disconnect
        bridge._on_disconnect(mock_client, None, 1)

        # Reconnect fails
        bridge._on_connect(mock_client, None, {}, 3)  # rc=3 "server unavailable"
        assert bridge._connected is False
        assert "rc=3" in bridge._last_error

    def test_on_disconnect_rc_values(self, bridge, event_bus):
        """rc=0 is clean disconnect, anything else is unexpected."""
        bridge._connected = True
        bridge._on_disconnect(None, None, 0)
        assert bridge._last_error == ""  # Clean disconnect: no error set

        bridge._connected = True
        bridge._on_disconnect(None, None, 1)
        assert "Unexpected disconnect" in bridge._last_error


# ===========================================================================
# Edge cases — Publish during concurrent stop
# ===========================================================================


@pytest.mark.unit
class TestPublishEdgeCases:
    def test_publish_after_client_set_to_none(self, bridge):
        """_publish after client becomes None should not raise."""
        bridge._connected = True
        bridge._client = None  # Simulates race: stop() nulled client

        bridge._publish("topic", {"data": 1})
        assert bridge._messages_published == 0

    def test_publish_dispatch_when_disconnected(self, bridge):
        """High-level publish methods should be no-ops when disconnected."""
        bridge._connected = False
        bridge._client = MagicMock()

        bridge.publish_dispatch("rover1", 1.0, 2.0)
        bridge.publish_patrol("rover1", [(1.0, 2.0)])
        bridge.publish_recall("rover1")
        bridge.publish_alert({"level": "high"})
        bridge.publish_speech("hello")
        bridge.publish_thought("thinking")
        bridge.publish_target_update({"id": "1"})
        bridge.publish_escalation({"level": "low"})

        bridge._client.publish.assert_not_called()
        assert bridge._messages_published == 0

    def test_publish_empty_text(self, bridge):
        """Publishing empty strings should work fine."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_speech("")
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["text"] == ""
        assert "timestamp" in payload

    def test_publish_patrol_empty_waypoints(self, bridge):
        """Patrol with empty waypoint list."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_patrol("rover1", [])

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["waypoints"] == []
        assert payload["command"] == "patrol"

    def test_publish_alert_timestamp_not_overwritten(self, bridge):
        """If alert_data already has a 'timestamp' key, the bridge overwrites it.

        This is expected behavior (bridge always sets its own timestamp),
        but worth documenting.
        """
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_alert({"level": "low", "timestamp": "user-provided"})

        payload = json.loads(mock_client.publish.call_args[0][1])
        # The bridge's dict spread puts **alert_data first, then timestamp after,
        # so the bridge's timestamp overwrites the user-provided one
        assert payload["timestamp"] != "user-provided"

    def test_publish_target_update_preserves_all_fields(self, bridge):
        """target_data fields should all appear in published payload."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        target = {
            "target_id": "det_person_1",
            "alliance": "hostile",
            "position": {"x": 3.0, "y": -1.0},
            "speed": 1.5,
        }
        bridge.publish_target_update(target)

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["target_id"] == "det_person_1"
        assert payload["alliance"] == "hostile"
        assert payload["position"] == {"x": 3.0, "y": -1.0}
        assert payload["speed"] == 1.5
        assert "timestamp" in payload


# ===========================================================================
# Edge cases — Import safety
# ===========================================================================


@pytest.mark.unit
class TestImportSafety:
    def test_paho_import_fails_gracefully(self, bridge):
        """When paho-mqtt is not installed, start() should not crash."""
        with patch.dict("sys.modules", {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            bridge.start()

        assert bridge._running is False
        assert bridge._client is None

    def test_paho_import_succeeds_but_connect_fails(self, bridge):
        """paho imported OK but broker unreachable — state should be clean."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = TimeoutError("broker unreachable")
        modules, _, _ = _make_paho_mock(mock_client)

        with patch.dict("sys.modules", modules):
            bridge.start()

        assert bridge._running is False
        assert bridge._client is None  # Bug fix verified
        assert "broker unreachable" in bridge._last_error

    def test_start_after_failed_import_then_success(self, bridge):
        """start() after a failed import should retry import next time."""
        # First: fail
        with patch.dict("sys.modules", {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            bridge.start()
        assert bridge._running is False

        # Second: succeed
        mock_client = MagicMock()
        modules, _, _ = _make_paho_mock(mock_client)
        with patch.dict("sys.modules", modules):
            bridge.start()
        assert bridge._running is True


# ===========================================================================
# Edge cases — Payload key collision in **spread
# ===========================================================================


@pytest.mark.unit
class TestPayloadKeyCollision:
    """Test that explicit keys set AFTER **payload spread cannot be overwritten.

    The handlers use patterns like:
        {**payload, "sensor_id": sensor_id}
    Explicit keys come last, so untrusted payload data cannot spoof them.
    """

    def test_robot_telemetry_payload_cannot_overwrite_robot_id(self, bridge, event_bus):
        """Payload 'robot_id' key should be overwritten by explicit robot_id."""
        payload = {"robot_id": "evil_override"}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        # Explicit "robot_id" is set after **payload, so topic-derived value wins
        assert data["robot_id"] == "rover1"

    def test_device_status_payload_cannot_overwrite_category(self, bridge, event_bus):
        """Payload 'category'/'device_id' keys should be overwritten by explicit values."""
        payload = {"category": "hacked", "device_id": "spoofed"}
        msg = _make_msg("tritium/home/cameras/cam1/status", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        # Explicit keys come after **payload spread, so they win
        assert data["category"] == "camera"
        assert data["device_id"] == "cam1"

    def test_sensor_event_payload_cannot_overwrite_sensor_id(self, bridge, event_bus):
        """Payload 'sensor_id' key should be overwritten by explicit value."""
        payload = {"sensor_id": "spoofed", "event_type": "motion"}
        msg = _make_msg("tritium/home/sensors/real_sensor/events", payload)
        bridge._on_message(None, None, msg)

        data = event_bus.published[0][1]
        assert data["sensor_id"] == "real_sensor"


# ===========================================================================
# Command ACK protocol
# ===========================================================================


@pytest.mark.unit
class TestCommandAck:
    def test_ack_subscription_in_on_connect(self, bridge, event_bus):
        """on_connect should subscribe to robots/+/command/ack."""
        mock_client = MagicMock()
        bridge._on_connect(mock_client, None, {}, 0)

        subs = mock_client.subscribe.call_args[0][0]
        topics = {s[0]: s[1] for s in subs}
        assert "tritium/home/robots/+/command/ack" in topics
        assert topics["tritium/home/robots/+/command/ack"] == 1

    def test_ack_message_routed(self, bridge, event_bus):
        """Command ACK message should be handled and published to EventBus."""
        payload = {
            "command": "dispatch",
            "command_timestamp": "2026-02-16T10:30:00+00:00",
            "status": "accepted",
            "robot_id": "rover1",
        }
        msg = _make_msg("tritium/home/robots/rover1/command/ack", payload)
        bridge._on_message(None, None, msg)

        assert bridge._messages_received == 1
        assert len(event_bus.published) == 1
        assert event_bus.published[0][0] == "mqtt_command_ack"
        data = event_bus.published[0][1]
        assert data["robot_id"] == "rover1"
        assert data["command"] == "dispatch"
        assert data["status"] == "accepted"

    def test_ack_stored_in_command_acks(self, bridge):
        """ACK with command_timestamp should be stored for correlation."""
        payload = {
            "command": "dispatch",
            "command_timestamp": "2026-02-16T10:30:00+00:00",
            "status": "accepted",
        }
        msg = _make_msg("tritium/home/robots/rover1/command/ack", payload)
        bridge._on_message(None, None, msg)

        ack = bridge.get_command_ack("2026-02-16T10:30:00+00:00")
        assert ack is not None
        assert ack["robot_id"] == "rover1"
        assert ack["command"] == "dispatch"
        assert ack["status"] == "accepted"

    def test_ack_missing_timestamp_not_stored(self, bridge, event_bus):
        """ACK without command_timestamp is still published but not stored."""
        payload = {"command": "dispatch", "status": "accepted"}
        msg = _make_msg("tritium/home/robots/rover1/command/ack", payload)
        bridge._on_message(None, None, msg)

        # Still published to EventBus
        assert len(event_bus.published) == 1
        # But not stored for correlation (no timestamp key)
        assert bridge.get_command_ack("") is None

    def test_ack_prunes_old_entries(self, bridge):
        """Old ACKs should be pruned when storage exceeds 100."""
        for i in range(110):
            payload = {
                "command": "dispatch",
                "command_timestamp": f"ts-{i:04d}",
                "status": "accepted",
            }
            msg = _make_msg("tritium/home/robots/rover1/command/ack", payload)
            bridge._on_message(None, None, msg)

        # After 110 entries, pruning should have removed the first 50
        assert len(bridge._command_acks) <= 100

    def test_dispatch_tracks_pending_command(self, bridge):
        """publish_dispatch should record the command in pending_commands."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_dispatch("rover1", 10.0, -5.0)

        assert len(bridge._pending_commands) == 1
        ts = list(bridge._pending_commands.keys())[0]
        pending = bridge._pending_commands[ts]
        assert pending["robot_id"] == "rover1"
        assert pending["command"] == "dispatch"
        assert pending["x"] == 10.0
        assert pending["y"] == -5.0

    def test_rejected_ack(self, bridge, event_bus):
        """Robot can reject a command."""
        payload = {
            "command": "dispatch",
            "command_timestamp": "ts-001",
            "status": "rejected",
        }
        msg = _make_msg("tritium/home/robots/rover1/command/ack", payload)
        bridge._on_message(None, None, msg)

        ack = bridge.get_command_ack("ts-001")
        assert ack is not None
        assert ack["status"] == "rejected"


# ===========================================================================
# Device liveness tracking
# ===========================================================================


@pytest.mark.unit
class TestDeviceLiveness:
    def test_telemetry_updates_last_seen(self, bridge):
        """Any message from a device updates its last_seen timestamp."""
        payload = {"position": {"x": 1, "y": 2}}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        assert "rover1" in bridge._device_last_seen

    def test_camera_detection_updates_last_seen(self, bridge):
        """Camera detections also update device liveness."""
        payload = {"boxes": []}
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        assert "cam1" in bridge._device_last_seen

    def test_sensor_event_updates_last_seen(self, bridge):
        """Sensor events update device liveness."""
        payload = {"event_type": "motion"}
        msg = _make_msg("tritium/home/sensors/pir01/events", payload)
        bridge._on_message(None, None, msg)

        assert "pir01" in bridge._device_last_seen

    def test_no_stale_devices_initially(self, bridge):
        """With no messages received, no devices are stale."""
        assert bridge.get_stale_devices() == []

    def test_fresh_device_not_stale(self, bridge):
        """A device that just published should not be stale."""
        payload = {"position": {"x": 0, "y": 0}}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        assert "rover1" not in bridge.get_stale_devices()

    def test_old_device_is_stale(self, bridge):
        """A device that hasn't published in > threshold seconds is stale."""
        bridge._device_last_seen["dead-bot"] = time.monotonic() - 60.0

        stale = bridge.get_stale_devices()
        assert "dead-bot" in stale

    def test_stale_threshold_configurable(self, bridge):
        """The stale threshold can be changed."""
        bridge._device_last_seen["rover1"] = time.monotonic() - 5.0
        bridge.device_stale_timeout = 3.0

        assert "rover1" in bridge.get_stale_devices()

        bridge.device_stale_timeout = 10.0
        assert "rover1" not in bridge.get_stale_devices()

    def test_stats_includes_device_info(self, bridge):
        """Stats should include device count and stale device list."""
        payload = {"position": {"x": 0, "y": 0}}
        msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
        bridge._on_message(None, None, msg)

        stats = bridge.stats
        assert stats["devices_seen"] == 1
        assert isinstance(stats["stale_devices"], list)

    def test_multiple_messages_update_same_device(self, bridge):
        """Multiple messages from same device update timestamp, not duplicate."""
        for i in range(5):
            payload = {"position": {"x": i, "y": 0}}
            msg = _make_msg("tritium/home/robots/rover1/telemetry", payload)
            bridge._on_message(None, None, msg)

        assert len(bridge._device_last_seen) == 1
        assert "rover1" not in bridge.get_stale_devices()
