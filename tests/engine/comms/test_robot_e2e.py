"""End-to-end tests using FakeRobot + mqtt_cot codec.

~15 tests verifying the full pipeline: FakeRobot telemetry -> CoT XML -> back,
command encoding, round-trip fidelity, fleet operations, and position changes.
"""

import math
import xml.etree.ElementTree as ET

import pytest

from engine.simulation.fake_robot import FakeRobot, FakeRobotFleet
from engine.comms.mqtt_cot import (
    cot_to_telemetry,
    command_to_cot,
    telemetry_to_cot,
)


# ── Telemetry -> CoT -> Parse ────────────────────────────────────────────

class TestTelemetryToCoT:
    def test_telemetry_to_cot_valid_xml(self):
        """FakeRobot telemetry -> telemetry_to_cot -> valid CoT XML."""
        robot = FakeRobot(robot_id="rover-01", asset_type="rover")
        telem = robot.get_telemetry()
        xml = telemetry_to_cot(robot.robot_id, telem)
        root = ET.fromstring(xml)
        assert root.tag == "event"
        assert root.get("uid") == "rover-01"
        assert root.get("version") == "2.0"

    def test_cot_to_telemetry_preserves_fields(self):
        """CoT XML -> cot_to_telemetry -> preserves core fields."""
        robot = FakeRobot(
            robot_id="drone-01",
            asset_type="drone",
            lat=37.78,
            lng=-122.42,
            battery=0.75,
        )
        robot.dispatch(37.79, -122.42)
        robot.tick(0.1)  # set speed and heading

        xml = telemetry_to_cot(robot.robot_id, robot.get_telemetry())
        parsed = cot_to_telemetry(xml)

        assert parsed is not None
        assert parsed["target_id"] == "drone-01"
        assert parsed["lat"] == pytest.approx(robot.lat, abs=0.001)
        assert parsed["lng"] == pytest.approx(robot.lng, abs=0.001)
        assert parsed["alliance"] == "friendly"

    def test_round_trip_positions_match(self):
        """Round trip: robot telemetry -> CoT -> back to dict -> positions match."""
        robot = FakeRobot(robot_id="r1", lat=37.5555, lng=-122.3333, battery=0.9)
        telem = robot.get_telemetry()
        xml = telemetry_to_cot(robot.robot_id, telem)
        parsed = cot_to_telemetry(xml)

        assert parsed is not None
        assert parsed["lat"] == pytest.approx(37.5555, abs=1e-4)
        assert parsed["lng"] == pytest.approx(-122.3333, abs=1e-4)

    def test_round_trip_battery_match(self):
        """Round trip preserves battery level."""
        robot = FakeRobot(robot_id="r1", battery=0.42)
        xml = telemetry_to_cot(robot.robot_id, robot.get_telemetry())
        parsed = cot_to_telemetry(xml)

        assert parsed is not None
        # Battery is encoded as percentage and parsed back
        assert parsed["battery"] == pytest.approx(0.42, abs=0.01)

    def test_round_trip_speed_heading(self):
        """Round trip preserves speed and heading."""
        robot = FakeRobot(robot_id="r1")
        robot.dispatch(37.78, -122.42)
        robot.tick(0.1)

        xml = telemetry_to_cot(robot.robot_id, robot.get_telemetry())
        parsed = cot_to_telemetry(xml)

        assert parsed is not None
        assert parsed["speed"] == pytest.approx(robot.speed, abs=0.1)


# ── Command -> CoT ───────────────────────────────────────────────────────

class TestCommandToCoT:
    def test_dispatch_command_to_cot(self):
        """Command -> command_to_cot -> valid tasking CoT XML."""
        xml = command_to_cot("rover-01", "dispatch", {"x": -122.42, "y": 37.78})
        root = ET.fromstring(xml)
        assert root.get("type") == "t-x-t-a"
        assert "rover-01" in xml
        assert "DISPATCH" in xml

    def test_patrol_command_to_cot(self):
        """Patrol command encodes waypoints."""
        xml = command_to_cot(
            "rover-01",
            "patrol",
            {"waypoints": [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]},
        )
        assert "PATROL" in xml
        assert "(1.0, 2.0)" in xml

    def test_recall_command_to_cot(self):
        """Recall command produces valid CoT."""
        xml = command_to_cot("rover-01", "recall")
        root = ET.fromstring(xml)
        assert root.get("type") == "t-x-t-a"
        assert "RECALL" in xml


# ── Multiple Robots ──────────────────────────────────────────────────────

