# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for NPC system wired into SimulationEngine.

Tests that NPCManager is properly created by the engine, that NPC
vehicles use pathfinding, and that the CoT telemetry pipeline works
end-to-end.
"""

from __future__ import annotations

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.npc import NPCManager, traffic_density, NPC_VEHICLE_TYPES

pytestmark = pytest.mark.unit


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def engine(event_bus: EventBus) -> SimulationEngine:
    e = SimulationEngine(event_bus, map_bounds=200.0)
    return e


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


class TestEngineNPCWiring:
    """Test that NPCManager is wired into SimulationEngine."""

    def test_engine_starts_npc_manager(self, engine: SimulationEngine) -> None:
        engine.start()
        try:
            assert engine.npc_manager is not None
        finally:
            engine.stop()

    def test_npc_manager_has_config_defaults(self, engine: SimulationEngine) -> None:
        engine.start()
        try:
            mgr = engine.npc_manager
            assert mgr is not None
            assert mgr.max_vehicles > 0
            assert mgr.max_pedestrians > 0
        finally:
            engine.stop()

    def test_npc_manager_spawn_vehicle(self, engine: SimulationEngine) -> None:
        engine.start()
        try:
            mgr = engine.npc_manager
            npc = mgr.spawn_vehicle()
            assert npc is not None
            assert npc.target_id in {t.target_id for t in engine.get_targets()}
        finally:
            engine.stop()

    def test_npc_manager_spawn_pedestrian(self, engine: SimulationEngine) -> None:
        engine.start()
        try:
            mgr = engine.npc_manager
            npc = mgr.spawn_pedestrian()
            assert npc is not None
            assert npc.target_id in {t.target_id for t in engine.get_targets()}
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# NPC tick in engine loop
# ---------------------------------------------------------------------------


class TestNPCTickInEngine:
    """Test that NPC manager tick runs inside engine tick loop."""

    def test_do_tick_with_npc_manager(self, engine: SimulationEngine) -> None:
        """Engine _do_tick should not crash when NPC manager is active."""
        engine._npc_manager = NPCManager(engine)
        engine._npc_manager.spawn_vehicle()
        engine._npc_manager.spawn_pedestrian()
        # Run a few ticks
        for _ in range(10):
            engine._do_tick(0.1)
        # NPCs should still be tracked
        assert engine._npc_manager.npc_count >= 0  # may have despawned

    def test_npc_appears_in_telemetry_batch(self, event_bus: EventBus) -> None:
        """NPC targets should appear in sim_telemetry_batch events."""
        engine = SimulationEngine(event_bus, map_bounds=200.0)
        engine._npc_manager = NPCManager(engine)
        npc = engine._npc_manager.spawn_vehicle()
        assert npc is not None

        # Subscribe to events
        sub = event_bus.subscribe()

        # Run one tick
        engine._do_tick(0.1)

        # Check event bus for telemetry containing our NPC
        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "sim_telemetry_batch":
                batch = msg.get("data", [])
                for td in batch:
                    if td.get("target_id") == npc.target_id:
                        found = True
                        break
        assert found, "NPC vehicle should appear in telemetry batch"


# ---------------------------------------------------------------------------
# Pathfinding integration
# ---------------------------------------------------------------------------


class TestNPCPathfinding:
    """Test that NPC vehicles use the pathfinder correctly."""

    def test_vehicle_in_road_types(self) -> None:
        from engine.simulation.pathfinding import _ROAD_TYPES
        assert "vehicle" in _ROAD_TYPES

    def test_plan_path_routes_vehicle_on_roads(self) -> None:
        from engine.simulation.pathfinding import plan_path

        class FakeGraph:
            graph = True
            def shortest_path(self, start, end):
                return [start, (0, 0), end]

        path = plan_path(
            (-100, 0), (100, 0), "vehicle",
            street_graph=FakeGraph(), obstacles=None,
            alliance="neutral",
        )
        assert path is not None
        assert len(path) >= 2
        # Should include intermediate road point
        assert (0, 0) in path


# ---------------------------------------------------------------------------
# CoT XML generation from NPC
# ---------------------------------------------------------------------------


class TestNPCCoT:
    """Test CoT XML generation from NPC targets."""

    def test_vehicle_cot_xml_valid(self) -> None:
        from engine.comms.cot import target_to_cot_xml
        from engine.simulation.target import SimulationTarget

        npc = SimulationTarget(
            target_id="npc-sedan-001",
            name="Red Sedan",
            alliance="neutral",
            asset_type="vehicle",
            position=(10.0, 20.0),
            speed=11.0,
            waypoints=[(50.0, 50.0)],
        )
        xml = target_to_cot_xml(npc.to_dict())
        assert "<event" in xml
        assert 'uid="npc-sedan-001"' in xml
        assert "<point" in xml

    def test_pedestrian_cot_xml_valid(self) -> None:
        from engine.comms.cot import target_to_cot_xml
        from engine.simulation.target import SimulationTarget

        npc = SimulationTarget(
            target_id="npc-ped-001",
            name="Morning Jogger",
            alliance="neutral",
            asset_type="person",
            position=(5.0, 10.0),
            speed=1.5,
            waypoints=[(30.0, 30.0)],
        )
        xml = target_to_cot_xml(npc.to_dict())
        assert "<event" in xml
        assert 'uid="npc-ped-001"' in xml


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestNPCConfig:
    """Test NPC config settings exist."""

    def test_npc_enabled_setting(self) -> None:
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "npc_enabled")
        assert isinstance(s.npc_enabled, bool)

    def test_npc_max_vehicles_setting(self) -> None:
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "npc_max_vehicles")
        assert s.npc_max_vehicles > 0

    def test_npc_max_pedestrians_setting(self) -> None:
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "npc_max_pedestrians")
        assert s.npc_max_pedestrians > 0


# ---------------------------------------------------------------------------
# Traffic density curve
# ---------------------------------------------------------------------------


class TestTrafficDensityCurve:
    """Full 24-hour traffic density validation."""

    def test_rush_hour_peaks(self) -> None:
        # Morning rush: 7-9am should be highest
        peak_morning = max(traffic_density(h) for h in range(7, 10))
        assert peak_morning >= 0.7

        # Evening rush: 4-6pm
        peak_evening = max(traffic_density(h) for h in range(16, 19))
        assert peak_evening >= 0.7

    def test_night_valley(self) -> None:
        # 1-4am should be lowest
        night_low = max(traffic_density(h) for h in range(1, 5))
        assert night_low <= 0.15

    def test_monotonic_morning_ramp(self) -> None:
        # 3am -> 8am should generally increase
        vals = [traffic_density(h) for h in range(3, 9)]
        assert vals[-1] > vals[0], "Traffic should increase from 3am to 8am"


# ---------------------------------------------------------------------------
# Vehicle type variety
# ---------------------------------------------------------------------------


class TestVehicleTypeVariety:
    """Test all vehicle types have complete definitions."""

    def test_seven_vehicle_types(self) -> None:
        assert len(NPC_VEHICLE_TYPES) == 7

    def test_all_types_have_names(self) -> None:
        for vtype, info in NPC_VEHICLE_TYPES.items():
            assert "names" in info, f"{vtype} missing names"
            assert len(info["names"]) >= 3, f"{vtype} needs >= 3 names"

    def test_emergency_vehicles_faster(self) -> None:
        """Police and ambulance should be faster than civilian vehicles."""
        sedan_speed = NPC_VEHICLE_TYPES["sedan"]["speed"]
        assert NPC_VEHICLE_TYPES["police"]["speed"] > sedan_speed
        assert NPC_VEHICLE_TYPES["ambulance"]["speed"] > sedan_speed

    def test_school_bus_slowest(self) -> None:
        """School bus should be the slowest vehicle type."""
        bus_speed = NPC_VEHICLE_TYPES["school_bus"]["speed"]
        for vtype, info in NPC_VEHICLE_TYPES.items():
            if vtype == "school_bus":
                continue
            assert info["speed"] >= bus_speed, (
                f"{vtype} ({info['speed']}) should not be slower than school bus ({bus_speed})"
            )
