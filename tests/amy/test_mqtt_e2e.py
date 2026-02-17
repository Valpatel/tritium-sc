"""End-to-end integration tests for MQTT bridge data flow.

These tests use REAL EventBus and REAL TargetTracker (no mocks for those)
to verify that data actually flows through the entire pipeline:
  MQTT message -> MQTTBridge._on_message -> TargetTracker -> EventBus

The MQTT client itself is mocked (no broker needed), but the _on_message
handler is called with realistic payloads — including the exact format
published by the robot-template's TelemetryPublisher.
"""

from __future__ import annotations

import json
import queue
import time
from unittest.mock import MagicMock

import pytest

from amy.commander import EventBus
from amy.mqtt_bridge import MQTTBridge
from amy.target_tracker import TargetTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(topic: str, payload: dict) -> MagicMock:
    """Create a mock MQTT message with the given topic and JSON payload."""
    msg = MagicMock()
    msg.topic = topic
    msg.payload = json.dumps(payload).encode("utf-8")
    return msg


def _drain_queue(q: queue.Queue, timeout: float = 0.1) -> list[dict]:
    """Drain all messages from a queue."""
    msgs = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msgs.append(q.get_nowait())
        except queue.Empty:
            break
    return msgs


# ---------------------------------------------------------------------------
# Fixtures — REAL EventBus + REAL TargetTracker
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def tracker():
    return TargetTracker()


@pytest.fixture
def bridge(event_bus, tracker):
    return MQTTBridge(
        event_bus=event_bus,
        target_tracker=tracker,
        site_id="home",
        broker_host="localhost",
        broker_port=1883,
    )


# ===========================================================================
# Camera detection -> TargetTracker flow
# ===========================================================================


@pytest.mark.unit
class TestCameraDetectionFlow:
    """Verify camera YOLO detections flow through bridge into real TargetTracker."""

    def test_person_detection_creates_hostile_target(self, bridge, tracker, event_bus):
        """A person detection from a camera should appear as hostile in tracker."""
        sub = event_bus.subscribe()

        payload = {
            "boxes": [
                {"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.3},
            ]
        }
        msg = _make_msg("tritium/home/cameras/front-door/detections", payload)
        bridge._on_message(None, None, msg)

        # Verify target appeared in real TargetTracker
        all_targets = tracker.get_all()
        assert len(all_targets) == 1
        target = all_targets[0]
        assert target.alliance == "hostile"
        assert target.asset_type == "person"
        assert target.source == "yolo"
        assert target.position == (0.5, 0.3)

        # Verify EventBus got the event
        events = _drain_queue(sub)
        detection_events = [e for e in events if e["type"] == "mqtt_camera_detection"]
        assert len(detection_events) == 1
        assert detection_events[0]["data"]["camera_id"] == "front-door"
        assert detection_events[0]["data"]["detection_count"] == 1

    def test_vehicle_detection_creates_unknown_target(self, bridge, tracker):
        """A car detection should appear as unknown alliance."""
        payload = {
            "boxes": [
                {"label": "car", "confidence": 0.85, "center_x": 0.7, "center_y": 0.6},
            ]
        }
        msg = _make_msg("tritium/home/cameras/side-cam/detections", payload)
        bridge._on_message(None, None, msg)

        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].alliance == "unknown"
        assert targets[0].asset_type == "vehicle"

    def test_low_confidence_detection_filtered(self, bridge, tracker):
        """Detections below 0.4 confidence should be filtered by TargetTracker."""
        payload = {
            "boxes": [
                {"label": "person", "confidence": 0.3, "center_x": 0.5, "center_y": 0.5},
            ]
        }
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        # TargetTracker filters confidence < 0.4
        targets = tracker.get_all()
        assert len(targets) == 0

    def test_multiple_detections_in_one_frame(self, bridge, tracker):
        """Multiple detections in a single MQTT message all land in tracker."""
        payload = {
            "boxes": [
                {"label": "person", "confidence": 0.9, "center_x": 0.2, "center_y": 0.3},
                {"label": "person", "confidence": 0.85, "center_x": 0.8, "center_y": 0.7},
                {"label": "car", "confidence": 0.7, "center_x": 0.5, "center_y": 0.5},
            ]
        }
        msg = _make_msg("tritium/home/cameras/cam1/detections", payload)
        bridge._on_message(None, None, msg)

        all_targets = tracker.get_all()
        assert len(all_targets) == 3
        hostiles = tracker.get_hostiles()
        assert len(hostiles) == 2  # Two persons
        # The car should be unknown
        unknowns = [t for t in all_targets if t.alliance == "unknown"]
        assert len(unknowns) == 1
        assert unknowns[0].asset_type == "vehicle"

    def test_repeated_detection_updates_existing_target(self, bridge, tracker):
        """Same object detected twice at nearby positions should update, not duplicate."""
        # First detection
        payload1 = {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5}]}
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam1/detections", payload1))

        # Second detection at nearby position (within 0.2 normalized)
        payload2 = {"boxes": [{"label": "person", "confidence": 0.88, "center_x": 0.52, "center_y": 0.48}]}
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam1/detections", payload2))

        # Should coalesce into one target (same class, nearby position)
        targets = tracker.get_all()
        assert len(targets) == 1
        # Position should be updated to the latest
        assert targets[0].position == (0.52, 0.48)

    def test_distant_detections_create_separate_targets(self, bridge, tracker):
        """Same class at distant positions should create separate targets."""
        payload1 = {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 0.1, "center_y": 0.1}]}
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam1/detections", payload1))

        payload2 = {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 0.9, "center_y": 0.9}]}
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam1/detections", payload2))

        targets = tracker.get_all()
        assert len(targets) == 2


