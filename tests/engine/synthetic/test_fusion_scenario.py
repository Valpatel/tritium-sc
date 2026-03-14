# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the FusionScenario — correlated multi-sensor target fusion demo."""

from __future__ import annotations

import time

import pytest

from engine.comms.event_bus import EventBus
from engine.synthetic.fusion_scenario import (
    SCENARIO_DESCRIPTION,
    FusionScenario,
    _enrich_oui,
    _interpolate_path,
)
from engine.tactical.geofence import GeofenceEngine
from engine.tactical.target_tracker import TargetTracker

pytestmark = pytest.mark.unit


# ── Helper ────────────────────────────────────────────────────────────────

def _drain_events(bus: EventBus, timeout: float = 0.5) -> list[dict]:
    """Subscribe and drain all events."""
    import queue as _q
    q = bus.subscribe()
    deadline = time.monotonic() + timeout
    msgs = []
    while time.monotonic() < deadline:
        try:
            msgs.append(q.get(timeout=0.05))
        except _q.Empty:
            pass
    bus.unsubscribe(q)
    return msgs


# ── Path interpolation ────────────────────────────────────────────────────

class TestPathInterpolation:

    def test_empty_path_returns_origin(self):
        assert _interpolate_path([], 0.0) == (0.0, 0.0)

    def test_index_zero_returns_first_point(self):
        path = [(1.0, 2.0), (3.0, 4.0)]
        assert _interpolate_path(path, 0.0) == (1.0, 2.0)

    def test_index_at_end_returns_last_point(self):
        path = [(1.0, 2.0), (3.0, 4.0)]
        assert _interpolate_path(path, 1.0) == (3.0, 4.0)

    def test_midpoint_interpolation(self):
        path = [(0.0, 0.0), (10.0, 10.0)]
        x, y = _interpolate_path(path, 0.5)
        assert abs(x - 5.0) < 0.01
        assert abs(y - 5.0) < 0.01

    def test_beyond_end_clamps(self):
        path = [(0.0, 0.0), (1.0, 1.0)]
        assert _interpolate_path(path, 5.0) == (1.0, 1.0)


# ── OUI enrichment ────────────────────────────────────────────────────────

class TestOUIEnrichment:

    def test_apple_phone(self):
        result = _enrich_oui("AA:11:22:33:44:01")
        assert result["manufacturer"] == "Apple Inc."
        assert result["device_class"] == "smartphone"

    def test_apple_wearable(self):
        result = _enrich_oui("AA:22:33:44:55:01")
        assert result["manufacturer"] == "Apple Inc."
        assert result["device_class"] == "wearable"

    def test_samsung(self):
        result = _enrich_oui("BB:11:22:33:44:01")
        assert result["manufacturer"] == "Samsung Electronics"

    def test_unknown_prefix(self):
        result = _enrich_oui("CC:CC:CC:CC:CC:CC")
        assert result["manufacturer"] == "Unknown"
        assert result["device_class"] == "unknown"


# ── Scenario description ──────────────────────────────────────────────────

class TestScenarioDescription:

    def test_has_required_keys(self):
        assert "name" in SCENARIO_DESCRIPTION
        assert "description" in SCENARIO_DESCRIPTION
        assert "actors" in SCENARIO_DESCRIPTION
        assert "demonstrated_capabilities" in SCENARIO_DESCRIPTION
        assert "geofence_zone" in SCENARIO_DESCRIPTION

    def test_has_three_actors(self):
        assert len(SCENARIO_DESCRIPTION["actors"]) == 3

    def test_actor_ids(self):
        ids = [a["id"] for a in SCENARIO_DESCRIPTION["actors"]]
        assert "person-a" in ids
        assert "vehicle-b" in ids
        assert "person-c" in ids

    def test_capabilities_list_nonempty(self):
        assert len(SCENARIO_DESCRIPTION["demonstrated_capabilities"]) >= 5


# ── FusionScenario lifecycle ──────────────────────────────────────────────

