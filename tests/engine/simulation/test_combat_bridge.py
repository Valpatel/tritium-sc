# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CombatBridge tests — routes simulation combat actions to physical hardware via MQTT.

TDD: These tests are written FIRST, before the implementation exists.
Each test verifies one aspect of the CombatBridge contract.

The CombatBridge provides a dual-authority model:
  - Simulation engine remains authoritative for game state (score, hits, damage)
  - Hardware commands are sent in parallel via MQTT
  - Hardware telemetry is recorded alongside sim state for correlation
"""

import json
import time
import pytest
from unittest.mock import MagicMock, patch, call

from engine.comms.event_bus import EventBus
from engine.simulation.target import SimulationTarget
from engine.simulation.combat_bridge import CombatBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_bus() -> EventBus:
    return EventBus()


def _make_mock_mqtt(site_id: str = "home") -> MagicMock:
    """Create a mock MQTTBridge with the methods CombatBridge needs."""
    mqtt = MagicMock()
    mqtt._site = site_id
    mqtt.connected = True
    mqtt.publish = MagicMock()
    mqtt.publish_dispatch = MagicMock()
    mqtt.publish_patrol = MagicMock()
    mqtt.publish_recall = MagicMock()
    return mqtt


def _make_turret(target_id: str = "turret-1", position: tuple = (10.0, 20.0)) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name="Alpha Turret",
        alliance="friendly",
        asset_type="turret",
        position=position,
        speed=0.0,
        health=200.0,
        max_health=200.0,
        weapon_range=80.0,
        weapon_cooldown=1.5,
        weapon_damage=15.0,
        is_combatant=True,
    )


def _make_rover(target_id: str = "rover-1", position: tuple = (5.0, 5.0)) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name="Rover Alpha",
        alliance="friendly",
        asset_type="rover",
        position=position,
        speed=3.0,
        health=150.0,
        max_health=150.0,
        weapon_range=60.0,
        weapon_cooldown=2.0,
        weapon_damage=12.0,
        is_combatant=True,
    )


def _make_hostile(target_id: str = "hostile-1", position: tuple = (50.0, 50.0)) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name="Intruder Alpha",
        alliance="hostile",
        asset_type="person",
        position=position,
        speed=1.5,
        health=80.0,
        max_health=80.0,
        weapon_range=40.0,
        is_combatant=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCombatBridgeCreation:
    """Test bridge initialization and basic properties."""

    def test_bridge_creation(self):
        """CombatBridge initializes with an MQTT bridge and EventBus."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        assert bridge is not None
        assert bridge.bindings == {}
        assert bridge.active is False

    def test_bridge_creation_with_site_id(self):
        """CombatBridge uses the site ID from the MQTT bridge."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt(site_id="base-alpha")
        bridge = CombatBridge(mqtt, bus)

        assert bridge.site_id == "base-alpha"

    def test_bridge_creation_with_sim_engine(self):
        """CombatBridge can optionally reference the SimulationEngine."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        engine = MagicMock()
        bridge = CombatBridge(mqtt, bus, sim_engine=engine)

        assert bridge._sim_engine is engine


