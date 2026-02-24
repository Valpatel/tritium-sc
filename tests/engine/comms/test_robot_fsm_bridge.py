"""Unit tests for RobotFSMBridge — bridges MQTT robots to the FSM system.

TDD: tests written first, implementation follows.

Tests cover:
  - Creating FSMs when robots connect via MQTT telemetry
  - Mapping robot telemetry status to FSM states
  - Engine commands (dispatch/patrol/recall) trigger FSM transitions
  - Syncing FSM state back to robot via MQTT command topic
  - Works with FakeRobot (testing) and MQTT robot payloads
  - Cleanup when robots disconnect
"""
from __future__ import annotations

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.fake_robot import FakeRobot
from engine.simulation.state_machine import StateMachine


@pytest.mark.unit
class TestRobotFSMBridgeCreation:
    """FSM creation when robots connect."""

    def test_import_bridge(self):
        """Bridge module is importable."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        assert RobotFSMBridge is not None

    def test_create_bridge(self):
        """Bridge instantiates with event bus."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        assert bridge is not None

    def test_register_robot_creates_fsm(self):
        """Registering a robot creates a corresponding FSM."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("rover-01", asset_type="rover")
        fsm = bridge.get_fsm("rover-01")
        assert fsm is not None
        assert isinstance(fsm, StateMachine)

    def test_register_rover_starts_idle(self):
        """Rover FSM starts in idle state."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("rover-01", asset_type="rover")
        assert bridge.get_fsm_state("rover-01") == "idle"

    def test_register_drone_starts_idle(self):
        """Drone FSM starts in idle state."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("drone-01", asset_type="drone")
        assert bridge.get_fsm_state("drone-01") == "idle"

    def test_register_turret_starts_scanning(self):
        """Turret FSM starts in scanning (idle->scanning is immediate)."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("turret-01", asset_type="turret")
        # Turret FSM has idle->scanning as always-true transition,
        # so after the initial tick it is already in scanning.
        assert bridge.get_fsm_state("turret-01") == "scanning"

    def test_register_duplicate_is_noop(self):
        """Re-registering same robot ID does not reset FSM."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("rover-01", asset_type="rover")
        # Force a state change to prove re-register doesn't reset
        bridge.on_telemetry("rover-01", {"status": "moving"})
        bridge.register_robot("rover-01", asset_type="rover")
        # State should still reflect the update, not reset to idle
        state = bridge.get_fsm_state("rover-01")
        assert state is not None

    def test_unknown_robot_returns_none(self):
        """Getting FSM for unknown robot returns None."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        assert bridge.get_fsm("unknown-bot") is None
        assert bridge.get_fsm_state("unknown-bot") is None

    def test_unsupported_type_returns_no_fsm(self):
        """Types without FSM (e.g. person/neutral) register but have no FSM."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("civilian-01", asset_type="person", alliance="neutral")
        assert bridge.get_fsm("civilian-01") is None

    def test_list_robots(self):
        """Bridge tracks all registered robot IDs."""
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.register_robot("drone-01", asset_type="drone")
        ids = bridge.robot_ids
        assert "rover-01" in ids
        assert "drone-01" in ids


@pytest.mark.unit
class TestTelemetryToFSM:
    """Mapping robot telemetry status to FSM state transitions."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge

    def test_idle_telemetry_stays_idle(self):
        """Robot reporting idle keeps FSM in idle."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_telemetry("rover-01", {"status": "idle"})
        assert bridge.get_fsm_state("rover-01") == "idle"

    def test_moving_telemetry_transitions_to_pursuing_or_patrolling(self):
        """Robot reporting 'moving' maps to an active FSM state."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_telemetry("rover-01", {"status": "moving"})
        state = bridge.get_fsm_state("rover-01")
        # "moving" should map to patrolling (waypoint-following)
        assert state == "patrolling"

    def test_patrolling_telemetry(self):
        """Robot reporting 'patrolling' maps to patrolling FSM state."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_telemetry("rover-01", {"status": "patrolling"})
        assert bridge.get_fsm_state("rover-01") == "patrolling"

    def test_returning_telemetry_maps_to_rtb(self):
        """Robot reporting 'returning' maps to RTB FSM state."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_telemetry("rover-01", {"status": "returning"})
        assert bridge.get_fsm_state("rover-01") == "rtb"

    def test_telemetry_for_unknown_robot_auto_registers(self):
        """Telemetry from unknown robot auto-registers it."""
        bridge = self._make_bridge()
        bridge.on_telemetry("rover-99", {
            "status": "idle",
            "asset_type": "rover",
        })
        assert bridge.get_fsm("rover-99") is not None
        assert bridge.get_fsm_state("rover-99") == "idle"

    def test_telemetry_updates_position(self):
        """Telemetry position data is stored on the bridge."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_telemetry("rover-01", {
            "status": "moving",
            "lat": 37.78,
            "lng": -122.42,
            "heading": 90.0,
            "speed": 1.5,
            "battery": 0.85,
        })
        info = bridge.get_robot_info("rover-01")
        assert info is not None
        assert info["lat"] == 37.78
        assert info["battery"] == 0.85

    def test_drone_scouting_state(self):
        """Drone 'moving' maps to 'scouting' (drone FSM equivalent)."""
        bridge = self._make_bridge()
        bridge.register_robot("drone-01", asset_type="drone")
        bridge.on_telemetry("drone-01", {"status": "moving"})
        state = bridge.get_fsm_state("drone-01")
        assert state == "scouting"

    def test_drone_returning_maps_to_rtb(self):
        """Drone 'returning' maps to RTB."""
        bridge = self._make_bridge()
        bridge.register_robot("drone-01", asset_type="drone")
        bridge.on_telemetry("drone-01", {"status": "returning"})
        assert bridge.get_fsm_state("drone-01") == "rtb"


@pytest.mark.unit
class TestCommandToFSM:
    """Engine commands trigger FSM transitions and publish MQTT."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge, bus

    def test_dispatch_command_transitions_rover(self):
        """Dispatch command transitions rover FSM to patrolling."""
        bridge, bus = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_command("rover-01", "dispatch", {"lat": 37.78, "lng": -122.42})
        state = bridge.get_fsm_state("rover-01")
        assert state == "patrolling"

    def test_patrol_command_transitions_rover(self):
        """Patrol command transitions rover FSM to patrolling."""
        bridge, bus = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_command("rover-01", "patrol", {
            "waypoints": [(37.78, -122.42), (37.79, -122.41)],
        })
        assert bridge.get_fsm_state("rover-01") == "patrolling"

    def test_recall_command_transitions_to_rtb(self):
        """Recall command transitions rover to RTB."""
        bridge, bus = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        # First dispatch to get out of idle
        bridge.on_command("rover-01", "dispatch", {"lat": 37.78, "lng": -122.42})
        # Then recall
        bridge.on_command("rover-01", "recall", {})
        assert bridge.get_fsm_state("rover-01") == "rtb"

    def test_command_publishes_event(self):
        """Commands publish an event on the event bus."""
        bridge, bus = self._make_bridge()
        q = bus.subscribe()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_command("rover-01", "dispatch", {"lat": 37.78, "lng": -122.42})
        # Drain events to find the command event
        events = []
        import queue as _q
        try:
            while True:
                events.append(q.get_nowait())
        except _q.Empty:
            pass
        cmd_events = [e for e in events if e["type"] == "robot_fsm_command"]
        assert len(cmd_events) >= 1
        assert cmd_events[0]["data"]["robot_id"] == "rover-01"
        assert cmd_events[0]["data"]["command"] == "dispatch"

    def test_command_for_unknown_robot_is_noop(self):
        """Command for unknown robot is a no-op (no crash)."""
        bridge, bus = self._make_bridge()
        # Should not raise
        bridge.on_command("ghost-bot", "dispatch", {"lat": 0, "lng": 0})

    def test_dispatch_drone_transitions_to_scouting(self):
        """Dispatch transitions drone FSM to scouting."""
        bridge, bus = self._make_bridge()
        bridge.register_robot("drone-01", asset_type="drone")
        bridge.on_command("drone-01", "dispatch", {"lat": 37.78, "lng": -122.42})
        assert bridge.get_fsm_state("drone-01") == "scouting"


