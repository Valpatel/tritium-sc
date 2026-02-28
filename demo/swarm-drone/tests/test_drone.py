# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for drone.py -- SwarmDrone state machine, movement, battery, elimination."""

import math
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from drone import SwarmDrone


# ---------------------------------------------------------------------------
# Creation / defaults
# ---------------------------------------------------------------------------
class TestCreation:
    """SwarmDrone initializes with correct defaults."""

    def test_drone_id(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.drone_id == "swarm-01"

    def test_default_state_hovering(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.state == "hovering"

    def test_start_position(self):
        d = SwarmDrone(drone_id="swarm-01", start_x=10.0, start_y=20.0)
        assert d.x == pytest.approx(10.0)
        assert d.y == pytest.approx(20.0)

    def test_default_position_origin(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.x == pytest.approx(0.0)
        assert d.y == pytest.approx(0.0)

    def test_default_heading(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.heading == pytest.approx(0.0)

    def test_battery_starts_full(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.battery_pct == pytest.approx(1.0)

    def test_status_active(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.status == "active"

    def test_alliance_friendly(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.alliance == "friendly"

    def test_name_default(self):
        d = SwarmDrone(drone_id="swarm-01")
        assert d.name == "Drone swarm-01"

    def test_name_custom(self):
        d = SwarmDrone(drone_id="swarm-01", name="Alpha")
        assert d.name == "Alpha"


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
class TestStates:
    """SwarmDrone has valid states: hovering, flying, patrolling, returning, eliminated."""

    def test_valid_states_exist(self):
        assert "hovering" in SwarmDrone.STATES
        assert "flying" in SwarmDrone.STATES
        assert "patrolling" in SwarmDrone.STATES
        assert "returning" in SwarmDrone.STATES
        assert "eliminated" in SwarmDrone.STATES


# ---------------------------------------------------------------------------
# Dispatch (fly to waypoint)
# ---------------------------------------------------------------------------
class TestDispatch:
    """dispatch(x, y) sends the drone to a point."""

    def test_dispatch_changes_state_to_flying(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(50.0, 50.0)
        assert d.state == "flying"

    def test_dispatch_sets_target(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(50.0, 60.0)
        assert d.target_x == pytest.approx(50.0)
        assert d.target_y == pytest.approx(60.0)

    def test_dispatch_moves_toward_target(self):
        d = SwarmDrone(drone_id="swarm-01", start_x=0.0, start_y=0.0)
        d.dispatch(100.0, 0.0)
        for _ in range(50):
            d.tick(0.1)
        assert d.x > 0.0

    def test_dispatch_arrives_and_hovers(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(2.0, 0.0)
        for _ in range(200):
            d.tick(0.1)
        assert d.state == "hovering"

    def test_heading_updates_toward_target(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(10.0, 10.0)
        d.tick(0.1)
        # Heading should be toward NE (roughly 45 degrees)
        assert d.heading != pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# Patrol
# ---------------------------------------------------------------------------
class TestPatrol:
    """patrol(waypoints) loops through waypoints."""

    def test_patrol_changes_state(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([{"x": 10, "y": 0}, {"x": 20, "y": 0}])
        assert d.state == "patrolling"

    def test_patrol_stores_waypoints(self):
        d = SwarmDrone(drone_id="swarm-01")
        wps = [{"x": 10, "y": 0}, {"x": 20, "y": 0}]
        d.patrol(wps)
        assert len(d.patrol_waypoints) == 2

    def test_patrol_moves_toward_first_waypoint(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([{"x": 10, "y": 0}])
        for _ in range(50):
            d.tick(0.1)
        assert d.x > 0.0

    def test_empty_patrol_stays_hovering(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([])
        assert d.state == "hovering"

    def test_patrol_loops(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([{"x": 2, "y": 0}, {"x": 2, "y": 2}])
        for _ in range(500):
            d.tick(0.1)
        assert d.state == "patrolling"


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------
class TestRecall:
    """recall() returns drone to start position."""

    def test_recall_changes_state(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(10.0, 0.0)
        for _ in range(10):
            d.tick(0.1)
        d.recall()
        assert d.state == "returning"

    def test_recall_goes_to_start(self):
        d = SwarmDrone(drone_id="swarm-01", start_x=5.0, start_y=5.0)
        d.dispatch(20.0, 20.0)
        for _ in range(50):
            d.tick(0.1)
        d.recall()
        for _ in range(500):
            d.tick(0.1)
        dist = math.sqrt((d.x - 5.0) ** 2 + (d.y - 5.0) ** 2)
        assert dist < 2.0

    def test_recall_goes_idle_on_arrival(self):
        d = SwarmDrone(drone_id="swarm-01", start_x=0.0, start_y=0.0)
        d.dispatch(3.0, 0.0)
        for _ in range(20):
            d.tick(0.1)
        d.recall()
        for _ in range(500):
            d.tick(0.1)
        assert d.state == "hovering"


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------
class TestStop:
    """stop() halts movement and returns to hovering."""

    def test_stop_from_flying(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(100.0, 0.0)
        d.stop()
        assert d.state == "hovering"

    def test_stop_from_patrolling(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([{"x": 10, "y": 0}])
        d.stop()
        assert d.state == "hovering"

    def test_stop_clears_patrol(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.patrol([{"x": 10, "y": 0}])
        d.stop()
        assert d.patrol_waypoints == []


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------
class TestBattery:
    """Battery drains at 2% per minute."""

    def test_battery_drains_over_time(self):
        d = SwarmDrone(drone_id="swarm-01")
        # 60 seconds of ticking
        for _ in range(600):
            d.tick(0.1)
        # Should drain approximately 2%
        assert d.battery_pct < 1.0
        assert d.battery_pct == pytest.approx(0.98, abs=0.005)

    def test_battery_voltage_correlates(self):
        d = SwarmDrone(drone_id="swarm-01")
        v_full = d.battery_voltage
        for _ in range(6000):
            d.tick(0.1)
        v_later = d.battery_voltage
        assert v_later < v_full

    def test_battery_never_negative(self):
        d = SwarmDrone(drone_id="swarm-01")
        # Drain heavily
        for _ in range(100000):
            d.tick(0.1)
        assert d.battery_pct >= 0.0


# ---------------------------------------------------------------------------
# Elimination
# ---------------------------------------------------------------------------
class TestElimination:
    """When eliminated, drone stops responding to commands."""

    def test_eliminate_changes_state(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        assert d.state == "eliminated"

    def test_eliminate_changes_status(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        assert d.status == "eliminated"

    def test_eliminate_ignores_dispatch(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        d.dispatch(100.0, 100.0)
        assert d.state == "eliminated"

    def test_eliminate_ignores_patrol(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        d.patrol([{"x": 10, "y": 0}])
        assert d.state == "eliminated"

    def test_eliminate_ignores_recall(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        d.recall()
        assert d.state == "eliminated"

    def test_eliminate_ignores_stop(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        d.stop()
        assert d.state == "eliminated"

    def test_eliminated_drone_no_movement(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.dispatch(100.0, 0.0)
        d.tick(0.1)
        x_before = d.x
        d.eliminate()
        for _ in range(100):
            d.tick(0.1)
        assert d.x == pytest.approx(x_before)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
class TestTelemetry:
    """tick() returns correct telemetry dict."""

    def test_tick_returns_dict(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        assert isinstance(tel, dict)

    def test_telemetry_required_fields(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        required = [
            "robot_id", "name", "asset_type", "position", "heading",
            "battery", "status", "fsm_state", "alliance", "timestamp",
        ]
        for field in required:
            assert field in tel, f"Missing field: {field}"

    def test_telemetry_robot_id(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        assert tel["robot_id"] == "swarm-01"

    def test_telemetry_asset_type_drone(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        assert tel["asset_type"] == "drone"

    def test_telemetry_position_format(self):
        d = SwarmDrone(drone_id="swarm-01", start_x=10.0, start_y=20.0)
        tel = d.tick(0.1)
        assert tel["position"]["x"] == pytest.approx(10.0)
        assert tel["position"]["y"] == pytest.approx(20.0)

    def test_telemetry_battery_format(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        bat = tel["battery"]
        assert "voltage" in bat
        assert "percentage" in bat

    def test_telemetry_fsm_state_matches_state(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        assert tel["fsm_state"] == "hovering"

    def test_telemetry_alliance(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        assert tel["alliance"] == "friendly"

    def test_telemetry_timestamp_iso8601(self):
        d = SwarmDrone(drone_id="swarm-01")
        tel = d.tick(0.1)
        ts = tel["timestamp"]
        assert ts.endswith("Z") or "+00:00" in ts
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_telemetry_status_eliminated(self):
        d = SwarmDrone(drone_id="swarm-01")
        d.eliminate()
        tel = d.tick(0.1)
        assert tel["status"] == "eliminated"
        assert tel["fsm_state"] == "eliminated"
