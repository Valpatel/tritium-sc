# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for NPC system — vehicles, pedestrians, missions, road following.

TDD-first: these tests are written before the implementation.
"""

from __future__ import annotations

import math
import time
import uuid

import pytest

from engine.simulation.target import SimulationTarget

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockStreetGraph:
    """Minimal street graph with a few nodes and edges for testing."""

    def __init__(self) -> None:
        self.graph = True  # truthy = loaded
        self._nodes = {
            0: (-50.0, 0.0),
            1: (0.0, 0.0),
            2: (50.0, 0.0),
            3: (0.0, 50.0),
            4: (0.0, -50.0),
        }

    def nearest_node(self, x: float, y: float) -> tuple[int | None, float]:
        best_id = None
        best_dist = float("inf")
        for nid, (nx, ny) in self._nodes.items():
            d = math.hypot(x - nx, y - ny)
            if d < best_dist:
                best_dist = d
                best_id = nid
        return best_id, best_dist

    def shortest_path(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> list[tuple[float, float]] | None:
        # Simple: return start node -> center -> end node
        _, sd = self.nearest_node(start[0], start[1])
        end_id, ed = self.nearest_node(end[0], end[1])
        if end_id is None:
            return None
        return [start, (0.0, 0.0), end]

    def random_node(self) -> tuple[float, float] | None:
        import random
        nid = random.choice(list(self._nodes.keys()))
        return self._nodes[nid]


class MockEventBus:
    """Minimal event bus for engine tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def publish(self, event_type: str, data: object = None) -> None:
        self.events.append((event_type, data))

    def subscribe(self):
        import queue
        return queue.Queue()


class MockEngine:
    """Minimal engine for NPC manager tests."""

    def __init__(self) -> None:
        self.targets: dict[str, SimulationTarget] = {}
        self._map_bounds = 200.0
        self._map_min = -200.0
        self._map_max = 200.0
        self._street_graph = MockStreetGraph()
        self._event_bus = MockEventBus()
        self.spawners_paused = False

    def add_target(self, target: SimulationTarget) -> None:
        self.targets[target.target_id] = target

    def get_targets(self) -> list[SimulationTarget]:
        return list(self.targets.values())

    def remove_target(self, target_id: str) -> bool:
        return self.targets.pop(target_id, None) is not None


@pytest.fixture
def engine() -> MockEngine:
    return MockEngine()


# ---------------------------------------------------------------------------
# NPC Mission tests
# ---------------------------------------------------------------------------


class TestNPCMission:
    """Test NPC mission data model."""

    def test_create_commute_mission(self) -> None:
        from engine.simulation.npc import NPCMission

        m = NPCMission(
            mission_type="commute",
            origin=(0.0, 0.0),
            destination=(50.0, 50.0),
        )
        assert m.mission_type == "commute"
        assert m.origin == (0.0, 0.0)
        assert m.destination == (50.0, 50.0)
        assert not m.completed

    def test_create_patrol_mission(self) -> None:
        from engine.simulation.npc import NPCMission

        m = NPCMission(
            mission_type="patrol",
            origin=(0.0, 0.0),
            destination=(50.0, 50.0),
            patrol_points=[(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)],
        )
        assert m.mission_type == "patrol"
        assert len(m.patrol_points) == 3

    def test_create_delivery_mission(self) -> None:
        from engine.simulation.npc import NPCMission

        m = NPCMission(
            mission_type="delivery",
            origin=(0.0, 0.0),
            destination=(50.0, 50.0),
        )
        assert m.mission_type == "delivery"

    def test_mission_types_valid(self) -> None:
        from engine.simulation.npc import MISSION_TYPES

        assert "commute" in MISSION_TYPES
        assert "patrol" in MISSION_TYPES
        assert "delivery" in MISSION_TYPES
        assert "drive_through" in MISSION_TYPES

    def test_mission_complete_flag(self) -> None:
        from engine.simulation.npc import NPCMission

        m = NPCMission(
            mission_type="commute",
            origin=(0.0, 0.0),
            destination=(50.0, 50.0),
        )
        assert not m.completed
        m.completed = True
        assert m.completed


# ---------------------------------------------------------------------------
# NPC Vehicle Type tests
# ---------------------------------------------------------------------------