# ===========================================================================
# Robot telemetry -> TargetTracker flow (exact robot-template format)
# ===========================================================================


@pytest.mark.unit
class TestRobotTelemetryFlow:
    """Verify robot telemetry flows through bridge into real TargetTracker.

    Uses the EXACT payload format from examples/robot-template/brain/telemetry.py:
        {
            "name": "Rover Alpha",
            "asset_type": "rover",
            "position": {"x": pos[0], "y": pos[1]},
            "heading": heading_degrees,
            "speed": speed_mps,
            "battery": battery_fraction,
            "status": "patrolling",
            "turret": {"pan": 45.0, "tilt": -10.0},
        }
    """

    ROBOT_TELEMETRY = {
        "name": "Rover Alpha",
        "asset_type": "rover",
        "position": {"x": 3.5, "y": -2.1},
        "heading": 127.4,
        "speed": 1.2,
        "battery": 0.85,
        "status": "patrolling",
        "turret": {"pan": 45.0, "tilt": -10.0},
    }

    def test_robot_telemetry_creates_friendly_target(self, bridge, tracker, event_bus):
        """Robot telemetry in exact robot-template format creates a friendly target."""
        sub = event_bus.subscribe()

        msg = _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            self.ROBOT_TELEMETRY,
        )
        bridge._on_message(None, None, msg)

        # Verify in real TargetTracker
        all_targets = tracker.get_all()
        assert len(all_targets) == 1

        target = all_targets[0]
        assert target.target_id == "mqtt_rover-alpha"
        assert target.name == "Rover Alpha"
        assert target.alliance == "friendly"
        assert target.asset_type == "rover"
        assert target.position == (3.5, -2.1)
        assert target.heading == 127.4
        assert target.speed == 1.2
        assert target.battery == 0.85
        assert target.status == "patrolling"
        assert target.source == "simulation"  # update_from_simulation sets this

        # Verify it appears in friendlies
        friendlies = tracker.get_friendlies()
        assert len(friendlies) == 1
        assert friendlies[0].target_id == "mqtt_rover-alpha"

        # Not in hostiles
        assert len(tracker.get_hostiles()) == 0

        # Verify EventBus received the event
        events = _drain_queue(sub)
        telem_events = [e for e in events if e["type"] == "mqtt_robot_telemetry"]
        assert len(telem_events) == 1
        assert telem_events[0]["data"]["robot_id"] == "rover-alpha"
        assert telem_events[0]["data"]["name"] == "Rover Alpha"

    def test_robot_telemetry_updates_position(self, bridge, tracker):
        """Repeated telemetry updates the robot's position in tracker."""
        # Initial position
        msg1 = _make_msg("tritium/home/robots/rover-alpha/telemetry", {
            **self.ROBOT_TELEMETRY,
            "position": {"x": 0.0, "y": 0.0},
        })
        bridge._on_message(None, None, msg1)

        # Updated position
        msg2 = _make_msg("tritium/home/robots/rover-alpha/telemetry", {
            **self.ROBOT_TELEMETRY,
            "position": {"x": 10.0, "y": 5.0},
            "heading": 45.0,
            "speed": 2.5,
            "battery": 0.72,
        })
        bridge._on_message(None, None, msg2)

        # Should still be one target, with updated values
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].position == (10.0, 5.0)
        assert targets[0].heading == 45.0
        assert targets[0].speed == 2.5
        assert targets[0].battery == 0.72

    def test_multiple_robots(self, bridge, tracker):
        """Multiple robots each get their own TargetTracker entry."""
        for robot_id, name, x, y in [
            ("rover-alpha", "Rover Alpha", 0.0, 0.0),
            ("rover-bravo", "Rover Bravo", 5.0, 3.0),
            ("drone-1", "Recon Drone", 2.0, -1.0),
        ]:
            msg = _make_msg(f"tritium/home/robots/{robot_id}/telemetry", {
                "name": name,
                "asset_type": "drone" if "drone" in robot_id else "rover",
                "position": {"x": x, "y": y},
                "heading": 0.0,
                "speed": 0.0,
                "battery": 1.0,
                "status": "idle",
            })
            bridge._on_message(None, None, msg)

        targets = tracker.get_all()
        assert len(targets) == 3
        # All should be friendly
        assert all(t.alliance == "friendly" for t in targets)
        # Check IDs
        ids = {t.target_id for t in targets}
        assert ids == {"mqtt_rover-alpha", "mqtt_rover-bravo", "mqtt_drone-1"}

    def test_robot_turret_field_does_not_break_tracker(self, bridge, tracker):
        """The turret field from robot-template is extra data — must not crash tracker."""
        msg = _make_msg("tritium/home/robots/rover-alpha/telemetry", self.ROBOT_TELEMETRY)
        bridge._on_message(None, None, msg)

        # The turret field is passed through to update_from_simulation
        # but TargetTracker ignores unknown keys — no crash
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].name == "Rover Alpha"

    def test_robot_with_zero_battery(self, bridge, tracker):
        """Robot at 0% battery should still appear in tracker."""
        msg = _make_msg("tritium/home/robots/rover-alpha/telemetry", {
            **self.ROBOT_TELEMETRY,
            "battery": 0.0,
            "status": "dead_battery",
        })
        bridge._on_message(None, None, msg)

        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].battery == 0.0
        assert targets[0].status == "dead_battery"

    def test_robot_minimal_telemetry(self, bridge, tracker):
        """Robot sending minimal telemetry (no optional fields) still works."""
        msg = _make_msg("tritium/home/robots/minimal-bot/telemetry", {})
        bridge._on_message(None, None, msg)

        targets = tracker.get_all()
        assert len(targets) == 1
        target = targets[0]
        assert target.target_id == "mqtt_minimal-bot"
        assert target.name == "minimal-bot"  # defaults to robot_id
        assert target.asset_type == "rover"   # default
        assert target.battery == 1.0          # default
        assert target.status == "active"      # default