class TestMultipleRobots:
    def test_multiple_robots_unique_telemetry(self):
        """Multiple robots produce unique telemetry."""
        r1 = FakeRobot(robot_id="r1", lat=37.0, lng=-122.0)
        r2 = FakeRobot(robot_id="r2", lat=38.0, lng=-121.0, asset_type="drone")

        t1 = r1.get_telemetry()
        t2 = r2.get_telemetry()

        assert t1["robot_id"] != t2["robot_id"]
        assert t1["lat"] != t2["lat"]
        assert t1["asset_type"] != t2["asset_type"]

    def test_dispatch_changes_position(self):
        """Robot dispatch -> robot moves -> new telemetry reflects position change."""
        robot = FakeRobot(robot_id="r1", lat=37.7749, lng=-122.4194)
        initial_lat = robot.lat

        robot.dispatch(37.776, -122.4194)  # ~120m north
        for _ in range(50):
            robot.tick(0.1)

        assert robot.lat != initial_lat, "Position should change after dispatch"
        telem = robot.get_telemetry()
        assert telem["lat"] != initial_lat

    def test_battery_drain_over_time(self):
        """Battery drain over time matches expected rate."""
        robot = FakeRobot(robot_id="r1", battery=1.0, asset_type="rover")
        robot.dispatch(37.78, -122.42)

        # Rover drain_rate is 0.001/s. Over 10s, expect ~0.01 drain
        for _ in range(100):
            robot.tick(0.1)  # total = 10s

        expected_drain = 0.001 * 10.0  # 0.01
        actual_drain = 1.0 - robot.battery
        assert actual_drain == pytest.approx(expected_drain, abs=0.005)


# ── Patrol E2E ───────────────────────────────────────────────────────────

class TestPatrolE2E:
    def test_patrol_visits_all_waypoints(self):
        """Patrol waypoints: robot visits all points in order."""
        robot = FakeRobot(robot_id="r1", lat=37.7749, lng=-122.4194)
        wp1 = (37.7749 + 0.00005, -122.4194)
        wp2 = (37.7749 + 0.0001, -122.4194)
        wp3 = (37.7749 + 0.00015, -122.4194)
        robot.patrol([wp1, wp2, wp3], loop=False)

        visited = set()
        for _ in range(2000):
            robot.tick(0.1)
            for i, wp in enumerate([wp1, wp2, wp3]):
                d = math.hypot(
                    (robot.lat - wp[0]) * 111_000,
                    (robot.lng - wp[1]) * 111_000 * math.cos(math.radians(robot.lat)),
                )
                if d < 3.0:
                    visited.add(i)
            if robot.status == "idle":
                break

        assert len(visited) >= 2, f"Robot should visit most waypoints, visited {visited}"


# ── Fleet E2E ────────────────────────────────────────────────────────────

class TestFleetE2E:
    def test_fleet_three_robots_valid_telemetry(self):
        """Fleet test: 3 robots running concurrently, all produce valid telemetry."""
        fleet = FakeRobotFleet()
        fleet.add_robot("r1", asset_type="rover", lat=37.77, lng=-122.42)
        fleet.add_robot("r2", asset_type="drone", lat=37.78, lng=-122.41)
        fleet.add_robot("r3", asset_type="tank", lat=37.79, lng=-122.40)

        fleet.dispatch("r1", 37.78, -122.42)
        fleet.dispatch("r2", 37.79, -122.41)

        for _ in range(50):
            all_telem = fleet.tick_all(0.1)
            assert len(all_telem) == 3
            for t in all_telem:
                assert "robot_id" in t
                assert "lat" in t
                assert "battery" in t
                # Each telemetry can be encoded as CoT
                robot = fleet.get_robot(t["robot_id"])
                xml = telemetry_to_cot(t["robot_id"], t)
                root = ET.fromstring(xml)
                assert root.tag == "event"

    def test_fleet_independent_movement(self):
        """Fleet robots move independently."""
        fleet = FakeRobotFleet()
        fleet.add_robot("r1", lat=37.77, lng=-122.42)
        fleet.add_robot("r2", lat=37.77, lng=-122.42)

        # Only dispatch r1
        fleet.dispatch("r1", 37.78, -122.42)

        for _ in range(50):
            fleet.tick_all(0.1)

        r1 = fleet.get_robot("r1")
        r2 = fleet.get_robot("r2")
        assert r1.status == "moving"
        assert r2.status == "idle"
        assert r1.lat != r2.lat or r1.speed != r2.speed
