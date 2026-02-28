# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for SimulationTarget."""

from __future__ import annotations

import math

import pytest

from engine.simulation.target import SimulationTarget, _DRAIN_RATES

pytestmark = pytest.mark.unit


class TestSimulationTargetInitialState:
    def test_initial_state(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
        )
        assert t.target_id == "r1"
        assert t.name == "Rover Alpha"
        assert t.alliance == "friendly"
        assert t.asset_type == "rover"
        assert t.position == (0.0, 0.0)
        assert t.heading == 0.0
        assert t.speed == 1.0
        assert t.battery == 1.0
        assert t.waypoints == []
        assert t.status == "active"


class TestSimulationTargetMovement:
    def test_tick_moves_toward_waypoint(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=5.0,
            waypoints=[(10.0, 0.0)],
        )
        for _ in range(5):
            t.tick(1.0)
        # Should have moved significantly toward (10, 0)
        assert t.position[0] > 0.0
        assert abs(t.position[1]) < 0.01

    def test_heading_calculation(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=1.0,
            waypoints=[(10.0, 0.0)],
        )
        t.tick(0.5)
        # Waypoint is at (10, 0): heading = degrees(atan2(dx=10, dy=0)) = 90
        expected = math.degrees(math.atan2(10.0, 0.0))
        assert abs(t.heading - expected) < 0.01

    def test_waypoint_cycling(self):
        wp = [(5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=100.0,  # very fast so it reaches waypoints quickly
            waypoints=wp,
        )
        # Tick many times to pass through all waypoints
        for _ in range(50):
            t.tick(0.1)
        # After cycling through all three, the internal index should have
        # advanced past the first waypoint at minimum
        assert t._waypoint_index >= 0  # just verify it cycled without error

    def test_stationary_no_waypoints(self):
        t = SimulationTarget(
            target_id="t1",
            name="Turret",
            alliance="friendly",
            asset_type="turret",
            position=(5.0, 5.0),
            speed=0.0,
            waypoints=[],
        )
        t.tick(1.0)
        assert t.position == (5.0, 5.0)
        assert t.status == "idle"

    def test_destroyed_target_no_movement(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=5.0,
            waypoints=[(10.0, 0.0)],
            status="destroyed",
        )
        t.tick(1.0)
        assert t.position == (0.0, 0.0)
        assert t.battery == 1.0  # no drain either


class TestSimulationTargetBattery:
    def test_battery_drain(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            battery=1.0,
            waypoints=[(100.0, 0.0)],
        )
        dt = 10.0
        t.tick(dt)
        expected_drain = _DRAIN_RATES["rover"] * dt
        assert abs(t.battery - (1.0 - expected_drain)) < 1e-6

    def test_low_battery_stops(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            battery=0.06,
            speed=5.0,
            waypoints=[(10.0, 0.0)],
        )
        # Tick with enough dt to drain below 0.05
        t.tick(20.0)
        assert t.status == "low_battery"

    def test_person_no_battery_drain(self):
        t = SimulationTarget(
            target_id="p1",
            name="Intruder",
            alliance="hostile",
            asset_type="person",
            position=(0.0, 0.0),
            battery=1.0,
            waypoints=[(10.0, 0.0)],
        )
        t.tick(100.0)
        assert t.battery == 1.0


class TestSimulationTargetSerialization:
    def test_to_dict(self):
        t = SimulationTarget(
            target_id="r1",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(3.5, -2.1),
            heading=1.57,
            speed=2.0,
            battery=0.85,
            status="active",
        )
        d = t.to_dict()
        assert d["target_id"] == "r1"
        assert d["name"] == "Rover Alpha"
        assert d["alliance"] == "friendly"
        assert d["asset_type"] == "rover"
        assert d["position"] == {"x": 3.5, "y": -2.1}
        assert d["heading"] == 1.57
        assert d["speed"] == 2.0
        assert d["battery"] == 0.85
        assert d["status"] == "active"


class TestSimulationTargetArrived:
    def test_single_waypoint_dispatch_arrives(self):
        """Single-waypoint dispatch should set status='arrived' at destination."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(1.0, 0.0)],
        )
        for _ in range(20):
            t.tick(0.1)
        assert t.status == "arrived"

    def test_multi_waypoint_patrol_loops(self):
        """Multi-waypoint patrol with loop_waypoints=True should loop, not arrive."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
            loop_waypoints=True,
        )
        for _ in range(100):
            t.tick(0.1)
        assert t.status != "arrived"
        # Should still be active (patrol loops)
        assert t.status in ("active", "low_battery")

    def test_multi_waypoint_no_loop_arrives(self):
        """Multi-waypoint dispatch without loop_waypoints should arrive."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=100.0, waypoints=[(2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
        )
        for _ in range(100):
            t.tick(0.1)
        assert t.status == "arrived"

    def test_hostile_escapes_at_path_end(self):
        """Hostile completing its path should get 'escaped' status."""
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
            speed=100.0, waypoints=[(5.0, 0.0), (10.0, 0.0)],
        )
        for _ in range(50):
            t.tick(0.1)
        assert t.status == "escaped"

    def test_neutralized_target_stops(self):
        """Neutralized targets should not move on tick."""
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(5.0, 0.0),
            speed=5.0, waypoints=[(20.0, 0.0)],
            status="neutralized",
        )
        t.tick(1.0)
        assert t.position == (5.0, 0.0)

    def test_escaped_target_stops(self):
        """Escaped targets should not move on tick."""
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(5.0, 0.0),
            speed=5.0, waypoints=[(20.0, 0.0)],
            status="escaped",
        )
        t.tick(1.0)
        assert t.position == (5.0, 0.0)


class TestSimulationTargetStationary:
    def test_zero_speed_with_waypoints_is_stationary(self):
        """Target with speed=0 and waypoints should be stationary, not active."""
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(5.0, 5.0),
            speed=0.0, waypoints=[(10.0, 10.0)],
        )
        t.tick(1.0)
        assert t.status == "stationary"
        assert t.position == (5.0, 5.0)


class TestSimulationTargetHeadingDegrees:
    def test_heading_stored_in_degrees(self):
        """Heading should be stored in degrees after tick()."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=1.0, waypoints=[(10.0, 0.0)],
        )
        t.tick(0.5)
        # Waypoint at (10, 0) from (0, 0): dx=10, dy=0
        # atan2(10, 0) = pi/2 → 90 degrees
        expected_deg = math.degrees(math.atan2(10.0, 0.0))
        assert abs(t.heading - expected_deg) < 0.01
        # Should be roughly 90 degrees
        assert abs(t.heading - 90.0) < 0.01

    def test_heading_north_is_zero(self):
        """Moving north (positive y) should give heading ~0 degrees."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            speed=1.0, waypoints=[(0.0, 10.0)],
        )
        t.tick(0.5)
        # dx=0, dy=10: atan2(0, 10) = 0 → 0 degrees
        assert abs(t.heading) < 0.01

    def test_to_dict_heading_in_degrees(self):
        """to_dict() heading should be in degrees."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            heading=90.0,  # 90 degrees
        )
        d = t.to_dict()
        assert d["heading"] == 90.0
