# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for SensorSimulator — virtual sensor network.

TDD: these tests were written BEFORE the implementation.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.sensors import SensorDevice, SensorSimulator
from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    x: float = 0.0, z: float = 0.0, status: str = "active",
    name: str = "Test Target", target_id: str = "t1",
) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id, name=name, alliance="hostile",
        asset_type="person", position=(x, z), speed=1.5,
    )


def _make_sensor_sim(event_bus: EventBus | None = None) -> SensorSimulator:
    eb = event_bus or EventBus()
    return SensorSimulator(eb)


# ---------------------------------------------------------------------------
# Test: Sensor activates when target enters radius
# ---------------------------------------------------------------------------

class TestSensorActivation:

    def test_activates_when_target_within_radius(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)  # ~7m from sensor, within 10m radius

        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True
        assert sim.sensors[0].triggered_by == "Test Target"

    def test_does_not_activate_when_target_outside_radius(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=20.0, z=20.0)  # ~28m, outside 10m

        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False

    def test_activates_at_exact_boundary(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Boundary", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=10.0, z=0.0)  # Exactly at radius

        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Test: Sensor deactivates when target leaves radius
# ---------------------------------------------------------------------------

class TestSensorDeactivation:

    def test_deactivates_when_target_leaves(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        # Move target far away
        target.position = (50.0, 50.0)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False

    def test_deactivates_when_all_targets_leave(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (0.0, 0.0), 10.0)

        t1 = _make_target(x=3.0, z=3.0, target_id="t1")
        t2 = _make_target(x=4.0, z=4.0, target_id="t2")
        sim.tick(0.1, [t1, t2])
        assert sim.sensors[0].active is True

        t1.position = (100.0, 100.0)
        t2.position = (100.0, 100.0)
        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# Test: Door sensor (small radius) only triggers on very close targets
# ---------------------------------------------------------------------------

class TestDoorSensor:

    def test_door_sensor_small_radius(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("d1", "Front Door", "door", (0.0, 0.0), 3.0)

        far_target = _make_target(x=5.0, z=0.0)  # 5m away, outside 3m
        sim.tick(0.1, [far_target])
        assert sim.sensors[0].active is False

        close_target = _make_target(x=2.0, z=0.0, target_id="t2")  # 2m away
        sim.tick(0.1, [close_target])
        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Test: Tripwire (large radius) triggers on distant targets
# ---------------------------------------------------------------------------

class TestTripwire:

    def test_tripwire_large_radius(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("tw1", "East Wire", "tripwire", (0.0, 0.0), 40.0)

        target = _make_target(x=30.0, z=20.0)  # ~36m, within 40m
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True

    def test_tripwire_rejects_beyond_radius(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("tw1", "East Wire", "tripwire", (0.0, 0.0), 40.0)

        target = _make_target(x=35.0, z=25.0)  # ~43m, outside 40m
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# Test: Events published to EventBus
# ---------------------------------------------------------------------------

class TestEventBusPublish:

    def test_publishes_sensor_triggered_event(self):
        eb = EventBus()
        sub = eb.subscribe()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (10.0, 20.0), 15.0)

        target = _make_target(x=10.0, z=20.0, target_id="hostile-1")
        sim.tick(0.1, [target])

        # Drain events to find our sensor_triggered
        found = None
        for _ in range(100):
            try:
                msg = sub.get(timeout=0.01)
                if msg.get("type") == "sensor_triggered":
                    found = msg
                    break
            except Exception:
                break

        assert found is not None, "sensor_triggered event not published"
        data = found["data"]
        assert data["sensor_id"] == "s1"
        assert data["name"] == "Front Porch"
        assert data["type"] == "motion"
        assert data["triggered_by"] == "Test Target"
        assert data["target_id"] == "hostile-1"
        assert data["position"]["x"] == 10.0
        assert data["position"]["z"] == 20.0

    def test_publishes_sensor_cleared_event(self):
        eb = EventBus()
        sub = eb.subscribe()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])

        # Move target away
        target.position = (100.0, 100.0)
        sim.tick(0.1, [target])

        # Look for sensor_cleared
        found = None
        for _ in range(100):
            try:
                msg = sub.get(timeout=0.01)
                if msg.get("type") == "sensor_cleared":
                    found = msg
                    break
            except Exception:
                break

        assert found is not None, "sensor_cleared event not published"
        data = found["data"]
        assert data["sensor_id"] == "s1"
        assert data["name"] == "Front Porch"

    def test_no_event_when_sensor_stays_active(self):
        """If sensor is already active and target is still there, no new event."""
        eb = EventBus()
        sub = eb.subscribe()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])

        # Drain the trigger event
        triggered_count = 0
        for _ in range(100):
            try:
                msg = sub.get(timeout=0.01)
                if msg.get("type") == "sensor_triggered":
                    triggered_count += 1
            except Exception:
                break

        assert triggered_count == 1

        # Tick again with target still there
        sim.tick(0.1, [target])

        # Should be no new trigger event
        extra_triggers = 0
        for _ in range(100):
            try:
                msg = sub.get(timeout=0.01)
                if msg.get("type") == "sensor_triggered":
                    extra_triggers += 1
            except Exception:
                break

        assert extra_triggers == 0