class TestFusionScenarioLifecycle:

    def test_start_stop(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        assert scenario.running is False
        scenario.start()
        assert scenario.running is True
        scenario.stop()
        assert scenario.running is False

    def test_double_start_is_noop(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        scenario.start()  # should not raise
        assert scenario.running is True
        scenario.stop()

    def test_get_scenario_info_when_stopped(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        info = scenario.get_scenario_info()
        assert info["running"] is False
        assert info["tick_count"] == 0
        assert info["dossiers"] == []
        assert "name" in info

    def test_get_dossiers_empty_initially(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        assert scenario.get_dossiers() == []


# ── FusionScenario event emission ─────────────────────────────────────────

class TestFusionScenarioEvents:

    def test_emits_ble_sighting_events(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        q = bus.subscribe()
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        ble_events = [e for e in events if e["type"] == "fleet.ble_sighting"]
        assert len(ble_events) >= 1
        # Should contain sighting data with MAC
        sighting = ble_events[0]["data"]["sighting"]
        assert "mac" in sighting
        assert "rssi" in sighting
        assert "manufacturer" in sighting

    def test_emits_camera_detection_events(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        q = bus.subscribe()
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        cam_events = [e for e in events if e["type"] == "detection:camera:fusion"]
        assert len(cam_events) >= 1
        det = cam_events[0]["data"]["detection"]
        assert "label" in det
        assert det["label"] in ("person", "car")
        assert "world_position" in det

    def test_emits_dossier_update_events(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        q = bus.subscribe()
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        dossier_events = [e for e in events if e["type"] == "demo:dossier_update"]
        assert len(dossier_events) >= 1
        dossiers = dossier_events[-1]["data"]["dossiers"]
        assert len(dossiers) == 3  # all three actors


# ── Tracker integration ───────────────────────────────────────────────────

class TestFusionTrackerIntegration:

    def test_injects_ble_targets_into_tracker(self):
        bus = EventBus()
        tracker = TargetTracker()
        scenario = FusionScenario(
            event_bus=bus, target_tracker=tracker, interval=0.1
        )
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        targets = tracker.get_all()
        ble_targets = [t for t in targets if t.source == "ble"]
        # 4 BLE devices total across 3 actors
        assert len(ble_targets) >= 3

    def test_injects_camera_targets_into_tracker(self):
        bus = EventBus()
        tracker = TargetTracker()
        scenario = FusionScenario(
            event_bus=bus, target_tracker=tracker, interval=0.1
        )
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        targets = tracker.get_all()
        yolo_targets = [t for t in targets if t.source == "yolo"]
        # At least person + car + person detections
        assert len(yolo_targets) >= 1

    def test_ble_targets_have_positions(self):
        bus = EventBus()
        tracker = TargetTracker()
        scenario = FusionScenario(
            event_bus=bus, target_tracker=tracker, interval=0.1
        )
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        targets = tracker.get_all()
        ble_targets = [t for t in targets if t.source == "ble"]
        for t in ble_targets:
            # Position should be non-zero (actors start at non-origin positions)
            assert t.position != (0.0, 0.0), f"BLE target {t.target_id} at origin"

    def test_target_trails_recorded(self):
        bus = EventBus()
        tracker = TargetTracker()
        scenario = FusionScenario(
            event_bus=bus, target_tracker=tracker, interval=0.1
        )
        scenario.start()
        time.sleep(0.8)
        scenario.stop()

        # Check that at least one BLE target has a trail
        targets = tracker.get_all()
        ble_targets = [t for t in targets if t.source == "ble"]
        has_trail = False
        for t in ble_targets:
            trail = tracker.history.get_trail(t.target_id)
            if len(trail) >= 2:
                has_trail = True
                break
        assert has_trail, "Expected at least one BLE target with movement trail"


# ── Geofence integration ──────────────────────────────────────────────────

class TestFusionGeofence:

    def test_adds_restricted_zone(self):
        bus = EventBus()
        geofence = GeofenceEngine(event_bus=bus)
        scenario = FusionScenario(
            event_bus=bus, geofence_engine=geofence, interval=0.1
        )
        scenario.start()
        time.sleep(0.3)

        zones = geofence.list_zones()
        assert len(zones) == 1
        assert zones[0].zone_id == "demo-restricted-01"
        assert zones[0].zone_type == "restricted"

        scenario.stop()

    def test_removes_zone_on_stop(self):
        bus = EventBus()
        geofence = GeofenceEngine(event_bus=bus)
        scenario = FusionScenario(
            event_bus=bus, geofence_engine=geofence, interval=0.1
        )
        scenario.start()
        time.sleep(0.2)
        scenario.stop()

        zones = geofence.list_zones()
        assert len(zones) == 0

    def test_person_c_triggers_geofence_alert(self):
        """Person C's path enters the restricted zone — should emit alert."""
        bus = EventBus()
        geofence = GeofenceEngine(event_bus=bus)
        q = bus.subscribe()
        scenario = FusionScenario(
            event_bus=bus, geofence_engine=geofence, interval=0.1
        )
        scenario.start()
        # Person C's path takes several ticks to reach the zone
        time.sleep(3.0)
        scenario.stop()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        geo_alerts = [e for e in events if e["type"] == "demo:geofence_alert"]
        # Person C should have entered the restricted zone
        person_c_alerts = [
            e for e in geo_alerts
            if e["data"]["actor_id"] == "person-c"
        ]
        assert len(person_c_alerts) >= 1, (
            "Expected Person C to trigger a geofence alert"
        )
        assert person_c_alerts[0]["data"]["zone_type"] == "restricted"


# ── Dossier building ──────────────────────────────────────────────────────

class TestDossierBuilding:

    def test_dossiers_accumulate_signals(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        dossiers = scenario.get_dossiers()
        assert len(dossiers) == 3

        # Person A should have 3 signals: 2 BLE + 1 camera
        person_a = next(d for d in dossiers if d["actor_id"] == "person-a")
        assert len(person_a["signals"]) == 3
        assert person_a["confidence"] > 0.5

        # Vehicle B should have 2 signals: 1 BLE + 1 camera
        vehicle_b = next(d for d in dossiers if d["actor_id"] == "vehicle-b")
        assert len(vehicle_b["signals"]) == 2

    def test_dossiers_have_uuids(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.3)
        scenario.stop()

        dossiers = scenario.get_dossiers()
        uuids = [d["dossier_uuid"] for d in dossiers]
        # All unique
        assert len(set(uuids)) == len(uuids)
        # All non-empty
        assert all(u for u in uuids)

    def test_dossiers_have_enrichment(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.3)
        scenario.stop()

        dossiers = scenario.get_dossiers()
        person_a = next(d for d in dossiers if d["actor_id"] == "person-a")
        enrichment = person_a["enrichment"]
        # Should have enrichment for both BLE devices
        assert "AA:11:22:33:44:01" in enrichment
        assert enrichment["AA:11:22:33:44:01"]["manufacturer"] == "Apple Inc."
        assert "AA:22:33:44:55:01" in enrichment
        assert enrichment["AA:22:33:44:55:01"]["device_class"] == "wearable"

    def test_person_c_has_unknown_device_class(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.3)
        scenario.stop()

        dossiers = scenario.get_dossiers()
        person_c = next(d for d in dossiers if d["actor_id"] == "person-c")
        enrichment = person_c["enrichment"]
        assert "DD:EE:FF:00:11:01" in enrichment
        assert enrichment["DD:EE:FF:00:11:01"]["device_class"] == "unknown"

    def test_dossiers_track_camera_detections_count(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.5)
        scenario.stop()

        dossiers = scenario.get_dossiers()
        for d in dossiers:
            assert d["camera_detections"] >= 1

    def test_scenario_info_includes_live_dossiers(self):
        bus = EventBus()
        scenario = FusionScenario(event_bus=bus, interval=0.1)
        scenario.start()
        time.sleep(0.3)
        scenario.stop()

        info = scenario.get_scenario_info()
        assert "dossiers" in info
        assert len(info["dossiers"]) == 3
        assert info["tick_count"] >= 1
        assert "name" in info
        assert "actors" in info


# ── DemoController fusion integration ─────────────────────────────────────

class TestDemoControllerFusion:

    def test_demo_controller_includes_fusion_generator(self):
        from engine.synthetic.demo_mode import DemoController

        bus = EventBus()
        ctrl = DemoController(event_bus=bus)
        ctrl.start()

        status = ctrl.status()
        names = [g["name"] for g in status["generators"]]
        assert "FusionScenario" in names

        ctrl.stop()

    def test_demo_controller_fusion_produces_events(self):
        from engine.synthetic.demo_mode import DemoController

        bus = EventBus()
        q = bus.subscribe()
        ctrl = DemoController(event_bus=bus)
        ctrl.start()
        time.sleep(3.0)
        ctrl.stop()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        types = {e["type"] for e in events}
        assert "fleet.ble_sighting" in types
        assert "detection:camera:fusion" in types
        assert "demo:dossier_update" in types

    def test_demo_controller_scenario_info(self):
        from engine.synthetic.demo_mode import DemoController

        bus = EventBus()
        ctrl = DemoController(event_bus=bus)

        # Before start — static info
        info = ctrl.get_scenario_info()
        assert info["running"] is False
        assert "name" in info

        ctrl.start()
        time.sleep(0.5)
        info = ctrl.get_scenario_info()
        assert info["running"] is True
        assert len(info["dossiers"]) == 3

        ctrl.stop()

    def test_demo_started_event_includes_fusion(self):
        from engine.synthetic.demo_mode import DemoController

        bus = EventBus()
        q = bus.subscribe()
        ctrl = DemoController(event_bus=bus)
        ctrl.start()

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        started = [e for e in events if e["type"] == "demo:started"]
        assert len(started) == 1
        assert started[0]["data"]["fusion_scenario"] is True

        ctrl.stop()

    def test_demo_controller_stop_cleans_up_fusion(self):
        from engine.synthetic.demo_mode import DemoController

        bus = EventBus()
        ctrl = DemoController(event_bus=bus)
        ctrl.start()
        ctrl.stop()

        status = ctrl.status()
        assert status["generator_count"] == 0


# ── API router tests for /api/demo/scenario ───────────────────────────────

class TestDemoScenarioRouter:

    def test_scenario_endpoint_without_controller(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.demo import router as demo_router

        app = FastAPI()
        app.include_router(demo_router)

        client = TestClient(app)
        resp = client.get("/api/demo/scenario")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert "actors" in data
        assert len(data["actors"]) == 3
        assert "demonstrated_capabilities" in data

    def test_scenario_endpoint_with_controller(self):
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.demo import router as demo_router

        app = FastAPI()
        app.include_router(demo_router)

        bus = EventBus()
        mock_amy = MagicMock()
        mock_amy.event_bus = bus
        mock_amy.target_tracker = None
        app.state.amy = mock_amy

        client = TestClient(app)

        # Start demo
        client.post("/api/demo/start")
        time.sleep(0.5)

        resp = client.get("/api/demo/scenario")
        assert resp.status_code == 200
        data = resp.json()
        assert "dossiers" in data
        assert "actors" in data

        # Stop
        client.post("/api/demo/stop")
