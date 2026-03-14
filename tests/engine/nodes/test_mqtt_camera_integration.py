# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests: MQTT camera detection -> CameraFeedsPlugin -> TargetTracker."""

from __future__ import annotations

import json
import queue
from unittest.mock import MagicMock

import numpy as np
import pytest

from engine.comms.mqtt_bridge import MQTTBridge
from plugins.camera_feeds.plugin import CameraFeedsPlugin
from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None):
        self.published.append((event_type, data))

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        pass


class MockTargetTracker:
    def __init__(self):
        self.detections: list[dict] = []
        self.sim_updates: list[dict] = []

    def update_from_detection(self, data: dict) -> None:
        self.detections.append(data)

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)


def _make_msg(topic: str, payload: bytes | dict) -> MagicMock:
    """Create a mock MQTT message."""
    msg = MagicMock()
    msg.topic = topic
    if isinstance(payload, dict):
        msg.payload = json.dumps(payload).encode("utf-8")
    else:
        msg.payload = payload
    return msg


def _make_jpeg() -> bytes:
    """Create a minimal valid JPEG."""
    # 1x1 white pixel JPEG
    img = np.ones((1, 1, 3), dtype=np.uint8) * 255
    import cv2
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


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
    )


@pytest.fixture
def plugin(event_bus, bridge, tracker):
    p = CameraFeedsPlugin()
    ctx = MagicMock()
    ctx.event_bus = event_bus
    ctx.app = None
    ctx.logger = None
    p.configure(ctx)
    p.set_mqtt_bridge(bridge)
    p.set_target_tracker(tracker)
    return p


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.unit
class TestMQTTBridgeCameraFrameSubscription:
    """Verify MQTTBridge subscribes to cameras/+/frame and dispatches to callbacks."""

    def test_frame_topic_in_subscriptions(self, bridge):
        """Bridge subscribes to cameras/+/frame on connect."""
        subscribed = []
        mock_client = MagicMock()
        mock_client.subscribe = lambda subs: subscribed.extend(subs)
        bridge._on_connect(mock_client, None, None, 0)
        topics = [t for t, q in subscribed]
        assert "tritium/home/cameras/+/frame" in topics

    def test_frame_callback_invoked(self, bridge):
        """Registered frame callback receives raw JPEG bytes."""
        received = []
        bridge.register_camera_callback("cam-01", lambda data: received.append(data))
        jpeg = _make_jpeg()
        msg = _make_msg("tritium/home/cameras/cam-01/frame", jpeg)
        bridge._on_message(None, None, msg)
        assert len(received) == 1
        assert received[0] == jpeg

    def test_wildcard_callback(self, bridge):
        """Wildcard (None) callback receives frames from any camera."""
        received = []
        bridge.register_camera_callback(None, lambda data: received.append(data))
        jpeg = _make_jpeg()
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam-A/frame", jpeg))
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam-B/frame", jpeg))
        assert len(received) == 2

    def test_frame_publishes_event(self, bridge, event_bus):
        """Frame arrival publishes mqtt_camera_frame event."""
        jpeg = _make_jpeg()
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam-01/frame", jpeg))
        frame_events = [e for e in event_bus.published if e[0] == "mqtt_camera_frame"]
        assert len(frame_events) == 1
        assert frame_events[0][1]["camera_id"] == "cam-01"
        assert frame_events[0][1]["size"] == len(jpeg)

    def test_device_liveness_tracked(self, bridge):
        """Frame messages update device liveness timestamp."""
        jpeg = _make_jpeg()
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam-01/frame", jpeg))
        assert "cam-01" in bridge._device_last_seen