# ===========================================================================
# Mixed scenario: cameras + robots + sensors all publishing
# ===========================================================================


@pytest.mark.unit
class TestMixedFlow:
    """Verify multiple device types publishing simultaneously."""

    def test_camera_and_robot_data_coexist_in_tracker(self, bridge, tracker, event_bus):
        """Both YOLO detections and robot telemetry land in same tracker."""
        sub = event_bus.subscribe()

        # Robot publishes telemetry
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "asset_type": "rover",
             "position": {"x": 1.0, "y": 2.0}, "battery": 0.9, "status": "patrolling"},
        ))

        # Camera detects a person
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/front-door/detections",
            {"boxes": [{"label": "person", "confidence": 0.95, "center_x": 0.5, "center_y": 0.5}]},
        ))

        # Sensor reports motion
        bridge._on_message(None, None, _make_msg(
            "tritium/home/sensors/pir-north/events",
            {"event_type": "motion", "zone": "north_fence"},
        ))

        # Tracker should have 2 targets (robot + person, sensor doesn't create targets)
        all_targets = tracker.get_all()
        assert len(all_targets) == 2

        friendlies = tracker.get_friendlies()
        assert len(friendlies) == 1
        assert friendlies[0].name == "Rover Alpha"

        hostiles = tracker.get_hostiles()
        assert len(hostiles) == 1
        assert hostiles[0].asset_type == "person"

        # EventBus should have 3 different event types
        events = _drain_queue(sub)
        event_types = {e["type"] for e in events}
        assert "mqtt_robot_telemetry" in event_types
        assert "mqtt_camera_detection" in event_types
        assert "mqtt_sensor_event" in event_types

    def test_battlespace_summary_with_mixed_targets(self, bridge, tracker):
        """TargetTracker.summary() produces readable text with mixed targets."""
        # Robot
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "asset_type": "rover",
             "position": {"x": 1.0, "y": 2.0}, "battery": 0.9, "status": "patrolling"},
        ))

        # Hostile person
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/cam1/detections",
            {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5}]},
        ))

        summary = tracker.summary()
        assert "BATTLESPACE" in summary
        assert "1 friendly" in summary
        assert "1 hostile" in summary

    def test_event_bus_subscriber_receives_all_events(self, bridge, event_bus):
        """A single EventBus subscriber gets events from all device types."""
        sub = event_bus.subscribe()

        # Send 5 different messages
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/cam1/detections",
            {"boxes": [{"label": "person", "confidence": 0.9}]},
        ))
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/cam1/status",
            {"online": True},
        ))
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover1/telemetry",
            {"name": "R1", "position": {"x": 0, "y": 0}},
        ))
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover1/status",
            {"state": "idle"},
        ))
        bridge._on_message(None, None, _make_msg(
            "tritium/home/sensors/pir1/events",
            {"event_type": "motion"},
        ))

        events = _drain_queue(sub)
        assert len(events) == 5
        types = [e["type"] for e in events]
        assert "mqtt_camera_detection" in types
        assert "mqtt_device_status" in types
        assert "mqtt_robot_telemetry" in types
        assert "mqtt_sensor_event" in types