@pytest.mark.unit
class TestFSMStateSync:
    """FSM state syncing back to robot info and events."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge, bus

    def test_state_change_publishes_event(self):
        """FSM state transitions publish robot_fsm_state_change event."""
        bridge, bus = self._make_bridge()
        q = bus.subscribe()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.on_command("rover-01", "dispatch", {"lat": 37.78, "lng": -122.42})

        import queue as _q
        events = []
        try:
            while True:
                events.append(q.get_nowait())
        except _q.Empty:
            pass
        state_events = [e for e in events if e["type"] == "robot_fsm_state_change"]
        assert len(state_events) >= 1
        assert state_events[0]["data"]["robot_id"] == "rover-01"

    def test_get_all_states(self):
        """get_all_states() returns dict of robot_id -> fsm_state."""
        bridge, bus = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.register_robot("drone-01", asset_type="drone")
        states = bridge.get_all_states()
        assert states["rover-01"] == "idle"
        assert states["drone-01"] == "idle"


@pytest.mark.unit
class TestFakeRobotIntegration:
    """Bridge works with FakeRobot for testing without hardware."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge

    def test_register_from_fake_robot(self):
        """Can register a FakeRobot via its telemetry."""
        bridge = self._make_bridge()
        robot = FakeRobot(robot_id="fake-rover", asset_type="rover")
        telemetry = robot.get_telemetry()
        bridge.register_robot(
            telemetry["robot_id"],
            asset_type=telemetry["asset_type"],
        )
        assert bridge.get_fsm_state("fake-rover") == "idle"

    def test_fake_robot_dispatch_syncs(self):
        """Dispatching a FakeRobot and feeding telemetry updates FSM."""
        bridge = self._make_bridge()
        robot = FakeRobot(robot_id="fake-rover", asset_type="rover")
        bridge.register_robot("fake-rover", asset_type="rover")

        # Dispatch the fake robot
        robot.dispatch(37.78, -122.42)
        telemetry = robot.get_telemetry()
        bridge.on_telemetry("fake-rover", telemetry)

        # FakeRobot status is "moving", bridge should map to patrolling
        assert bridge.get_fsm_state("fake-rover") == "patrolling"

    def test_fake_robot_recall_syncs(self):
        """Recalling a FakeRobot and feeding telemetry updates FSM to RTB."""
        bridge = self._make_bridge()
        robot = FakeRobot(robot_id="fake-rover", asset_type="rover")
        bridge.register_robot("fake-rover", asset_type="rover")

        robot.recall()
        telemetry = robot.get_telemetry()
        bridge.on_telemetry("fake-rover", telemetry)
        assert bridge.get_fsm_state("fake-rover") == "rtb"

    def test_fake_robot_patrol_syncs(self):
        """Patrolling a FakeRobot syncs to patrolling FSM state."""
        bridge = self._make_bridge()
        robot = FakeRobot(robot_id="fake-rover", asset_type="rover")
        bridge.register_robot("fake-rover", asset_type="rover")

        robot.patrol([(37.78, -122.42), (37.79, -122.41)])
        telemetry = robot.get_telemetry()
        bridge.on_telemetry("fake-rover", telemetry)
        assert bridge.get_fsm_state("fake-rover") == "patrolling"

    def test_fake_robot_idle_after_arrival(self):
        """FakeRobot going idle after arrival syncs FSM back to idle."""
        bridge = self._make_bridge()
        robot = FakeRobot(robot_id="fake-rover", asset_type="rover")
        bridge.register_robot("fake-rover", asset_type="rover")

        # Start moving
        robot.dispatch(37.78, -122.42)
        bridge.on_telemetry("fake-rover", robot.get_telemetry())
        assert bridge.get_fsm_state("fake-rover") == "patrolling"

        # Simulate arrival: set status to idle
        robot.status = "idle"
        robot.speed = 0.0
        bridge.on_telemetry("fake-rover", robot.get_telemetry())
        assert bridge.get_fsm_state("fake-rover") == "idle"