class TestDeviceMapping:
    """Test binding simulation target IDs to MQTT robot IDs."""

    def test_register_device_mapping(self):
        """bind_unit() maps a simulation target ID to an MQTT robot ID."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")

        assert bridge.bindings == {"turret-1": "real-turret-01"}

    def test_register_multiple_mappings(self):
        """Multiple bind_unit() calls register multiple mappings."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")
        bridge.bind_unit("rover-1", "real-rover-01")

        assert len(bridge.bindings) == 2
        assert bridge.bindings["turret-1"] == "real-turret-01"
        assert bridge.bindings["rover-1"] == "real-rover-01"

    def test_unbind_unit(self):
        """unbind_unit() removes the mapping."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")
        bridge.unbind_unit("turret-1")

        assert bridge.bindings == {}

    def test_unbind_nonexistent(self):
        """unbind_unit() on a nonexistent mapping does not raise."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.unbind_unit("nonexistent")  # Should not raise

    def test_get_mqtt_id(self):
        """get_mqtt_id() returns the MQTT robot ID for a sim target."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")

        assert bridge.get_mqtt_id("turret-1") == "real-turret-01"
        assert bridge.get_mqtt_id("nonexistent") is None

    def test_get_sim_id(self):
        """get_sim_id() returns the sim target ID for an MQTT robot ID."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")

        assert bridge.get_sim_id("real-turret-01") == "turret-1"
        assert bridge.get_sim_id("nonexistent") is None

    def test_rebind_overwrites(self):
        """Binding the same sim_id to a different mqtt_id overwrites."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.bind_unit("turret-1", "real-turret-01")
        bridge.bind_unit("turret-1", "real-turret-02")

        assert bridge.bindings["turret-1"] == "real-turret-02"


class TestDispatchCommand:
    """Test that dispatch events produce MQTT commands."""

    def test_dispatch_publishes_mqtt_command(self):
        """on_dispatch() publishes a dispatch command to the bound robot's MQTT topic."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_dispatch({
            "unit_id": "rover-1",
            "destination": {"x": 50.0, "y": 100.0},
        })

        mqtt.publish.assert_called()
        call_args = mqtt.publish.call_args
        topic = call_args[0][0] if call_args[0] else call_args[1].get("topic", "")
        payload_str = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("payload", "")
        payload = json.loads(payload_str)

        assert "robots/real-rover-01/command" in topic
        assert payload["command"] == "dispatch"
        assert payload["x"] == 50.0
        assert payload["y"] == 100.0

    def test_dispatch_unregistered_device_ignored(self):
        """on_dispatch() for an unregistered sim target does nothing."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.on_dispatch({
            "unit_id": "unknown-unit",
            "destination": {"x": 50.0, "y": 100.0},
        })

        mqtt.publish.assert_not_called()

    def test_dispatch_records_command_log(self):
        """on_dispatch() records the command in the command log for correlation."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_dispatch({
            "unit_id": "rover-1",
            "destination": {"x": 50.0, "y": 100.0},
        })

        log = bridge.command_log
        assert len(log) == 1
        assert log[0]["command"] == "dispatch"
        assert log[0]["sim_id"] == "rover-1"
        assert log[0]["mqtt_id"] == "real-rover-01"


class TestRecallCommand:
    """Test that recall events produce MQTT commands."""

    def test_recall_publishes_mqtt_command(self):
        """on_recall() publishes a recall command to the bound robot's MQTT topic."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_recall({"unit_id": "rover-1"})

        mqtt.publish.assert_called()
        call_args = mqtt.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert "robots/real-rover-01/command" in topic
        assert payload["command"] == "recall"

    def test_recall_unregistered_ignored(self):
        """on_recall() for an unregistered sim target does nothing."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.on_recall({"unit_id": "unknown"})

        mqtt.publish.assert_not_called()


class TestPatrolCommand:
    """Test that patrol events produce MQTT commands."""

    def test_patrol_publishes_mqtt_command(self):
        """on_patrol() publishes a patrol command with waypoints."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        waypoints = [{"x": 10.0, "y": 10.0}, {"x": 20.0, "y": 20.0}, {"x": 30.0, "y": 30.0}]
        bridge.on_patrol({
            "unit_id": "rover-1",
            "waypoints": waypoints,
        })

        mqtt.publish.assert_called()
        call_args = mqtt.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert "robots/real-rover-01/command" in topic
        assert payload["command"] == "patrol"
        assert len(payload["waypoints"]) == 3

    def test_patrol_unregistered_ignored(self):
        """on_patrol() for an unregistered sim target does nothing."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.on_patrol({
            "unit_id": "unknown",
            "waypoints": [{"x": 10.0, "y": 10.0}],
        })

        mqtt.publish.assert_not_called()