# ===========================================================================
# Outbound publish + roundtrip verification
# ===========================================================================


@pytest.mark.unit
class TestOutboundDispatch:
    """Verify outbound MQTT publishing with mock MQTT client."""

    def test_dispatch_publishes_to_correct_topic(self, bridge):
        """publish_dispatch should target the robot's command topic."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_dispatch("rover-alpha", 10.5, -3.2)

        # Two publishes: one to robot command, one to amy/dispatch
        assert mock_client.publish.call_count == 2

        # Robot command
        call1 = mock_client.publish.call_args_list[0]
        assert call1[0][0] == "tritium/home/robots/rover-alpha/command"
        p1 = json.loads(call1[0][1])
        assert p1["command"] == "dispatch"
        assert p1["x"] == 10.5
        assert p1["y"] == -3.2

        # Amy dispatch monitoring
        call2 = mock_client.publish.call_args_list[1]
        assert call2[0][0] == "tritium/home/amy/dispatch"
        p2 = json.loads(call2[0][1])
        assert p2["robot_id"] == "rover-alpha"
        assert p2["destination"] == {"x": 10.5, "y": -3.2}

    def test_dispatch_command_would_reach_robot(self, bridge, tracker):
        """Simulate roundtrip: robot appears via telemetry, then gets dispatched."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        # Robot publishes telemetry first
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "asset_type": "rover",
             "position": {"x": 0, "y": 0}, "battery": 0.9, "status": "idle"},
        ))

        # Verify robot exists in tracker
        target = tracker.get_target("mqtt_rover-alpha")
        assert target is not None
        assert target.name == "Rover Alpha"

        # Now dispatch it
        bridge.publish_dispatch("rover-alpha", 5.0, 3.0)

        # Verify the dispatch went to the right topic
        cmd_call = mock_client.publish.call_args_list[0]
        assert "rover-alpha/command" in cmd_call[0][0]
        payload = json.loads(cmd_call[0][1])
        assert payload["command"] == "dispatch"
        assert payload["x"] == 5.0
        assert payload["y"] == 3.0


