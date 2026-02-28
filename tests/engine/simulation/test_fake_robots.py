# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for FakeRobot and FakeRobotFleet.

~25 tests covering robot creation, movement, battery drain, motor temps,
patrol waypoints, recall, CoT telemetry generation, and fleet management.
"""

import math
import xml.etree.ElementTree as ET

import pytest

from engine.simulation.fake_robot import FakeRobot, FakeRobotFleet


# ── Helpers ──────────────────────────────────────────────────────────────

def _approx_distance_m(lat1, lng1, lat2, lng2):
    """Approximate distance in meters between two lat/lng points."""
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlng) * R


# ── Creation ─────────────────────────────────────────────────────────────

class TestFakeRobotCreation:
    def test_default_creation(self):
        robot = FakeRobot(robot_id="test-01")
        assert robot.robot_id == "test-01"
        assert robot.asset_type == "rover"
        assert robot.alliance == "friendly"
        assert robot.battery == 1.0
        assert robot.status == "idle"
        assert robot.speed == 0.0

    def test_custom_creation(self):
        robot = FakeRobot(
            robot_id="drone-01",
            asset_type="drone",
            lat=38.0,
            lng=-121.0,
            battery=0.8,
        )
        assert robot.asset_type == "drone"
        assert robot.lat == 38.0
        assert robot.lng == -121.0
        assert robot.battery == 0.8

    def test_default_motor_temps(self):
        robot = FakeRobot(robot_id="test-01")
        assert len(robot.motor_temps) == 4
        assert all(t == 25.0 for t in robot.motor_temps)

    def test_start_position_saved(self):
        robot = FakeRobot(robot_id="test-01", lat=37.0, lng=-122.0)
        assert robot._start_lat == 37.0
        assert robot._start_lng == -122.0


# ── Telemetry ────────────────────────────────────────────────────────────

class TestFakeRobotTelemetry:
    def test_tick_returns_telemetry_dict(self):
        robot = FakeRobot(robot_id="test-01")
        telem = robot.tick(0.1)
        assert isinstance(telem, dict)
        assert "robot_id" in telem
        assert "lat" in telem
        assert "lng" in telem
        assert "battery" in telem
        assert "motor_temps" in telem
        assert "speed" in telem
        assert "heading" in telem
        assert "status" in telem
        assert "asset_type" in telem
        assert "alliance" in telem
        assert "alt" in telem

    def test_telemetry_fields_match_state(self):
        robot = FakeRobot(robot_id="r1", lat=37.5, lng=-122.1)
        telem = robot.get_telemetry()
        assert telem["robot_id"] == "r1"
        assert telem["lat"] == 37.5
        assert telem["lng"] == -122.1
        assert telem["status"] == "idle"

    def test_telemetry_logged(self):
        robot = FakeRobot(robot_id="test-01")
        assert len(robot._telemetry_log) == 0
        robot.tick(0.1)
        assert len(robot._telemetry_log) == 1
        robot.tick(0.1)
        assert len(robot._telemetry_log) == 2


# ── Dispatch and Movement ────────────────────────────────────────────────

class TestFakeRobotMovement:
    def test_dispatch_sets_status_moving(self):
        robot = FakeRobot(robot_id="test-01")
        robot.dispatch(37.78, -122.42)
        assert robot.status == "moving"

    def test_dispatch_logged(self):
        robot = FakeRobot(robot_id="test-01")
        robot.dispatch(37.78, -122.42)
        assert len(robot._command_log) == 1
        assert robot._command_log[0]["command"] == "dispatch"

    def test_robot_moves_toward_target(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        target_lat, target_lng = 37.7760, -122.4194  # ~120m north
        robot.dispatch(target_lat, target_lng)

        initial_dist = _approx_distance_m(
            robot.lat, robot.lng, target_lat, target_lng
        )

        # Run many ticks
        for _ in range(100):
            robot.tick(0.1)

        final_dist = _approx_distance_m(
            robot.lat, robot.lng, target_lat, target_lng
        )
        assert final_dist < initial_dist, "Robot should move closer to target"

    def test_robot_reaches_destination(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        # Very close target (~10m north)
        target_lat = 37.7749 + 0.0001
        robot.dispatch(target_lat, -122.4194)

        # Tick until idle or max iterations
        for _ in range(500):
            robot.tick(0.1)
            if robot.status == "idle":
                break

        assert robot.status == "idle", "Robot should arrive and become idle"

    def test_heading_updates_during_movement(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        # Target due east
        robot.dispatch(37.7749, -122.4180)
        robot.tick(0.1)
        # Heading should be approximately east (~90 degrees)
        assert 45 < robot.heading < 135, f"Heading should be ~90, got {robot.heading}"

    def test_speed_nonzero_during_movement(self):
        robot = FakeRobot(robot_id="test-01")
        robot.dispatch(37.78, -122.42)
        robot.tick(0.1)
        assert robot.speed > 0


# ── Battery ──────────────────────────────────────────────────────────────

class TestFakeRobotBattery:
    def test_battery_drains_during_movement(self):
        robot = FakeRobot(robot_id="test-01", battery=1.0)
        robot.dispatch(37.78, -122.42)

        initial_batt = robot.battery
        for _ in range(100):
            robot.tick(0.1)

        assert robot.battery < initial_batt, "Battery should drain during movement"

    def test_battery_drain_slower_when_idle(self):
        moving = FakeRobot(robot_id="mover", battery=1.0)
        idle = FakeRobot(robot_id="idler", battery=1.0)
        moving.dispatch(37.78, -122.42)

        for _ in range(100):
            moving.tick(0.1)
            idle.tick(0.1)

        assert idle.battery > moving.battery, "Idle drain should be less than movement drain"

    def test_battery_does_not_go_negative(self):
        robot = FakeRobot(robot_id="test-01", battery=0.001)
        robot.dispatch(37.78, -122.42)
        for _ in range(100):
            robot.tick(1.0)
        assert robot.battery >= 0.0


# ── Motor Temps ──────────────────────────────────────────────────────────

class TestFakeRobotMotorTemps:
    def test_motor_temps_increase_during_movement(self):
        robot = FakeRobot(robot_id="test-01")
        robot.dispatch(37.78, -122.42)

        initial_temps = list(robot.motor_temps)
        for _ in range(20):
            robot.tick(1.0)

        for i in range(4):
            assert robot.motor_temps[i] > initial_temps[i], \
                f"Motor {i} should heat up during movement"

    def test_motor_temps_cool_when_idle(self):
        robot = FakeRobot(robot_id="test-01")
        # Start hot
        robot.motor_temps = [50.0, 50.0, 50.0, 50.0]
        for _ in range(20):
            robot.tick(1.0)

        for t in robot.motor_temps:
            assert t < 50.0, "Motors should cool when idle"

    def test_motor_temps_capped_at_85(self):
        robot = FakeRobot(robot_id="test-01")
        robot.motor_temps = [84.0, 84.0, 84.0, 84.0]
        robot.dispatch(37.78, -122.42)
        for _ in range(100):
            robot.tick(1.0)

        for t in robot.motor_temps:
            assert t <= 85.0, f"Motor temp {t} should be capped at 85"

    def test_motor_temps_floor_at_25(self):
        robot = FakeRobot(robot_id="test-01")
        robot.motor_temps = [26.0, 26.0, 26.0, 26.0]
        for _ in range(100):
            robot.tick(1.0)

        for t in robot.motor_temps:
            assert t >= 25.0, f"Motor temp {t} should not go below 25"


# ── Patrol ───────────────────────────────────────────────────────────────

class TestFakeRobotPatrol:
    def test_patrol_sets_status(self):
        robot = FakeRobot(robot_id="test-01")
        wp = [(37.775, -122.419), (37.776, -122.419)]
        robot.patrol(wp)
        assert robot.status == "patrolling"

    def test_patrol_follows_waypoints(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        wp1 = (37.7749 + 0.00005, -122.4194)  # ~5m north
        wp2 = (37.7749 + 0.0001, -122.4194)    # ~11m north
        robot.patrol([wp1, wp2], loop=False)

        visited_wp1 = False
        for _ in range(500):
            robot.tick(0.1)
            d1 = _approx_distance_m(robot.lat, robot.lng, wp1[0], wp1[1])
            if d1 < 2.0:
                visited_wp1 = True
            if robot.status == "idle":
                break

        assert visited_wp1, "Robot should visit first waypoint"
        assert robot.status == "idle", "Robot should be idle after non-looping patrol"

    def test_patrol_loop_repeats(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        wp1 = (37.7749 + 0.00005, -122.4194)
        wp2 = (37.7749 + 0.0001, -122.4194)
        robot.patrol([wp1, wp2], loop=True)

        # Run enough ticks to traverse all waypoints and loop
        for _ in range(1000):
            robot.tick(0.1)

        # Should still be patrolling (not idle) if looping
        assert robot.status == "patrolling"

    def test_patrol_command_logged(self):
        robot = FakeRobot(robot_id="test-01")
        robot.patrol([(37.775, -122.419)])
        assert len(robot._command_log) == 1
        assert robot._command_log[0]["command"] == "patrol"


# ── Recall ───────────────────────────────────────────────────────────────

class TestFakeRobotRecall:
    def test_recall_sets_status_returning(self):
        robot = FakeRobot(robot_id="test-01", lat=37.7749, lng=-122.4194)
        robot.dispatch(37.78, -122.42)  # move away
        robot.recall()
        assert robot.status == "returning"

    def test_recall_returns_to_start(self):
        start_lat, start_lng = 37.7749, -122.4194
        robot = FakeRobot(robot_id="test-01", lat=start_lat, lng=start_lng)

        # Move slightly away manually
        robot.lat += 0.0001
        robot.lng += 0.0001
        robot.recall()

        for _ in range(500):
            robot.tick(0.1)
            if robot.status == "idle":
                break

        dist = _approx_distance_m(robot.lat, robot.lng, start_lat, start_lng)
        assert dist < 2.0, f"Robot should return to start, distance is {dist}m"

    def test_recall_command_logged(self):
        robot = FakeRobot(robot_id="test-01")
        robot.recall()
        assert len(robot._command_log) == 1
        assert robot._command_log[0]["command"] == "recall"


# ── receive_command ──────────────────────────────────────────────────────

class TestFakeRobotReceiveCommand:
    def test_receive_dispatch(self):
        robot = FakeRobot(robot_id="test-01")
        robot.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        assert robot.status == "moving"

    def test_receive_patrol(self):
        robot = FakeRobot(robot_id="test-01")
        robot.receive_command("patrol", {
            "waypoints": [(37.775, -122.419)],
            "loop": False,
        })
        assert robot.status == "patrolling"

    def test_receive_recall(self):
        robot = FakeRobot(robot_id="test-01")
        robot.receive_command("recall")
        assert robot.status == "returning"


# ── CoT Telemetry ────────────────────────────────────────────────────────

class TestFakeRobotCoT:
    def test_get_cot_telemetry_returns_xml(self):
        robot = FakeRobot(robot_id="rover-01", asset_type="rover")
        xml = robot.get_cot_telemetry()
        assert xml.startswith("<event")
        assert "rover-01" in xml

    def test_get_cot_telemetry_parseable(self):
        robot = FakeRobot(robot_id="rover-01")
        xml = robot.get_cot_telemetry()
        root = ET.fromstring(xml)
        assert root.tag == "event"
        assert root.get("uid") == "rover-01"

    def test_cot_contains_position(self):
        robot = FakeRobot(robot_id="r1", lat=37.5, lng=-122.1)
        xml = robot.get_cot_telemetry()
        root = ET.fromstring(xml)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.5)
        assert float(point.get("lon")) == pytest.approx(-122.1)


# ── FakeRobotFleet ───────────────────────────────────────────────────────

class TestFakeRobotFleet:
    def test_add_robot(self):
        fleet = FakeRobotFleet()
        robot = fleet.add_robot("r1")
        assert robot.robot_id == "r1"
        assert len(fleet) == 1

    def test_add_multiple_robots(self):
        fleet = FakeRobotFleet()
        fleet.add_robot("r1")
        fleet.add_robot("r2", asset_type="drone")
        assert len(fleet) == 2

    def test_get_robot(self):
        fleet = FakeRobotFleet()
        fleet.add_robot("r1")
        assert fleet.get_robot("r1") is not None
        assert fleet.get_robot("nonexistent") is None

    def test_tick_all_returns_telemetry_list(self):
        fleet = FakeRobotFleet()
        fleet.add_robot("r1")
        fleet.add_robot("r2")
        results = fleet.tick_all(0.1)
        assert len(results) == 2
        assert all(isinstance(t, dict) for t in results)

    def test_fleet_dispatch(self):
        fleet = FakeRobotFleet()
        fleet.add_robot("r1")
        fleet.dispatch("r1", 37.78, -122.42)
        assert fleet.get_robot("r1").status == "moving"

    def test_fleet_dispatch_nonexistent_robot(self):
        fleet = FakeRobotFleet()
        # Should not raise
        fleet.dispatch("ghost", 37.78, -122.42)

    def test_fleet_robots_property(self):
        fleet = FakeRobotFleet()
        fleet.add_robot("r1")
        fleet.add_robot("r2")
        robots = fleet.robots
        assert "r1" in robots
        assert "r2" in robots
        # Should be a copy
        robots["r3"] = None
        assert len(fleet) == 2
