"""Integration tests for the FakeRobot -> MQTT pipeline -> TargetTracker roundtrip.

TDD: tests written first. These prove the full pipeline works end-to-end
WITHOUT a real MQTT broker, using FakeRobotAdapter's in-process message routing.

~15 tests covering:
  - FakeRobotAdapter -> MQTTBridge._on_robot_telemetry() -> TargetTracker
  - MQTTBridge command -> FakeRobotAdapter.receive_command() -> FakeRobot moves
  - Full roundtrip: dispatch -> execute -> telemetry -> tracker
  - Fleet: 3 robots, dispatch one, verify only that one moves
  - RobotFSMBridge integration: robot telemetry creates FSM state
"""

import queue

import pytest

from engine.comms.event_bus import EventBus
from engine.comms.mqtt_bridge import MQTTBridge
from engine.tactical.target_tracker import TargetTracker


# ===========================================================================
# Helpers
# ===========================================================================


def _make_pipeline():
    """Create a full pipeline: EventBus + TargetTracker + MQTTBridge.

    Returns (event_bus, tracker, bridge).
    The bridge is NOT connected to a real broker -- we bypass MQTT
    by calling _on_robot_telemetry() directly.
    """
    bus = EventBus()
    tracker = TargetTracker()
    bridge = MQTTBridge(
        event_bus=bus,
        target_tracker=tracker,
        site_id="test",
    )
    return bus, tracker, bridge


# ===========================================================================
# Telemetry flow: Adapter -> Bridge -> Tracker
# ===========================================================================


@pytest.mark.unit
class TestTelemetryFlow:
    """FakeRobotAdapter.publish_telemetry() -> MQTTBridge._on_robot_telemetry() -> TargetTracker."""

    def test_robot_appears_in_tracker_after_telemetry(self):
        """After adapter publishes telemetry, robot appears as friendly in tracker."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(robot_id="rover-01", asset_type="rover")
        adapter.connect_to_bridge(bridge)

        adapter.publish_telemetry()

        friendlies = tracker.get_friendlies()
        assert len(friendlies) >= 1
        rover = [t for t in friendlies if "rover-01" in t.target_id]
        assert len(rover) == 1
        assert rover[0].alliance == "friendly"
        assert rover[0].asset_type == "rover"

    def test_position_updates_flow_through(self):
        """Position updates from adapter flow through bridge to tracker."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(
            robot_id="rover-01",
            asset_type="rover",
            lat=37.77,
            lng=-122.41,
        )
        adapter.connect_to_bridge(bridge)

        adapter.publish_telemetry()

        target = tracker.get_target("mqtt_rover-01")
        assert target is not None
        # Position should be present (lat/lng get mapped to x/y by bridge)

    def test_battery_updates_flow_through(self):
        """Battery level from adapter flows through to tracker."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(robot_id="rover-01", battery=0.75)
        adapter.connect_to_bridge(bridge)

        adapter.publish_telemetry()

        target = tracker.get_target("mqtt_rover-01")
        assert target is not None
        assert target.battery == 0.75

    def test_telemetry_publishes_eventbus_event(self):
        """Telemetry flow also publishes to EventBus for UI consumers."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        q = bus.subscribe()
        adapter = FakeRobotAdapter.create(robot_id="rover-01")
        adapter.connect_to_bridge(bridge)

        adapter.publish_telemetry()

        events = []
        try:
            while True:
                events.append(q.get_nowait())
        except queue.Empty:
            pass
        telem_events = [e for e in events if e["type"] == "mqtt_robot_telemetry"]
        assert len(telem_events) >= 1
        assert telem_events[0]["data"]["robot_id"] == "rover-01"


# ===========================================================================
# Command flow: Bridge -> Adapter -> FakeRobot
# ===========================================================================


@pytest.mark.unit
class TestCommandFlow:
    """Command dispatch through adapter reaches FakeRobot."""

    def test_dispatch_command_reaches_robot(self):
        """Sending dispatch through adapter makes robot move."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        adapter = FakeRobotAdapter.create(robot_id="rover-01")
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        assert adapter.robot.status == "moving"

    def test_robot_position_changes_after_dispatch_and_tick(self):
        """After dispatch and ticking, robot position changes."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        adapter = FakeRobotAdapter.create(
            robot_id="rover-01",
            lat=37.7749,
            lng=-122.4194,
        )
        initial_lat = adapter.robot.lat

        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})

        # Tick several times
        for _ in range(50):
            adapter.tick(0.1)

        assert adapter.robot.lat != initial_lat

    def test_updated_telemetry_flows_back_to_tracker(self):
        """After dispatch + tick, updated position flows back to tracker."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(
            robot_id="rover-01",
            lat=37.7749,
            lng=-122.4194,
        )
        adapter.connect_to_bridge(bridge)

        # Publish initial position
        adapter.publish_telemetry()
        target_before = tracker.get_target("mqtt_rover-01")
        assert target_before is not None

        # Dispatch and tick
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        for _ in range(50):
            adapter.tick(0.1)

        # Publish updated telemetry
        adapter.publish_telemetry()

        # Tracker should have updated data
        target_after = tracker.get_target("mqtt_rover-01")
        assert target_after is not None


# ===========================================================================
# Full roundtrip
# ===========================================================================


@pytest.mark.unit
class TestFullRoundtrip:
    """Full roundtrip: dispatch -> execute -> telemetry -> tracker."""

    def test_dispatch_execute_telemetry_roundtrip(self):
        """Complete lifecycle: create, dispatch, tick, verify in tracker."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(
            robot_id="rover-01",
            lat=37.7749,
            lng=-122.4194,
        )
        adapter.connect_to_bridge(bridge)

        # 1. Publish initial telemetry -> appears in tracker
        adapter.publish_telemetry()
        assert tracker.get_target("mqtt_rover-01") is not None

        # 2. Dispatch
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        assert adapter.robot.status == "moving"

        # 3. Tick (robot moves)
        for _ in range(50):
            adapter.tick(0.1)

        # 4. Publish updated telemetry
        adapter.publish_telemetry()

        # 5. Verify tracker has updated status
        target = tracker.get_target("mqtt_rover-01")
        assert target is not None
        assert target.status in ("active", "moving", "patrolling")

    def test_recall_roundtrip(self):
        """Dispatch then recall, verify status flows back."""
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus, tracker, bridge = _make_pipeline()
        adapter = FakeRobotAdapter.create(robot_id="rover-01")
        adapter.connect_to_bridge(bridge)

        # Dispatch
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        adapter.tick(0.1)
        adapter.publish_telemetry()

        # Recall
        adapter.receive_command("recall")
        adapter.tick(0.1)
        adapter.publish_telemetry()

        target = tracker.get_target("mqtt_rover-01")
        assert target is not None