# ===========================================================================
# Stale detection pruning
# ===========================================================================


@pytest.mark.unit
class TestStalePruning:
    """Verify TargetTracker prunes stale YOLO detections but keeps robots."""

    def test_yolo_detection_pruned_after_timeout(self, bridge, tracker):
        """YOLO detections older than STALE_TIMEOUT should be pruned."""
        # Inject a detection
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/cam1/detections",
            {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 0.5, "center_y": 0.5}]},
        ))
        assert len(tracker.get_all()) == 1

        # Manually age the detection beyond the stale timeout
        for t in tracker._targets.values():
            t.last_seen = time.monotonic() - (tracker.STALE_TIMEOUT + 1)

        # Now get_all() should prune it
        assert len(tracker.get_all()) == 0

    def test_robot_survives_yolo_timeout(self, bridge, tracker):
        """Sim-source targets use SIM_STALE_TIMEOUT, not the shorter YOLO timeout."""
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "position": {"x": 0, "y": 0}, "battery": 0.9},
        ))
        assert len(tracker.get_all()) == 1

        sim_timeout = getattr(tracker, "SIM_STALE_TIMEOUT", float("inf"))
        # Age just within the sim timeout
        for t in tracker._targets.values():
            t.last_seen = time.monotonic() - (sim_timeout * 0.5)

        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].target_id == "mqtt_rover-alpha"

    def test_robot_pruned_after_sim_timeout(self, bridge, tracker):
        """Sim-source targets ARE pruned when engine stops publishing telemetry."""
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "position": {"x": 0, "y": 0}, "battery": 0.9},
        ))
        assert len(tracker.get_all()) == 1

        sim_timeout = getattr(tracker, "SIM_STALE_TIMEOUT", 10.0)
        for t in tracker._targets.values():
            t.last_seen = time.monotonic() - (sim_timeout + 1)

        targets = tracker.get_all()
        assert len(targets) == 0


# ===========================================================================
# Stats tracking
# ===========================================================================


@pytest.mark.unit
class TestStatsTracking:
    """Verify bridge message counters work with real data flow."""

    def test_message_counter_with_real_flow(self, bridge):
        """Messages received counter increments for each processed message."""
        assert bridge.stats["messages_received"] == 0

        for i in range(10):
            bridge._on_message(None, None, _make_msg(
                "tritium/home/sensors/s1/events",
                {"event_type": "motion", "n": i},
            ))

        assert bridge.stats["messages_received"] == 10

    def test_publish_counter_with_real_client(self, bridge):
        """Messages published counter increments for each outbound publish."""
        mock_client = MagicMock()
        bridge._client = mock_client
        bridge._connected = True

        bridge.publish_speech("hello")
        bridge.publish_thought("thinking")
        bridge.publish_alert({"level": "low"})

        assert bridge.stats["messages_published"] == 3


# ===========================================================================
# EventBus integration
# ===========================================================================