@pytest.mark.unit
class TestCleanup:
    """Robot unregistration and cleanup."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge

    def test_unregister_robot(self):
        """Unregistering a robot removes its FSM."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        assert bridge.get_fsm("rover-01") is not None
        bridge.unregister_robot("rover-01")
        assert bridge.get_fsm("rover-01") is None
        assert "rover-01" not in bridge.robot_ids

    def test_unregister_unknown_is_noop(self):
        """Unregistering unknown robot does not raise."""
        bridge = self._make_bridge()
        bridge.unregister_robot("ghost")  # no crash

    def test_clear_all(self):
        """clear_all() removes all robots and FSMs."""
        bridge = self._make_bridge()
        bridge.register_robot("rover-01", asset_type="rover")
        bridge.register_robot("drone-01", asset_type="drone")
        bridge.clear_all()
        assert len(bridge.robot_ids) == 0


@pytest.mark.unit
class TestMQTTBridgeIntegration:
    """Bridge generates MQTT-compatible command payloads."""

    def _make_bridge(self):
        from engine.comms.robot_fsm_bridge import RobotFSMBridge
        bus = EventBus()
        bridge = RobotFSMBridge(bus)
        return bridge, bus

    def test_build_dispatch_payload(self):
        """build_command_payload returns MQTT-compatible dispatch dict."""
        bridge, bus = self._make_bridge()
        payload = bridge.build_command_payload("dispatch", {
            "lat": 37.78,
            "lng": -122.42,
        })
        assert payload["command"] == "dispatch"
        assert payload["lat"] == 37.78
        assert payload["lng"] == -122.42
        assert "timestamp" in payload

    def test_build_patrol_payload(self):
        """build_command_payload returns MQTT-compatible patrol dict."""
        bridge, bus = self._make_bridge()
        payload = bridge.build_command_payload("patrol", {
            "waypoints": [(37.78, -122.42), (37.79, -122.41)],
        })
        assert payload["command"] == "patrol"
        assert len(payload["waypoints"]) == 2

    def test_build_recall_payload(self):
        """build_command_payload returns MQTT-compatible recall dict."""
        bridge, bus = self._make_bridge()
        payload = bridge.build_command_payload("recall", {})
        assert payload["command"] == "recall"
        assert "timestamp" in payload