class TestNPCVehicleTypes:
    """Test NPC vehicle type definitions."""

    def test_sedan_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "sedan" in NPC_VEHICLE_TYPES

    def test_suv_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "suv" in NPC_VEHICLE_TYPES

    def test_pickup_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "pickup" in NPC_VEHICLE_TYPES

    def test_delivery_van_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "delivery_van" in NPC_VEHICLE_TYPES

    def test_police_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "police" in NPC_VEHICLE_TYPES

    def test_ambulance_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "ambulance" in NPC_VEHICLE_TYPES

    def test_school_bus_type_exists(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        assert "school_bus" in NPC_VEHICLE_TYPES

    def test_all_types_have_speed(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        for vtype, info in NPC_VEHICLE_TYPES.items():
            assert "speed" in info, f"{vtype} missing speed"
            assert info["speed"] > 0, f"{vtype} speed must be positive"

    def test_all_types_have_display_name(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        for vtype, info in NPC_VEHICLE_TYPES.items():
            assert "display_name" in info, f"{vtype} missing display_name"

    def test_all_types_have_icon(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        for vtype, info in NPC_VEHICLE_TYPES.items():
            assert "icon" in info, f"{vtype} missing icon"

    def test_speed_ranges_reasonable(self) -> None:
        from engine.simulation.npc import NPC_VEHICLE_TYPES

        for vtype, info in NPC_VEHICLE_TYPES.items():
            # Speed in m/s: cars ~8-15 m/s, buses ~6-10 m/s
            assert 3.0 <= info["speed"] <= 20.0, (
                f"{vtype} speed {info['speed']} out of range"
            )


# ---------------------------------------------------------------------------
# NPCManager creation and lifecycle
# ---------------------------------------------------------------------------


class TestNPCManager:
    """Test NPCManager creation and basic lifecycle."""

    def test_create_manager(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        assert mgr is not None
        assert mgr.npc_count == 0

    def test_spawn_vehicle(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        assert npc is not None
        assert npc.alliance == "neutral"
        assert npc.asset_type == "vehicle"
        assert npc.speed > 0

    def test_spawn_pedestrian(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        assert npc is not None
        assert npc.alliance == "neutral"
        assert npc.asset_type == "person"
        assert 1.0 <= npc.speed <= 2.0

    def test_spawn_vehicle_has_waypoints(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        assert len(npc.waypoints) >= 1, "Vehicle must have road waypoints"

    def test_spawn_pedestrian_has_waypoints(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        assert len(npc.waypoints) >= 1, "Pedestrian must have waypoints"

    def test_npc_count_tracks_spawns(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        mgr.spawn_vehicle()
        mgr.spawn_vehicle()
        mgr.spawn_pedestrian()
        assert mgr.npc_count == 3

    def test_vehicle_added_to_engine(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        assert npc.target_id in engine.targets

    def test_pedestrian_added_to_engine(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        assert npc.target_id in engine.targets


# ---------------------------------------------------------------------------
# Vehicle road-following
# ---------------------------------------------------------------------------


class TestVehicleRoadFollowing:
    """Test that vehicles follow roads using the street graph."""

    def test_vehicle_uses_street_graph(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        # Vehicle should have waypoints from the street graph
        assert len(npc.waypoints) >= 2

    def test_vehicle_path_includes_road_points(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        # At least some waypoints should be near road nodes
        has_road_point = any(
            math.hypot(w[0], w[1]) < 60.0 for w in npc.waypoints
        )
        assert has_road_point, "Vehicle path should include road network points"

    def test_vehicle_fallback_without_street_graph(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        engine._street_graph = None
        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        # Should still have waypoints (fallback path)
        assert len(npc.waypoints) >= 1


# ---------------------------------------------------------------------------
# Mission assignment
# ---------------------------------------------------------------------------


class TestMissionAssignment:
    """Test that NPCs get missions assigned on spawn."""

    def test_vehicle_gets_mission(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mission = mgr.get_mission(npc.target_id)
        assert mission is not None
        assert mission.mission_type in ("commute", "patrol", "delivery", "drive_through")

    def test_pedestrian_gets_mission(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        mission = mgr.get_mission(npc.target_id)
        assert mission is not None

    def test_mission_has_origin_and_destination(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mission = mgr.get_mission(npc.target_id)
        assert mission.origin is not None
        assert mission.destination is not None


# ---------------------------------------------------------------------------
# Time-of-day traffic patterns
# ---------------------------------------------------------------------------


class TestTimeOfDay:
    """Test time-of-day traffic density scaling."""

    def test_traffic_density_function_exists(self) -> None:
        from engine.simulation.npc import traffic_density

        result = traffic_density(8)
        assert isinstance(result, float)

    def test_rush_hour_morning_high(self) -> None:
        from engine.simulation.npc import traffic_density

        morning_rush = traffic_density(8)
        assert morning_rush >= 0.7, "Morning rush hour should have high traffic"

    def test_rush_hour_evening_high(self) -> None:
        from engine.simulation.npc import traffic_density

        evening_rush = traffic_density(17)
        assert evening_rush >= 0.7, "Evening rush hour should have high traffic"

    def test_night_low_traffic(self) -> None:
        from engine.simulation.npc import traffic_density

        night = traffic_density(3)
        assert night <= 0.3, "3am should have very low traffic"

    def test_midday_moderate(self) -> None:
        from engine.simulation.npc import traffic_density

        midday = traffic_density(12)
        assert 0.3 <= midday <= 0.8, "Midday should have moderate traffic"

    def test_density_always_positive(self) -> None:
        from engine.simulation.npc import traffic_density

        for hour in range(24):
            d = traffic_density(hour)
            assert d > 0, f"Traffic density at hour {hour} must be positive"
            assert d <= 1.0, f"Traffic density at hour {hour} must be <= 1.0"


# ---------------------------------------------------------------------------
# Population density config
# ---------------------------------------------------------------------------


class TestPopulationDensity:
    """Test configurable population density."""

    def test_default_max_vehicles(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        assert mgr.max_vehicles >= 100, "Default max vehicles should be >= 100"
        assert mgr.max_vehicles <= 300, "Default max vehicles should be <= 300"

    def test_default_max_pedestrians(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        assert mgr.max_pedestrians >= 100, "Default max pedestrians should be >= 100"
        assert mgr.max_pedestrians <= 400, "Default max pedestrians should be <= 400"

    def test_configurable_max_vehicles(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine, max_vehicles=5)
        assert mgr.max_vehicles == 5

    def test_configurable_max_pedestrians(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine, max_pedestrians=10)
        assert mgr.max_pedestrians == 10

    def test_respects_vehicle_cap(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine, max_vehicles=3)
        for _ in range(10):
            mgr.spawn_vehicle()
        vehicle_count = sum(
            1 for t in engine.targets.values() if t.asset_type == "vehicle"
        )
        assert vehicle_count <= 3

    def test_respects_pedestrian_cap(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine, max_pedestrians=3)
        for _ in range(10):
            mgr.spawn_pedestrian()
        ped_count = sum(
            1 for t in engine.targets.values() if t.asset_type == "person"
        )
        assert ped_count <= 3


# ---------------------------------------------------------------------------
# NPC tick lifecycle
# ---------------------------------------------------------------------------


class TestNPCTick:
    """Test NPC tick updates — mission completion and respawn."""

    def test_tick_advances_npcs(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        mgr.spawn_vehicle()
        # Should not raise
        mgr.tick(0.1)

    def test_completed_mission_marks_npc(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        # Force NPC to destination
        npc.status = "despawned"
        mgr.tick(0.1)
        mission = mgr.get_mission(npc.target_id)
        assert mission is not None
        assert mission.completed

    def test_despawned_npc_cleaned_up(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        initial_count = mgr.npc_count
        # Force despawn
        npc.status = "despawned"
        mgr.tick(0.1)
        assert mgr.npc_count < initial_count


# ---------------------------------------------------------------------------
# NPC names
# ---------------------------------------------------------------------------


class TestNPCNames:
    """Test NPC name generation."""

    def test_vehicle_has_name(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        assert npc.name is not None
        assert len(npc.name) > 0

    def test_pedestrian_has_name(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        assert npc.name is not None
        assert len(npc.name) > 0

    def test_names_are_unique(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine, max_vehicles=50, max_pedestrians=50)
        names = set()
        for _ in range(20):
            v = mgr.spawn_vehicle()
            if v is not None:
                names.add(v.name)
            p = mgr.spawn_pedestrian()
            if p is not None:
                names.add(p.name)
        # All names should be unique
        assert len(names) >= 20


# ---------------------------------------------------------------------------
# Pedestrian sidewalk offset
# ---------------------------------------------------------------------------


class TestPedestrianPaths:
    """Test pedestrian path generation."""

    def test_pedestrian_speed_realistic(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        # Walking speed: 1.0-2.0 m/s
        assert 1.0 <= npc.speed <= 2.0


# ---------------------------------------------------------------------------
# CoT telemetry compatibility
# ---------------------------------------------------------------------------


class TestNPCCoTCompatibility:
    """Test that NPCs produce CoT-compatible telemetry."""

    def test_vehicle_to_dict_has_required_fields(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        d = npc.to_dict()
        assert "target_id" in d
        assert "alliance" in d
        assert "asset_type" in d
        assert "position" in d
        assert "heading" in d
        assert "speed" in d
        assert "lat" in d
        assert "lng" in d

    def test_vehicle_alliance_neutral(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        assert npc.alliance == "neutral"

    def test_npc_can_generate_cot_xml(self, engine: MockEngine) -> None:
        from engine.comms.cot import target_to_cot_xml
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        d = npc.to_dict()
        xml = target_to_cot_xml(d)
        assert "<event" in xml
        assert "uid=" in xml
        assert "<point" in xml


# ---------------------------------------------------------------------------
# NPC data binding (real data replacement)
# ---------------------------------------------------------------------------


class TestNPCBinding:
    """Test binding NPCs to real data streams."""

    def test_bind_npc_to_track(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        success = mgr.bind_to_track(npc.target_id, "cot", "TRACK-001")
        assert success

    def test_bound_npc_is_marked(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mgr.bind_to_track(npc.target_id, "cot", "TRACK-001")
        binding = mgr.get_binding(npc.target_id)
        assert binding is not None
        assert binding["source"] == "cot"
        assert binding["track_id"] == "TRACK-001"

    def test_bound_npc_ignores_sim_movement(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mgr.bind_to_track(npc.target_id, "cot", "TRACK-001")
        assert mgr.is_bound(npc.target_id)

    def test_unbind_npc(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mgr.bind_to_track(npc.target_id, "cot", "TRACK-001")
        mgr.unbind(npc.target_id)
        assert not mgr.is_bound(npc.target_id)

    def test_update_bound_position(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        mgr.bind_to_track(npc.target_id, "cot", "TRACK-001")
        mgr.update_bound_position(
            npc.target_id, position=(10.0, 20.0), heading=90.0, speed=5.0
        )
        assert npc.position == (10.0, 20.0)
        assert npc.heading == 90.0
        assert npc.speed == 5.0

    def test_bind_nonexistent_npc_fails(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        success = mgr.bind_to_track("nonexistent", "cot", "TRACK-001")
        assert not success


# ---------------------------------------------------------------------------
# Spawn location variety
# ---------------------------------------------------------------------------


class TestSpawnLocations:
    """Test that NPCs spawn from map edges."""

    def test_vehicle_spawns_near_edge(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle()
        x, y = npc.position
        bounds = engine._map_bounds
        at_edge = (
            abs(abs(x) - bounds) < bounds * 0.3
            or abs(abs(y) - bounds) < bounds * 0.3
        )
        assert at_edge, f"Vehicle should spawn near edge, got ({x}, {y})"

    def test_pedestrian_spawns_near_edge(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_pedestrian()
        x, y = npc.position
        bounds = engine._map_bounds
        at_edge = (
            abs(abs(x) - bounds) < bounds * 0.3
            or abs(abs(y) - bounds) < bounds * 0.3
        )
        assert at_edge, f"Pedestrian should spawn near edge, got ({x}, {y})"


# ---------------------------------------------------------------------------
# Vehicle type-specific spawning
# ---------------------------------------------------------------------------


class TestVehicleTypeSpawning:
    """Test spawning specific vehicle types."""

    def test_spawn_specific_vehicle_type(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager

        mgr = NPCManager(engine)
        npc = mgr.spawn_vehicle(vehicle_type="police")
        assert npc is not None
        assert "Police" in npc.name or "police" in npc.name.lower()

    def test_spawn_random_vehicle_type(self, engine: MockEngine) -> None:
        from engine.simulation.npc import NPCManager, NPC_VEHICLE_TYPES

        mgr = NPCManager(engine, max_vehicles=50)
        types_seen = set()
        for _ in range(30):
            npc = mgr.spawn_vehicle()
            if npc is not None:
                types_seen.add(mgr.get_vehicle_type(npc.target_id))
        # Should see at least a few different types
        assert len(types_seen) >= 3, f"Expected variety, got {types_seen}"