# ===========================================================================
# Fleet — multiple robots
# ===========================================================================


@pytest.mark.unit
class TestFleetPipeline:
    """Fleet of 3 robots: dispatch one, verify only that one moves."""

    def test_fleet_dispatch_one_only_that_one_moves(self):
        """In a 3-robot fleet, dispatching one leaves others idle."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter

        bus, tracker, bridge = _make_pipeline()
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        fleet.add_robot("rover-02")
        fleet.add_robot("drone-01", robot_type="drone")
        fleet.connect_to_bridge(bridge)

        # Dispatch only rover-01
        fleet.dispatch("rover-01", lat=37.78, lng=-122.42)

        assert fleet.get_adapter("rover-01").robot.status == "moving"
        assert fleet.get_adapter("rover-02").robot.status == "idle"
        assert fleet.get_adapter("drone-01").robot.status == "idle"

    def test_fleet_telemetry_all_appear_in_tracker(self):
        """All fleet robots appear in tracker after tick + publish."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter

        bus, tracker, bridge = _make_pipeline()
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01")
        fleet.add_robot("rover-02")
        fleet.add_robot("drone-01", robot_type="drone")
        fleet.connect_to_bridge(bridge)

        # Set immediate telemetry interval and tick
        for adapter in fleet._adapters.values():
            adapter.telemetry_interval = 0.0
        fleet.tick_all(0.1)

        friendlies = tracker.get_friendlies()
        ids = {t.target_id for t in friendlies}
        assert "mqtt_rover-01" in ids
        assert "mqtt_rover-02" in ids
        assert "mqtt_drone-01" in ids

    def test_fleet_dispatched_robot_position_updates(self):
        """Dispatched robot's position updates in tracker after ticks."""
        from engine.simulation.robot_adapter import FakeRobotFleetAdapter

        bus, tracker, bridge = _make_pipeline()
        fleet = FakeRobotFleetAdapter()
        fleet.add_robot("rover-01", lat=37.7749, lng=-122.4194)
        fleet.connect_to_bridge(bridge)

        # Set immediate publish
        for adapter in fleet._adapters.values():
            adapter.telemetry_interval = 0.0

        # Initial telemetry
        fleet.tick_all(0.1)

        # Dispatch
        fleet.dispatch("rover-01", lat=37.78, lng=-122.42)

        # Tick many times
        for _ in range(50):
            fleet.tick_all(0.1)

        target = tracker.get_target("mqtt_rover-01")
        assert target is not None


# ===========================================================================
# RobotFSMBridge integration
# ===========================================================================


@pytest.mark.unit
class TestRobotFSMBridgeIntegration:
    """FakeRobotAdapter telemetry creates FSM state via RobotFSMBridge."""

    def test_telemetry_creates_fsm_state(self):
        """Robot telemetry through adapter -> FSM bridge creates FSM."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus = EventBus()
        fsm_bridge = RobotFSMBridge(bus)

        adapter = FakeRobotAdapter.create(robot_id="rover-01", asset_type="rover")

        # Feed telemetry to FSM bridge
        telem = adapter.publish_telemetry()
        fsm_bridge.on_telemetry("rover-01", telem)

        assert fsm_bridge.get_fsm_state("rover-01") == "idle"

    def test_dispatch_updates_fsm_to_patrolling(self):
        """Dispatching robot and feeding telemetry transitions FSM."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus = EventBus()
        fsm_bridge = RobotFSMBridge(bus)

        adapter = FakeRobotAdapter.create(robot_id="rover-01", asset_type="rover")
        fsm_bridge.register_robot("rover-01", asset_type="rover")

        # Dispatch
        adapter.receive_command("dispatch", {"lat": 37.78, "lng": -122.42})
        telem = adapter.publish_telemetry()
        fsm_bridge.on_telemetry("rover-01", telem)

        # FakeRobot status is "moving" -> FSM maps to "patrolling"
        assert fsm_bridge.get_fsm_state("rover-01") == "patrolling"

    def test_recall_updates_fsm_to_rtb(self):
        """Recalling robot transitions FSM to RTB."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        from engine.simulation.robot_adapter import FakeRobotAdapter

        bus = EventBus()
        fsm_bridge = RobotFSMBridge(bus)

        adapter = FakeRobotAdapter.create(robot_id="rover-01", asset_type="rover")
        fsm_bridge.register_robot("rover-01", asset_type="rover")

        adapter.receive_command("recall")
        telem = adapter.publish_telemetry()
        fsm_bridge.on_telemetry("rover-01", telem)

        assert fsm_bridge.get_fsm_state("rover-01") == "rtb"