# ---------------------------------------------------------------------------
# Test: Debounce — re-entering within 3s doesn't re-trigger
# ---------------------------------------------------------------------------

class TestDebounce:

    def test_no_retrigger_within_debounce_window(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)

        # First trigger
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        # Target leaves
        target.position = (100.0, 100.0)
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is False

        # Target re-enters immediately (within 3s debounce)
        target.position = (5.0, 5.0)
        sim.tick(0.1, [target])

        # Should NOT re-activate because debounce hasn't expired
        assert sim.sensors[0].active is False

    def test_retriggers_after_debounce_expires(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)

        # First trigger
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        # Target leaves
        target.position = (100.0, 100.0)
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is False

        # Manually set last_triggered to the past to simulate debounce expiry
        sim.sensors[0].last_triggered = time.monotonic() - 4.0

        # Re-enter
        target.position = (5.0, 5.0)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Test: Multiple sensors are independent
# ---------------------------------------------------------------------------

class TestMultipleSensors:

    def test_independent_activation(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front", "motion", (0.0, 0.0), 10.0)
        sim.add_sensor("s2", "Back", "motion", (100.0, 100.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True   # Front triggered
        assert sim.sensors[1].active is False   # Back not triggered

    def test_both_activate_with_targets_nearby(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Front", "motion", (0.0, 0.0), 10.0)
        sim.add_sensor("s2", "Back", "motion", (100.0, 100.0), 10.0)

        t1 = _make_target(x=5.0, z=5.0, target_id="t1")
        t2 = _make_target(x=105.0, z=105.0, target_id="t2")
        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].active is True
        assert sim.sensors[1].active is True

    def test_sensor_count(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "A", "motion", (0.0, 0.0), 10.0)
        sim.add_sensor("s2", "B", "door", (50.0, 50.0), 3.0)
        sim.add_sensor("s3", "C", "tripwire", (100.0, 0.0), 40.0)

        assert len(sim.sensors) == 3


# ---------------------------------------------------------------------------
# Test: Destroyed/eliminated targets don't trigger sensors
# ---------------------------------------------------------------------------

class TestDeadTargetsIgnored:

    @pytest.mark.parametrize("status", [
        "destroyed", "eliminated", "despawned", "escaped",
    ])
    def test_dead_target_does_not_trigger(self, status):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0, status=status)
        target.status = status
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False

    def test_active_target_triggers_but_eliminated_does_not(self):
        eb = EventBus()
        sim = SensorSimulator(eb)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        # Eliminate the target
        target.status = "eliminated"
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# Test: MQTT publishing
# ---------------------------------------------------------------------------

class TestMqttPublish:

    def test_publishes_to_mqtt_on_activation(self):
        eb = EventBus()
        mqtt = MagicMock()
        sim = SensorSimulator(eb, mqtt_bridge=mqtt, site_id="test_site")
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])

        mqtt.publish.assert_called_once()
        call_args = mqtt.publish.call_args
        assert "tritium/test_site/sensors/s1/events" in call_args[0][0]

    def test_mqtt_failure_does_not_crash(self):
        eb = EventBus()
        mqtt = MagicMock()
        mqtt.publish.side_effect = Exception("MQTT down")
        sim = SensorSimulator(eb, mqtt_bridge=mqtt)
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)

        target = _make_target(x=5.0, z=5.0)
        # Should not raise
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Test: set_event_bus()
# ---------------------------------------------------------------------------

class TestSetEventBus:

    def test_set_event_bus_replaces(self):
        eb1 = EventBus()
        eb2 = EventBus()
        sim = SensorSimulator(eb1)

        sim.set_event_bus(eb2)

        sub = eb2.subscribe()
        sim.add_sensor("s1", "Porch", "motion", (0.0, 0.0), 10.0)
        target = _make_target(x=5.0, z=5.0)
        sim.tick(0.1, [target])

        found = False
        for _ in range(100):
            try:
                msg = sub.get(timeout=0.01)
                if msg.get("type") == "sensor_triggered":
                    found = True
                    break
            except Exception:
                break

        assert found, "Event should be published to the new EventBus"


# ---------------------------------------------------------------------------
# Test: SensorDevice dataclass
# ---------------------------------------------------------------------------

class TestSensorDevice:

    def test_defaults(self):
        sd = SensorDevice(
            sensor_id="s1", name="Test", sensor_type="motion",
            position=(10.0, 20.0), radius=15.0,
        )
        assert sd.active is False
        assert sd.last_triggered == 0.0
        assert sd.triggered_by == ""

    def test_all_fields(self):
        sd = SensorDevice(
            sensor_id="s1", name="Test", sensor_type="door",
            position=(1.0, 2.0), radius=3.0,
            active=True, last_triggered=100.0, triggered_by="Bob",
        )
        assert sd.sensor_type == "door"
        assert sd.active is True
        assert sd.triggered_by == "Bob"
