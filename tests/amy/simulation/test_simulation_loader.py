"""Unit tests for simulation layout loader."""

from __future__ import annotations

import json
import queue
import threading

import pytest

from amy.simulation.engine import SimulationEngine
from amy.simulation.loader import load_layout


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


def _write_layout(tmp_path, objects: list[dict]) -> str:
    """Write a TritiumLevelFormat JSON file and return its path."""
    layout = {"format": "TritiumLevelFormat", "version": 1, "objects": objects}
    path = tmp_path / "test_level.json"
    path.write_text(json.dumps(layout))
    return str(path)


class TestLoadLayoutRovers:
    def test_load_rovers(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "robot",
                "position": {"x": 5.0, "y": 0.0, "z": 3.0},
                "properties": {"name": "Scout Bot"},
            }
        ])
        count = load_layout(path, engine)
        assert count == 1
        targets = engine.get_targets()
        assert len(targets) == 1
        t = targets[0]
        assert t.alliance == "friendly"
        assert t.asset_type == "rover"
        assert t.position == (5.0, 3.0)
        assert t.name == "Scout Bot"


class TestLoadLayoutDrones:
    def test_load_drones(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "drone",
                "position": {"x": 1.0, "y": 0.0, "z": 2.0},
                "properties": {"name": "Sky Eye"},
            }
        ])
        count = load_layout(path, engine)
        assert count == 1
        t = engine.get_targets()[0]
        assert t.alliance == "friendly"
        assert t.asset_type == "drone"
        assert t.speed == 4.0


class TestLoadLayoutTurrets:
    def test_load_turrets(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "turret",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "properties": {"name": "Sentry A"},
            }
        ])
        count = load_layout(path, engine)
        assert count == 1
        t = engine.get_targets()[0]
        assert t.alliance == "friendly"
        assert t.asset_type == "turret"
        assert t.speed == 0.0


class TestLoadLayoutHostiles:
    def test_load_hostiles(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "person",
                "position": {"x": 10.0, "y": 0.0, "z": -5.0},
                "properties": {"name": "Intruder Alpha"},
            }
        ])
        count = load_layout(path, engine)
        assert count == 1
        t = engine.get_targets()[0]
        assert t.alliance == "hostile"
        assert t.asset_type == "person"
        assert t.speed == 1.5


class TestLoadLayoutFiltering:
    def test_skip_cameras(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "camera",
                "position": {"x": 0.0, "y": 2.0, "z": 0.0},
                "properties": {"name": "Cam 1"},
            }
        ])
        count = load_layout(path, engine)
        assert count == 0
        assert len(engine.get_targets()) == 0

    def test_empty_layout(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [])
        count = load_layout(path, engine)
        assert count == 0


class TestLoadLayoutWaypoints:
    def test_waypoints_loaded(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {
                "type": "rover",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "properties": {
                    "name": "Patrol Bot",
                    "patrol_waypoints": [
                        {"x": 5.0, "z": 0.0},
                        {"x": 5.0, "z": 5.0},
                        {"x": 0.0, "z": 5.0},
                    ],
                },
            }
        ])
        count = load_layout(path, engine)
        assert count == 1
        t = engine.get_targets()[0]
        assert len(t.waypoints) == 3
        assert t.waypoints[0] == (5.0, 0.0)
        assert t.waypoints[1] == (5.0, 5.0)
        assert t.waypoints[2] == (0.0, 5.0)


