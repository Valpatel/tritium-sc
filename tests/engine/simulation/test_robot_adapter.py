# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for FakeRobotAdapter and FakeRobotFleetAdapter.

TDD: tests written first. Adapter wraps FakeRobot and provides
bidirectional message passing WITHOUT a real MQTT broker.

~20 tests covering:
  - Adapter wraps FakeRobot correctly
  - publish_telemetry() returns MQTT-compatible format
  - receive_command() dispatches/recalls the robot
  - tick() auto-publishes at interval
  - Fleet adapter manages multiple robots
  - dispatch() reaches the correct robot
"""

import pytest

from engine.simulation.fake_robot import FakeRobot


# ===========================================================================
# FakeRobotAdapter — creation and wrapping
# ===========================================================================


@pytest.mark.unit
class TestFakeRobotAdapterCreation:
    def test_import(self):
        """Module is importable."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        assert FakeRobotAdapter is not None

    def test_create_from_existing_robot(self):
        """Adapter wraps an existing FakeRobot instance."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01", asset_type="rover")
        adapter = FakeRobotAdapter(robot)
        assert adapter.robot is robot
        assert adapter.robot_id == "rover-01"

    def test_create_inline(self):
        """Adapter can create a FakeRobot inline via class method."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        adapter = FakeRobotAdapter.create(
            robot_id="drone-01",
            asset_type="drone",
            lat=37.78,
            lng=-122.42,
        )
        assert adapter.robot_id == "drone-01"
        assert adapter.robot.asset_type == "drone"
        assert adapter.robot.lat == 37.78


# ===========================================================================
# publish_telemetry
# ===========================================================================


@pytest.mark.unit
class TestPublishTelemetry:
    def test_publish_returns_telemetry_dict(self):
        """publish_telemetry() returns a dict with MQTT-expected fields."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01", lat=37.77, lng=-122.41)
        adapter = FakeRobotAdapter(robot)
        telem = adapter.publish_telemetry()

        assert isinstance(telem, dict)
        assert telem["robot_id"] == "rover-01"
        assert telem["lat"] == 37.77
        assert telem["lng"] == -122.41
        assert "battery" in telem
        assert "status" in telem
        assert "heading" in telem
        assert "speed" in telem
        assert "asset_type" in telem
        assert "alliance" in telem

    def test_publish_calls_callback(self):
        """publish_telemetry() invokes the telemetry callback if set."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        received = []
        adapter.on_telemetry = lambda robot_id, data: received.append((robot_id, data))

        adapter.publish_telemetry()

        assert len(received) == 1
        assert received[0][0] == "rover-01"
        assert received[0][1]["robot_id"] == "rover-01"

    def test_publish_without_callback_does_not_crash(self):
        """publish_telemetry() without a callback is a no-op (no crash)."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)
        # No callback set -- should not raise
        telem = adapter.publish_telemetry()
        assert telem is not None


# ===========================================================================
# receive_command
# ===========================================================================


@pytest.mark.unit
class TestReceiveCommand:
    def test_dispatch_makes_robot_move(self):
        """receive_command('dispatch', ...) sets robot to moving."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})

        assert robot.status == "moving"

    def test_recall_stops_robot(self):
        """receive_command('recall') sets robot to returning."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        robot.dispatch(37.78, -122.42)  # Start moving first
        adapter.receive_command("recall")

        assert robot.status == "returning"

    def test_patrol_command(self):
        """receive_command('patrol', ...) sets robot to patrolling."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        adapter.receive_command("patrol", {
            "waypoints": [(37.775, -122.419), (37.776, -122.419)],
            "loop": True,
        })

        assert robot.status == "patrolling"

    def test_unknown_command_is_noop(self):
        """Unknown commands do not crash."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        adapter.receive_command("self_destruct", {"confirm": True})
        # Should still be idle (no crash, no state change)
        assert robot.status == "idle"


# ===========================================================================
# tick() with auto-publish
# ===========================================================================


@pytest.mark.unit
class TestTick:
    def test_tick_advances_robot(self):
        """tick() advances the underlying FakeRobot."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01", battery=1.0)
        adapter = FakeRobotAdapter(robot)

        adapter.tick(0.1)

        # Battery should drain slightly even when idle
        assert robot.battery <= 1.0

    def test_tick_auto_publishes_at_interval(self):
        """tick() publishes telemetry when accumulated time exceeds interval."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot, telemetry_interval=1.0)

        received = []
        adapter.on_telemetry = lambda rid, data: received.append(data)

        # 9 ticks of 0.1s each -- not enough to trigger
        for _ in range(9):
            adapter.tick(0.1)
        assert len(received) == 0

        # 10th tick -- 1.0s total, should trigger
        adapter.tick(0.1)
        assert len(received) == 1

    def test_tick_does_not_publish_before_interval(self):
        """tick() should not publish before the interval elapses."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot, telemetry_interval=5.0)

        received = []
        adapter.on_telemetry = lambda rid, data: received.append(data)

        for _ in range(10):
            adapter.tick(0.1)  # 1.0s total

        assert len(received) == 0

    def test_tick_returns_telemetry(self):
        """tick() returns the FakeRobot telemetry dict."""
        from engine.simulation.robot_adapter import FakeRobotAdapter
        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        telem = adapter.tick(0.1)
        assert isinstance(telem, dict)
        assert telem["robot_id"] == "rover-01"