class TestFireCommand:
    """Test that fire events produce MQTT commands."""

    def test_fire_publishes_mqtt_command(self):
        """on_fire() publishes aim + fire commands to the bound robot."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("turret-1", "real-turret-01")

        bridge.on_fire({
            "shooter_id": "turret-1",
            "target_id": "hostile-1",
            "target_position": {"x": 50.0, "y": 50.0},
            "shooter_position": {"x": 10.0, "y": 20.0},
        })

        # Should publish at least one command (fire, potentially aim first)
        assert mqtt.publish.call_count >= 1

        # Check the fire command
        calls = mqtt.publish.call_args_list
        fire_found = False
        for c in calls:
            topic = c[0][0]
            payload = json.loads(c[0][1])
            if payload.get("command") == "fire":
                fire_found = True
                assert "robots/real-turret-01/command" in topic
                assert "target_x" in payload
                assert "target_y" in payload

        assert fire_found, "No fire command was published"

    def test_fire_unregistered_ignored(self):
        """on_fire() for an unregistered shooter does nothing."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.on_fire({
            "shooter_id": "unknown-turret",
            "target_id": "hostile-1",
            "target_position": {"x": 50.0, "y": 50.0},
            "shooter_position": {"x": 10.0, "y": 20.0},
        })

        mqtt.publish.assert_not_called()

    def test_fire_records_in_command_log(self):
        """on_fire() records the fire command for sim-vs-hardware correlation."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("turret-1", "real-turret-01")

        bridge.on_fire({
            "shooter_id": "turret-1",
            "target_id": "hostile-1",
            "target_position": {"x": 50.0, "y": 50.0},
            "shooter_position": {"x": 10.0, "y": 20.0},
        })

        log = bridge.command_log
        fire_entries = [e for e in log if e["command"] == "fire"]
        assert len(fire_entries) >= 1
        assert fire_entries[0]["sim_id"] == "turret-1"
        assert fire_entries[0]["mqtt_id"] == "real-turret-01"


class TestTelemetryUpdates:
    """Test that inbound robot telemetry updates simulation targets."""

    def test_telemetry_updates_sim_target(self):
        """Inbound MQTT telemetry updates the corresponding sim target's HW state."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        engine = MagicMock()

        rover = _make_rover()
        engine.get_target.return_value = rover

        bridge = CombatBridge(mqtt, bus, sim_engine=engine)
        bridge.bind_unit("rover-1", "real-rover-01")

        telemetry = {
            "robot_id": "real-rover-01",
            "position": {"x": 12.0, "y": 8.0},
            "heading": 90.0,
            "speed": 2.5,
            "battery": 0.75,
            "status": "active",
        }
        bridge.on_telemetry("real-rover-01", telemetry)

        # The bridge should record hardware state
        hw_state = bridge.get_hardware_state("rover-1")
        assert hw_state is not None
        assert hw_state["position"]["x"] == 12.0
        assert hw_state["position"]["y"] == 8.0
        assert hw_state["heading"] == 90.0
        assert hw_state["battery"] == 0.75

    def test_unregistered_device_telemetry_ignored(self):
        """Telemetry from an unregistered MQTT device is ignored."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        telemetry = {
            "robot_id": "unknown-robot",
            "position": {"x": 99.0, "y": 99.0},
        }
        bridge.on_telemetry("unknown-robot", telemetry)

        assert bridge.get_hardware_state("unknown") is None

    def test_telemetry_publishes_event(self):
        """Telemetry from a bound device publishes a combat_bridge_telemetry event."""
        bus = _make_event_bus()
        sub = bus.subscribe()
        mqtt = _make_mock_mqtt()
        engine = MagicMock()
        engine.get_target.return_value = _make_rover()

        bridge = CombatBridge(mqtt, bus, sim_engine=engine)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_telemetry("real-rover-01", {
            "position": {"x": 12.0, "y": 8.0},
            "heading": 90.0,
            "battery": 0.75,
        })

        # Drain the queue for the combat_bridge_telemetry event
        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "combat_bridge_telemetry":
                found = True
                break

        assert found, "Expected combat_bridge_telemetry event on EventBus"


class TestBridgeStartStop:
    """Test bridge lifecycle management."""

    def test_bridge_start_stop(self):
        """start() subscribes to EventBus events, stop() cleans up."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.start()
        assert bridge.active is True

        bridge.stop()
        assert bridge.active is False

    def test_bridge_start_is_idempotent(self):
        """Calling start() twice does not create duplicate subscriptions."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.start()
        bridge.start()  # Second call should be a no-op
        assert bridge.active is True

        bridge.stop()
        assert bridge.active is False

    def test_bridge_stop_is_idempotent(self):
        """Calling stop() when not started does not raise."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)

        bridge.stop()  # Should not raise
        assert bridge.active is False