@pytest.mark.unit
class TestEventBusIntegration:
    """Verify EventBus correctly distributes MQTT events to multiple subscribers."""

    def test_multiple_subscribers_all_receive(self, bridge, event_bus):
        """All EventBus subscribers should receive MQTT events."""
        sub1 = event_bus.subscribe()
        sub2 = event_bus.subscribe()
        sub3 = event_bus.subscribe()

        bridge._on_message(None, None, _make_msg(
            "tritium/home/sensors/s1/events",
            {"event_type": "motion"},
        ))

        for sub in [sub1, sub2, sub3]:
            events = _drain_queue(sub)
            assert len(events) == 1
            assert events[0]["type"] == "mqtt_sensor_event"

    def test_unsubscribed_queue_does_not_receive(self, bridge, event_bus):
        """After unsubscribe, the queue should not get new events."""
        sub1 = event_bus.subscribe()
        sub2 = event_bus.subscribe()

        event_bus.unsubscribe(sub1)

        bridge._on_message(None, None, _make_msg(
            "tritium/home/sensors/s1/events",
            {"event_type": "motion"},
        ))

        # sub1 was unsubscribed
        assert _drain_queue(sub1) == []
        # sub2 still gets events
        assert len(_drain_queue(sub2)) == 1


# ===========================================================================
# Edge cases in the real pipeline
# ===========================================================================


@pytest.mark.unit
class TestPipelineEdgeCases:
    """Edge cases that only manifest when using real EventBus + TargetTracker."""

    def test_tracker_get_target_by_mqtt_id(self, bridge, tracker):
        """Can look up a specific MQTT robot by its generated target_id."""
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/my-bot/telemetry",
            {"name": "My Bot", "position": {"x": 1, "y": 2}},
        ))

        target = tracker.get_target("mqtt_my-bot")
        assert target is not None
        assert target.name == "My Bot"
        assert target.position == (1.0, 2.0)

    def test_tracker_remove_mqtt_robot(self, bridge, tracker):
        """Can remove an MQTT-injected robot from tracker."""
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "position": {"x": 0, "y": 0}},
        ))
        assert len(tracker.get_all()) == 1

        removed = tracker.remove("mqtt_rover-alpha")
        assert removed is True
        assert len(tracker.get_all()) == 0

    def test_bad_json_does_not_corrupt_tracker(self, bridge, tracker):
        """Bad MQTT payload should not leave tracker in inconsistent state."""
        # First: inject a good robot
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "position": {"x": 0, "y": 0}},
        ))

        # Then: bad JSON
        bad_msg = MagicMock()
        bad_msg.topic = "tritium/home/robots/rover-alpha/telemetry"
        bad_msg.payload = b"not-json{{"
        bridge._on_message(None, None, bad_msg)

        # Tracker should still be valid with original data
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].name == "Rover Alpha"

    def test_proximity_alert_in_summary(self, bridge, tracker):
        """When hostile is near friendly, summary should contain ALERT."""
        # Friendly robot at (1, 1)
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "position": {"x": 1, "y": 1}, "battery": 0.9},
        ))

        # Hostile person at (1.5, 1.5) — within 5.0 units
        bridge._on_message(None, None, _make_msg(
            "tritium/home/cameras/cam1/detections",
            {"boxes": [{"label": "person", "confidence": 0.9, "center_x": 1.5, "center_y": 1.5}]},
        ))

        summary = tracker.summary()
        assert "ALERT" in summary
        assert "Rover Alpha" in summary

    def test_to_dict_serialization(self, bridge, tracker):
        """TrackedTarget.to_dict() works for MQTT-injected targets."""
        bridge._on_message(None, None, _make_msg(
            "tritium/home/robots/rover-alpha/telemetry",
            {"name": "Rover Alpha", "asset_type": "rover",
             "position": {"x": 3.5, "y": -2.1}, "heading": 90.0,
             "speed": 1.0, "battery": 0.8, "status": "patrolling"},
        ))

        targets = tracker.get_all()
        d = targets[0].to_dict()
        assert d["target_id"] == "mqtt_rover-alpha"
        assert d["name"] == "Rover Alpha"
        assert d["alliance"] == "friendly"
        assert d["position"] == {"x": 3.5, "y": -2.1}
        assert d["heading"] == 90.0
        assert d["speed"] == 1.0
        assert d["battery"] == 0.8
        assert d["status"] == "patrolling"
        assert d["source"] == "simulation"

        # Must be JSON-serializable
        json_str = json.dumps(d)
        assert '"Rover Alpha"' in json_str
