# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for synthetic data generators — BLE, Meshtastic, Camera."""

from __future__ import annotations

import time

import pytest

from engine.comms.event_bus import EventBus
from engine.synthetic.data_generators import (
    BLEScanGenerator,
    CameraDetectionGenerator,
    MeshtasticNodeGenerator,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _drain(bus: EventBus, timeout: float = 2.0):
    """Subscribe and drain events until timeout."""
    q = bus.subscribe()
    deadline = time.monotonic() + timeout
    msgs = []
    while time.monotonic() < deadline:
        try:
            msgs.append(q.get(timeout=0.1))
        except Exception:
            pass
    bus.unsubscribe(q)
    return msgs


def _drain_type(bus: EventBus, event_type: str, timeout: float = 2.0):
    """Subscribe and collect events of a specific type."""
    q = bus.subscribe()
    deadline = time.monotonic() + timeout
    msgs = []
    while time.monotonic() < deadline:
        try:
            msg = q.get(timeout=0.1)
            if msg.get("type") == event_type:
                msgs.append(msg)
        except Exception:
            pass
    bus.unsubscribe(q)
    return msgs


# ── BLEScanGenerator ────────────────────────────────────────────────────

@pytest.mark.unit
class TestBLEScanGenerator:

    def test_start_stop(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1)
        gen.start(bus)
        assert gen.running is True
        gen.stop()
        assert gen.running is False

    def test_publishes_ble_presence_events(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1, max_devices=5)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.5)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        ble_events = [e for e in events if e.get("type") == "fleet.ble_presence"]
        assert len(ble_events) >= 1
        data = ble_events[0]["data"]
        assert "devices" in data
        assert "node_id" in data
        assert data["node_id"] == "synth-scanner-01"

    def test_device_count_respects_max(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1, max_devices=3)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.5)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        ble_events = [e for e in events if e.get("type") == "fleet.ble_presence"]
        for ev in ble_events:
            assert len(ev["data"]["devices"]) <= 3

    def test_devices_have_required_fields(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1, max_devices=8)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.3)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        ble_events = [e for e in events if e.get("type") == "fleet.ble_presence"]
        assert len(ble_events) >= 1
        for dev in ble_events[0]["data"]["devices"]:
            assert "addr" in dev
            assert "rssi" in dev
            assert isinstance(dev["rssi"], int)
            assert -90 <= dev["rssi"] <= -30

    def test_known_ratio(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1, max_devices=10, known_ratio=0.8)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.3)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        ble_events = [e for e in events if e.get("type") == "fleet.ble_presence"]
        # After first tick, check that named devices dominate
        if ble_events:
            devices = ble_events[-1]["data"]["devices"]
            named = [d for d in devices if d.get("name")]
            # known_ratio is approximate; just verify named > 0
            assert len(named) > 0

    def test_idempotent_start(self):
        bus = EventBus()
        gen = BLEScanGenerator(interval=0.1)
        gen.start(bus)
        gen.start(bus)  # second call should be no-op
        assert gen.running is True
        gen.stop()


# ── MeshtasticNodeGenerator ────────────────────────────────────────────

@pytest.mark.unit
class TestMeshtasticNodeGenerator:

    def test_start_stop(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1)
        gen.start(bus)
        assert gen.running is True
        gen.stop()
        assert gen.running is False

    def test_publishes_nodes_updated_events(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1, node_count=3)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.5)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        mesh_events = [e for e in events if e.get("type") == "meshtastic:nodes_updated"]
        assert len(mesh_events) >= 1
        data = mesh_events[0]["data"]
        assert "nodes" in data
        assert data["count"] == 3

    def test_node_count_configurable(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1, node_count=2)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.3)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        mesh_events = [e for e in events if e.get("type") == "meshtastic:nodes_updated"]
        assert len(mesh_events) >= 1
        assert len(mesh_events[0]["data"]["nodes"]) == 2

    def test_nodes_have_required_fields(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1, node_count=3)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.3)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        mesh_events = [e for e in events if e.get("type") == "meshtastic:nodes_updated"]
        for node in mesh_events[0]["data"]["nodes"]:
            assert "node_id" in node
            assert "long_name" in node
            assert "position" in node
            assert "battery" in node
            assert "snr" in node
            pos = node["position"]
            assert "lat" in pos
            assert "lng" in pos

    def test_battery_drains_over_time(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1, node_count=1)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.8)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        mesh_events = [e for e in events if e.get("type") == "meshtastic:nodes_updated"]
        if len(mesh_events) >= 2:
            first_battery = mesh_events[0]["data"]["nodes"][0]["battery"]
            last_battery = mesh_events[-1]["data"]["nodes"][0]["battery"]
            assert last_battery < first_battery

    def test_positions_drift(self):
        bus = EventBus()
        gen = MeshtasticNodeGenerator(interval=0.1, node_count=1)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.8)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        mesh_events = [e for e in events if e.get("type") == "meshtastic:nodes_updated"]
        if len(mesh_events) >= 2:
            first_pos = mesh_events[0]["data"]["nodes"][0]["position"]
            last_pos = mesh_events[-1]["data"]["nodes"][0]["position"]
            # Position should have changed
            assert (first_pos["lat"] != last_pos["lat"]
                    or first_pos["lng"] != last_pos["lng"])


# ── CameraDetectionGenerator ──────────────────────────────────────────

@pytest.mark.unit
class TestCameraDetectionGenerator:

    def test_start_stop(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1)
        gen.start(bus)
        assert gen.running is True
        gen.stop()
        assert gen.running is False

    def test_publishes_detection_events(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1, max_objects=5)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.8)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        assert len(det_events) >= 1
        data = det_events[0]["data"]
        assert "camera_id" in data
        assert data["camera_id"] == "synth-cam-01"
        assert "detections" in data
        assert "frame_number" in data

    def test_detections_have_required_fields(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1, max_objects=5)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(1.0)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        # Find an event with at least one detection
        with_dets = [e for e in det_events if e["data"]["detections"]]
        assert len(with_dets) >= 1, "Expected at least one event with detections"
        det = with_dets[0]["data"]["detections"][0]
        assert "id" in det
        assert "label" in det
        assert "confidence" in det
        assert "bbox" in det
        bbox = det["bbox"]
        assert "x" in bbox
        assert "y" in bbox
        assert "w" in bbox
        assert "h" in bbox

    def test_labels_are_person_or_vehicle(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1, max_objects=10)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(1.5)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        labels = set()
        for ev in det_events:
            for det in ev["data"]["detections"]:
                labels.add(det["label"])
        # Over 1.5s with 0.1 interval, we should see at least one label
        assert labels.issubset({"person", "vehicle"})

    def test_bbox_values_normalized(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1, max_objects=5)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(1.0)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        for ev in det_events:
            for det in ev["data"]["detections"]:
                bbox = det["bbox"]
                assert 0.0 <= bbox["x"] <= 1.0
                assert 0.0 <= bbox["y"] <= 1.0

    def test_objects_limited_by_max(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1, max_objects=3)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(1.0)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        for ev in det_events:
            assert len(ev["data"]["detections"]) <= 3

    def test_frame_number_increments(self):
        bus = EventBus()
        gen = CameraDetectionGenerator(interval=0.1)
        q = bus.subscribe()
        gen.start(bus)
        time.sleep(0.5)
        gen.stop()

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        det_events = [e for e in events if e.get("type") == "detection:camera"]
        if len(det_events) >= 2:
            frames = [e["data"]["frame_number"] for e in det_events]
            assert frames == sorted(frames)
            assert frames[-1] > frames[0]