class TestDualAuthority:
    """Test the dual-authority model: simulation is authoritative, hardware is recorded."""

    def test_dual_authority_sim_wins(self):
        """Simulation position overrides hardware position when there is conflict.

        The sim engine is authoritative for game state. Hardware telemetry is
        recorded for correlation but does NOT override the sim target position.
        """
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        engine = MagicMock()

        rover = _make_rover(position=(5.0, 5.0))
        engine.get_target.return_value = rover

        bridge = CombatBridge(mqtt, bus, sim_engine=engine)
        bridge.bind_unit("rover-1", "real-rover-01")

        # Hardware reports a different position
        bridge.on_telemetry("real-rover-01", {
            "position": {"x": 99.0, "y": 99.0},
            "heading": 180.0,
            "battery": 0.50,
        })

        # Sim target position should NOT be modified by the bridge
        assert rover.position == (5.0, 5.0), \
            "Simulation position must not be overridden by hardware telemetry"

        # But hardware state is recorded for correlation
        hw_state = bridge.get_hardware_state("rover-1")
        assert hw_state is not None
        assert hw_state["position"]["x"] == 99.0

    def test_dual_authority_status_report(self):
        """get_binding_status() returns both sim and hardware state for comparison."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        engine = MagicMock()

        rover = _make_rover(position=(5.0, 5.0))
        engine.get_target.return_value = rover

        bridge = CombatBridge(mqtt, bus, sim_engine=engine)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_telemetry("real-rover-01", {
            "position": {"x": 12.0, "y": 8.0},
            "heading": 90.0,
            "battery": 0.75,
        })

        status = bridge.get_binding_status("rover-1")
        assert status is not None
        assert status["sim_id"] == "rover-1"
        assert status["mqtt_id"] == "real-rover-01"
        assert "sim_position" in status
        assert "hw_position" in status
        assert status["sim_position"]["x"] == 5.0
        assert status["hw_position"]["x"] == 12.0

    def test_correlation_log_records_fire_events(self):
        """Fire events are logged with timestamps for sim-vs-hardware correlation."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("turret-1", "real-turret-01")

        bridge.on_fire({
            "shooter_id": "turret-1",
            "target_id": "hostile-1",
            "target_position": {"x": 50.0, "y": 50.0},
            "shooter_position": {"x": 10.0, "y": 20.0},
        })

        log = bridge.command_log
        assert len(log) >= 1
        assert "timestamp" in log[0]
        assert log[0]["source"] == "simulation"


class TestMQTTDisconnection:
    """Test graceful handling of MQTT disconnection."""

    def test_commands_when_mqtt_disconnected(self):
        """Commands are silently dropped (not raised) when MQTT is disconnected."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        mqtt.connected = False
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        # These should not raise even though MQTT is disconnected
        bridge.on_dispatch({
            "unit_id": "rover-1",
            "destination": {"x": 50.0, "y": 100.0},
        })
        bridge.on_recall({"unit_id": "rover-1"})
        bridge.on_fire({
            "shooter_id": "rover-1",
            "target_id": "hostile-1",
            "target_position": {"x": 50.0, "y": 50.0},
            "shooter_position": {"x": 10.0, "y": 20.0},
        })

        # Commands should still be logged even when MQTT is down
        assert len(bridge.command_log) >= 1

    def test_command_log_tracks_mqtt_status(self):
        """Command log entries include whether MQTT delivery succeeded."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        mqtt.connected = False
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        bridge.on_dispatch({
            "unit_id": "rover-1",
            "destination": {"x": 50.0, "y": 100.0},
        })

        entry = bridge.command_log[0]
        assert entry["mqtt_delivered"] is False


class TestCommandLogPruning:
    """Test that the command log does not grow unbounded."""

    def test_command_log_max_entries(self):
        """Command log is pruned to MAX_LOG_ENTRIES."""
        bus = _make_event_bus()
        mqtt = _make_mock_mqtt()
        bridge = CombatBridge(mqtt, bus)
        bridge.bind_unit("rover-1", "real-rover-01")

        # Generate many commands
        for i in range(bridge.MAX_LOG_ENTRIES + 50):
            bridge.on_dispatch({
                "unit_id": "rover-1",
                "destination": {"x": float(i), "y": float(i)},
            })

        assert len(bridge.command_log) <= bridge.MAX_LOG_ENTRIES