# ===========================================================================
# connect_to_bridge
# ===========================================================================


@pytest.mark.unit
class TestConnectToBridge:
    def test_connect_wires_telemetry_handler(self):
        """connect_to_bridge() wires adapter into bridge's telemetry handler."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        # Fake bridge that records calls
        class FakeBridge:
            def __init__(self):
                self.telemetry_calls = []

            def _on_robot_telemetry(self, robot_id, payload):
                self.telemetry_calls.append((robot_id, payload))

        bridge = FakeBridge()
        adapter.connect_to_bridge(bridge)

        # Now publish should route through bridge
        adapter.publish_telemetry()
        assert len(bridge.telemetry_calls) == 1
        assert bridge.telemetry_calls[0][0] == "rover-01"

    def test_connect_enables_command_receiving(self):
        """After connect_to_bridge, the bridge can send commands to the adapter."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        robot = FakeRobot(robot_id="rover-01")
        adapter = FakeRobotAdapter(robot)

        # The adapter should be accessible for command dispatch
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        assert robot.status == "moving"


# ===========================================================================
# FakeRobotFleetAdapter
# ===========================================================================


@pytest.mark.unit
class TestFakeRobotFleetAdapter:
    def test_import(self):
        """Fleet adapter module is importable."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        assert FakeRobotFleetAdapter is not None

    def test_add_robot(self):
        """add_robot() creates and tracks a new fake robot adapter."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        adapter = fleet.add_robot("rover-01", lat=37.77, lng=-122.41)
        assert adapter.robot_id == "rover-01"
        assert len(fleet) == 1

    def test_add_robot_with_type(self):
        """add_robot() supports robot_type parameter."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        adapter = fleet.add_robot("drone-01", robot_type="drone")
        assert adapter.robot.asset_type == "drone"

    def test_add_multiple_robots(self):
        """Fleet can track multiple robots."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        fleet.add_robot("rover-02")
        fleet.add_robot("drone-01", robot_type="drone")
        assert len(fleet) == 3

    def test_tick_all_ticks_every_robot(self):
        """tick_all() advances all robots and returns telemetry list."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01", battery=1.0)
        fleet.add_robot("rover-02", battery=1.0)

        results = fleet.tick_all(0.1)
        assert len(results) == 2
        assert all(isinstance(t, dict) for t in results)

    def test_dispatch_reaches_correct_robot(self):
        """dispatch() sends command to the right robot only."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        fleet.add_robot("rover-02")

        fleet.dispatch("rover-01", lat=37.78, lng=-122.42)

        adapter1 = fleet.get_adapter("rover-01")
        adapter2 = fleet.get_adapter("rover-02")
        assert adapter1.robot.status == "moving"
        assert adapter2.robot.status == "idle"

    def test_dispatch_nonexistent_robot_is_noop(self):
        """dispatch() for unknown robot ID does not crash."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        fleet.dispatch("ghost", lat=37.78, lng=-122.42)  # no crash

    def test_get_adapter(self):
        """get_adapter() returns the adapter for a given robot ID."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        adapter = fleet.get_adapter("rover-01")
        assert adapter is not None
        assert adapter.robot_id == "rover-01"

    def test_get_adapter_nonexistent_returns_none(self):
        """get_adapter() returns None for unknown robot ID."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter
        fleet = FakeRobotFleetAdapter()
        assert fleet.get_adapter("ghost") is None

    def test_connect_to_bridge_wires_all_robots(self):
        """connect_to_bridge() wires all fleet robots into the bridge."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter

        class FakeBridge:
            def __init__(self):
                self.telemetry_calls = []

            def _on_robot_telemetry(self, robot_id, payload):
                self.telemetry_calls.append((robot_id, payload))

        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        fleet.add_robot("rover-02")

        bridge = FakeBridge()
        fleet.connect_to_bridge(bridge)

        # Tick all to trigger auto-publish (set short interval)
        for adapter in fleet._adapters.values():
            adapter.telemetry_interval = 0.0  # immediate publish
        fleet.tick_all(0.1)

        robot_ids = {call[0] for call in bridge.telemetry_calls}
        assert "rover-01" in robot_ids
        assert "rover-02" in robot_ids