class TestLoadLayoutSpecificTypes:
    """Test that all specific asset types are correctly mapped."""

    @pytest.mark.parametrize("obj_type,expected_asset,expected_speed", [
        ("patrol_rover", "rover", 2.0),
        ("interceptor_bot", "rover", 3.5),
        ("sentry_turret", "turret", 0.0),
        ("recon_drone", "drone", 5.0),
        ("heavy_drone", "drone", 2.5),
        ("scout_drone", "scout_drone", 4.0),
        ("tank", "tank", 3.0),
        ("apc", "apc", 5.0),
        ("heavy_turret", "heavy_turret", 0.0),
        ("missile_turret", "missile_turret", 0.0),
    ])
    def test_specific_types(self, tmp_path, obj_type, expected_asset, expected_speed):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {"type": obj_type, "position": {"x": 1.0, "y": 0.0, "z": 2.0},
             "properties": {"name": f"Test {obj_type}"}},
        ])
        count = load_layout(path, engine)
        assert count == 1
        t = engine.get_targets()[0]
        assert t.alliance == "friendly"
        assert t.asset_type == expected_asset
        assert t.speed == expected_speed

    @pytest.mark.parametrize("obj_type", [
        "security_camera", "ptz_camera", "dome_camera",
        "motion_sensor", "microphone_sensor", "speaker", "floodlight",
        "building", "house", "street", "sidewalk", "fence",
    ])
    def test_skip_types(self, tmp_path, obj_type):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {"type": obj_type, "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "properties": {"name": "Should Skip"}},
        ])
        count = load_layout(path, engine)
        assert count == 0

    @pytest.mark.parametrize("zone_type", [
        "activity_zone", "entry_exit_zone", "tripwire", "restricted_area",
    ])
    def test_zone_types_skipped(self, tmp_path, zone_type):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {"type": zone_type, "position": {"x": 5.0, "y": 0.0, "z": 5.0},
             "properties": {"name": "Test Zone"}},
        ])
        count = load_layout(path, engine)
        assert count == 0


class TestLoadLayoutWaypointAssignment:
    def test_waypoints_assigned_to_nearest_target(self, tmp_path):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        path = _write_layout(tmp_path, [
            {"type": "rover", "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "properties": {"name": "Near Rover"}},
            {"type": "rover", "position": {"x": 20.0, "y": 0.0, "z": 20.0},
             "properties": {"name": "Far Rover"}},
            {"type": "patrol_waypoint", "position": {"x": 1.0, "y": 0.0, "z": 1.0}},
        ])
        count = load_layout(path, engine)
        assert count == 2
        targets = engine.get_targets()
        near = [t for t in targets if t.name == "Near Rover"][0]
        far = [t for t in targets if t.name == "Far Rover"][0]
        assert len(near.waypoints) == 1
        assert near.waypoints[0] == (1.0, 1.0)
        assert len(far.waypoints) == 0


class TestLoadZones:
    def test_load_zones(self, tmp_path):
        from amy.simulation.loader import load_zones
        path = _write_layout(tmp_path, [
            {"type": "activity_zone", "position": {"x": 5.0, "y": 0.0, "z": 5.0},
             "properties": {"name": "Play Area"}},
            {"type": "restricted_area", "position": {"x": -5.0, "y": 0.0, "z": -5.0},
             "properties": {"name": "No-Go Zone"}},
            {"type": "rover", "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "properties": {"name": "Rover"}},
        ])
        zones = load_zones(path)
        assert len(zones) == 2
        zone_names = {z["name"] for z in zones}
        assert zone_names == {"Play Area", "No-Go Zone"}


class TestSampleLayout:
    """Validate the sample neighborhood layout shipped with the project."""

    def test_sample_layout_loads(self):
        """scenarios/neighborhood_default.json should load without errors."""
        import os
        layout_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "neighborhood_default.json"
        )
        if not os.path.exists(layout_path):
            pytest.skip("Sample layout not found")
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        count = load_layout(layout_path, engine)
        # Should create targets (rovers, drones, turrets, interceptor)
        assert count >= 4
        targets = engine.get_targets()
        # Verify we got the expected mix
        alliances = {t.alliance for t in targets}
        assert "friendly" in alliances
        asset_types = {t.asset_type for t in targets}
        assert "rover" in asset_types
        assert "turret" in asset_types
        assert "scout_drone" in asset_types
        assert "tank" in asset_types
        assert "heavy_turret" in asset_types
        assert "missile_turret" in asset_types

    def test_sample_layout_zones(self):
        """Sample layout should contain zone definitions."""
        import os
        from amy.simulation.loader import load_zones
        layout_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "neighborhood_default.json"
        )
        if not os.path.exists(layout_path):
            pytest.skip("Sample layout not found")
        zones = load_zones(layout_path)
        assert len(zones) >= 2
        zone_types = {z["type"] for z in zones}
        assert "activity_zone" in zone_types
        assert "restricted_area" in zone_types