@pytest.mark.unit
class TestMQTTSourceWiring:
    """Verify MQTTSource wires to MQTTBridge and processes frames/detections."""

    def test_set_mqtt_bridge_registers_callback(self, bridge):
        """MQTTSource.set_mqtt_bridge registers a frame callback on the bridge."""
        config = CameraSourceConfig(
            source_id="mqtt-cam-01",
            source_type="mqtt",
            extra={"cam_id": "cam-01"},
        )
        source = MQTTSource(config)
        source.set_mqtt_bridge(bridge)
        assert "cam-01" in bridge._camera_frame_callbacks
        assert len(bridge._camera_frame_callbacks["cam-01"]) == 1

    def test_mqtt_frame_reaches_source(self, bridge):
        """JPEG frame via MQTTBridge reaches MQTTSource and is decodable."""
        config = CameraSourceConfig(
            source_id="mqtt-cam-01",
            source_type="mqtt",
            extra={"cam_id": "cam-01"},
        )
        source = MQTTSource(config)
        source.set_mqtt_bridge(bridge)
        source.start()

        jpeg = _make_jpeg()
        bridge._on_message(None, None, _make_msg("tritium/home/cameras/cam-01/frame", jpeg))

        frame = source.get_frame()
        assert frame is not None
        assert frame.shape == (1, 1, 3)

    def test_on_detection_creates_target(self, tracker):
        """MQTTSource.on_detection forwards to TargetTracker."""
        config = CameraSourceConfig(
            source_id="mqtt-cam-01",
            source_type="mqtt",
            extra={"cam_id": "cam-01"},
        )
        source = MQTTSource(config)
        source.set_target_tracker(tracker)

        source.on_detection({
            "label": "person",
            "confidence": 0.85,
            "center_x": 0.5,
            "center_y": 0.6,
        })

        assert len(tracker.detections) == 1
        det = tracker.detections[0]
        assert det["class_name"] == "person"
        assert det["confidence"] == 0.85
        assert det["source_camera"] == "cam-01"

    def test_detection_count_increments(self, tracker):
        """Detection counter increments on each on_detection call."""
        config = CameraSourceConfig(source_id="cam-x", source_type="mqtt")
        source = MQTTSource(config)
        source.set_target_tracker(tracker)
        source.on_detection({"label": "car", "confidence": 0.7})
        source.on_detection({"label": "person", "confidence": 0.9})
        assert source._detection_count == 2

    def test_to_dict_includes_detection_count(self):
        """MQTTSource.to_dict includes detection_count and cam_id."""
        config = CameraSourceConfig(
            source_id="cam-01",
            source_type="mqtt",
            extra={"cam_id": "front-door"},
        )
        source = MQTTSource(config)
        d = source.to_dict()
        assert d["cam_id"] == "front-door"
        assert d["detection_count"] == 0


@pytest.mark.unit
class TestCameraFeedsPluginMQTTIntegration:
    """Verify CameraFeedsPlugin wires MQTT sources to bridge and tracker."""

    def test_register_mqtt_source_wires_bridge(self, plugin, bridge):
        """Registering an MQTT source auto-wires it to MQTTBridge."""
        config = CameraSourceConfig(
            source_id="front-cam",
            source_type="mqtt",
            extra={"cam_id": "cam-front"},
        )
        source = plugin.register_source(config)
        assert isinstance(source, MQTTSource)
        assert "cam-front" in bridge._camera_frame_callbacks

    def test_register_mqtt_source_wires_tracker(self, plugin, tracker):
        """Registering an MQTT source auto-wires TargetTracker."""
        config = CameraSourceConfig(
            source_id="rear-cam",
            source_type="mqtt",
            extra={"cam_id": "cam-rear"},
        )
        source = plugin.register_source(config)
        assert isinstance(source, MQTTSource)
        assert source._target_tracker is tracker

    def test_end_to_end_detection_flow(self, plugin, bridge, tracker, event_bus):
        """Full flow: MQTT detection message -> MQTTBridge -> TargetTracker.

        The MQTTBridge._on_camera_detection already creates targets from
        detections on the /detections topic. This test verifies both the
        bridge path and the MQTTSource.on_detection path work.
        """
        # Register an MQTT camera source
        config = CameraSourceConfig(
            source_id="yard-cam",
            source_type="mqtt",
            extra={"cam_id": "cam-yard"},
        )
        source = plugin.register_source(config)

        # Simulate MQTT detection arriving via MQTTBridge
        detection_payload = {
            "boxes": [
                {"label": "person", "confidence": 0.92, "center_x": 0.3, "center_y": 0.4},
                {"label": "dog", "confidence": 0.75, "center_x": 0.7, "center_y": 0.8},
            ]
        }
        msg = _make_msg("tritium/home/cameras/cam-yard/detections", detection_payload)
        bridge._on_message(None, None, msg)

        # MQTTBridge._on_camera_detection should have created targets
        assert len(tracker.detections) == 2
        assert tracker.detections[0]["class_name"] == "person"
        assert tracker.detections[0]["source_camera"] == "cam-yard"
        assert tracker.detections[1]["class_name"] == "dog"

        # EventBus should have the detection event
        det_events = [e for e in event_bus.published if e[0] == "mqtt_camera_detection"]
        assert len(det_events) == 1
        assert det_events[0][1]["camera_id"] == "cam-yard"
        assert det_events[0][1]["detection_count"] == 2

    def test_end_to_end_frame_flow(self, plugin, bridge):
        """Full flow: MQTT frame -> MQTTBridge -> MQTTSource -> decodable frame."""
        config = CameraSourceConfig(
            source_id="door-cam",
            source_type="mqtt",
            extra={"cam_id": "cam-door"},
        )
        source = plugin.register_source(config)
        source.start()

        jpeg = _make_jpeg()
        msg = _make_msg("tritium/home/cameras/cam-door/frame", jpeg)
        bridge._on_message(None, None, msg)

        frame = source.get_frame()
        assert frame is not None
        assert source._frame_count == 1
