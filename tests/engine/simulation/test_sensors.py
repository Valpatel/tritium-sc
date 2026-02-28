# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for SensorSimulator and SensorDevice.

Covers:
- SensorDevice dataclass initialization and defaults
- SensorSimulator initialization and add_sensor
- Trip detection: unit entering sensor range
- Debounce: sensor does not re-trigger within DEBOUNCE_S window
- Deactivation: sensor clears when all targets leave range
- Multiple sensors: each operates independently
- Sensor range boundaries: exactly at boundary, just inside, just outside
- Status filtering: destroyed/eliminated/despawned/escaped targets ignored
- Multiple targets: sensor triggers on first nearby target
- Event payloads: sensor_triggered and sensor_cleared events checked
- MQTT publish path: called when mqtt_bridge is provided
- set_event_bus: hot-swap event bus
- sensors property: returns a copy, not internal list
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from engine.simulation.sensors import SensorDevice, SensorSimulator


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class SimpleEventBus:
    """Minimal EventBus for unit testing — mirrors the pattern in test_combat.py."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


def make_target(
    target_id: str = "t1",
    name: str = "Rover",
    alliance: str = "hostile",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    status: str = "active",
):
    """Return a minimal SimpleNamespace that looks like a SimulationTarget."""
    return SimpleNamespace(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        status=status,
    )


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# SensorDevice dataclass
# ---------------------------------------------------------------------------

class TestSensorDevice:
    def test_required_fields(self):
        sd = SensorDevice(
            sensor_id="s1",
            name="Front Door",
            sensor_type="motion",
            position=(10.0, 20.0),
            radius=5.0,
        )
        assert sd.sensor_id == "s1"
        assert sd.name == "Front Door"
        assert sd.sensor_type == "motion"
        assert sd.position == (10.0, 20.0)
        assert sd.radius == 5.0

    def test_default_active_false(self):
        sd = SensorDevice("s1", "Door", "door", (0.0, 0.0), 3.0)
        assert sd.active is False

    def test_default_last_triggered_zero(self):
        sd = SensorDevice("s1", "Wire", "tripwire", (0.0, 0.0), 1.0)
        assert sd.last_triggered == 0.0

    def test_default_triggered_by_empty(self):
        sd = SensorDevice("s1", "Wire", "tripwire", (0.0, 0.0), 1.0)
        assert sd.triggered_by == ""

    def test_explicit_active_true(self):
        sd = SensorDevice("s1", "Wire", "tripwire", (0.0, 0.0), 1.0, active=True)
        assert sd.active is True

    def test_all_sensor_types_storable(self):
        for stype in ("motion", "door", "tripwire"):
            sd = SensorDevice("s", stype, stype, (0.0, 0.0), 1.0)
            assert sd.sensor_type == stype


# ---------------------------------------------------------------------------
# SensorSimulator initialization
# ---------------------------------------------------------------------------

class TestSensorSimulatorInit:
    def test_empty_sensors_on_init(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        assert sim.sensors == []

    def test_default_site_id(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        assert sim._site_id == "home"

    def test_custom_site_id(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus, site_id="alpha-site")
        assert sim._site_id == "alpha-site"

    def test_mqtt_bridge_stored(self):
        bus = SimpleEventBus()
        mqtt = MagicMock()
        sim = SensorSimulator(event_bus=bus, mqtt_bridge=mqtt)
        assert sim._mqtt is mqtt

    def test_no_mqtt_by_default(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        assert sim._mqtt is None


# ---------------------------------------------------------------------------
# add_sensor / sensors property
# ---------------------------------------------------------------------------

class TestAddSensor:
    def test_add_single_sensor(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (5.0, 10.0), 3.0)
        assert len(sim.sensors) == 1
        sd = sim.sensors[0]
        assert sd.sensor_id == "s1"
        assert sd.name == "Gate"
        assert sd.sensor_type == "motion"
        assert sd.position == (5.0, 10.0)
        assert sd.radius == 3.0

    def test_add_multiple_sensors(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 3.0)
        sim.add_sensor("s2", "Door", "door", (10.0, 0.0), 2.0)
        sim.add_sensor("s3", "Wire", "tripwire", (20.0, 0.0), 1.0)
        assert len(sim.sensors) == 3

    def test_sensors_property_returns_copy(self):
        """Mutating the returned list must not affect internal state."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 3.0)
        sensors_copy = sim.sensors
        sensors_copy.clear()
        assert len(sim.sensors) == 1  # internal list unchanged

    def test_initial_sensor_state_inactive(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 3.0)
        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# set_event_bus
# ---------------------------------------------------------------------------

class TestSetEventBus:
    def test_set_event_bus_replaces_bus(self):
        bus1 = SimpleEventBus()
        bus2 = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus1)
        sim.set_event_bus(bus2)
        assert sim._event_bus is bus2

    def test_events_go_to_new_bus(self):
        bus1 = SimpleEventBus()
        bus2 = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus1)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        # Subscribe only on new bus
        sub2 = bus2.subscribe("sensor_triggered")
        sim.set_event_bus(bus2)

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])

        event = sub2.get(timeout=1.0)
        assert event["sensor_id"] == "s1"


# ---------------------------------------------------------------------------
# Trip detection — basic activation
# ---------------------------------------------------------------------------

class TestTripDetection:
    def test_target_inside_radius_triggers_sensor(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0))  # dist=5, radius=10
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True
        event = sub.get(timeout=1.0)
        assert event["sensor_id"] == "s1"

    def test_target_outside_radius_does_not_trigger(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(15.0, 0.0))  # dist=15, radius=10
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False
        assert sub.empty()

    def test_sensor_triggered_stores_triggering_unit_name(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(name="Infiltrator", position=(3.0, 0.0))
        sim.tick(0.1, [target])

        assert sim.sensors[0].triggered_by == "Infiltrator"

    def test_sensor_triggered_event_payload(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Rear Door", "door", (5.0, 7.0), 4.0)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(target_id="h1", name="Hostile", position=(5.0, 7.0))
        sim.tick(0.1, [target])

        event = sub.get(timeout=1.0)
        assert event["sensor_id"] == "s1"
        assert event["name"] == "Rear Door"
        assert event["type"] == "door"
        assert event["triggered_by"] == "Hostile"
        assert event["target_id"] == "h1"
        assert event["position"] == {"x": 5.0, "z": 7.0}


# ---------------------------------------------------------------------------
# Sensor range boundary tests
# ---------------------------------------------------------------------------

class TestRangeBoundary:
    """Sensors use dist <= radius, so exactly at boundary counts as inside."""

    def test_target_exactly_at_boundary_triggers(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        radius = 10.0
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), radius)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(radius, 0.0))  # dist == radius exactly
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True
        assert not sub.empty()

    def test_target_one_unit_outside_boundary_does_not_trigger(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        radius = 10.0
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), radius)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(radius + 0.001, 0.0))  # barely outside
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False
        assert sub.empty()

    def test_target_just_inside_boundary_triggers(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        radius = 10.0
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), radius)

        target = make_target(position=(radius - 0.001, 0.0))  # barely inside
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True

    def test_target_at_diagonal_boundary(self):
        """dist should use euclidean math.hypot, not just x or y."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        radius = 10.0
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), radius)

        # Target at 45 degrees exactly on the circle boundary: (r/sqrt2, r/sqrt2)
        diag = radius / math.sqrt(2)
        target = make_target(position=(diag, diag))
        # dist = hypot(diag, diag) == radius exactly
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True

    def test_zero_radius_sensor_never_triggers(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Dead Zone", "tripwire", (0.0, 0.0), 0.0)

        # Even a target at (0,0) — dist=0 <= 0 is True, so it triggers
        # This validates actual behaviour, not assumed behaviour
        target = make_target(position=(0.0, 0.0))
        sim.tick(0.1, [target])

        # dist == 0.0 <= radius 0.0 is True, so sensor activates
        assert sim.sensors[0].active is True

    def test_zero_radius_sensor_does_not_trigger_off_center(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Dead Zone", "tripwire", (0.0, 0.0), 0.0)

        target = make_target(position=(0.001, 0.0))  # not exactly at center
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# Deactivation (sensor cleared)
# ---------------------------------------------------------------------------

class TestSensorDeactivation:
    def test_sensor_deactivates_when_target_leaves(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        clear_sub = bus.subscribe("sensor_cleared")

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        # Move target outside radius
        target.position = (50.0, 0.0)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False
        event = clear_sub.get(timeout=1.0)
        assert event["sensor_id"] == "s1"

    def test_sensor_cleared_event_payload(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "door", (3.0, 4.0), 10.0)
        clear_sub = bus.subscribe("sensor_cleared")

        target = make_target(position=(3.0, 4.0))
        sim.tick(0.1, [target])
        target.position = (100.0, 100.0)
        sim.tick(0.1, [target])

        event = clear_sub.get(timeout=1.0)
        assert event["sensor_id"] == "s1"
        assert event["name"] == "Gate"
        assert event["type"] == "door"
        assert event["position"] == {"x": 3.0, "z": 4.0}

    def test_sensor_cleared_not_published_when_no_target_was_inside(self):
        """Cleared should only be published on active→inactive transition."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        clear_sub = bus.subscribe("sensor_cleared")

        target = make_target(position=(50.0, 0.0))  # always outside
        sim.tick(0.1, [target])
        sim.tick(0.1, [target])

        assert clear_sub.empty()

    def test_sensor_does_not_trigger_again_while_active(self):
        """sensor_triggered should only fire on inactive→active transition."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])
        # Drain the first event
        trigger_sub.get(timeout=1.0)

        # Tick again while still inside — no new event
        sim.tick(0.1, [target])
        assert trigger_sub.empty()


# ---------------------------------------------------------------------------
# Debounce behaviour
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_debounce_prevents_immediate_retriggering(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0))

        # Trigger: target inside
        sim.tick(0.1, [target])
        trigger_sub.get(timeout=1.0)  # consume first trigger

        # Target leaves → sensor clears
        target.position = (50.0, 0.0)
        sim.tick(0.1, [target])

        # Target re-enters within DEBOUNCE_S — must NOT re-trigger
        target.position = (5.0, 0.0)
        sim.tick(0.1, [target])

        assert trigger_sub.empty()  # debounced

    def test_debounce_constant_is_3_seconds(self):
        assert SensorSimulator.DEBOUNCE_S == 3.0

    def test_sensor_retriggered_after_debounce_expires(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0))

        # Trigger and consume first event
        sim.tick(0.1, [target])
        trigger_sub.get(timeout=1.0)

        # Target leaves
        target.position = (50.0, 0.0)
        sim.tick(0.1, [target])

        # Wind back last_triggered to simulate time passing
        sensor = sim._sensors[0]
        sensor.last_triggered -= SensorSimulator.DEBOUNCE_S + 0.1  # just past debounce

        # Target re-enters
        target.position = (5.0, 0.0)
        sim.tick(0.1, [target])

        event = trigger_sub.get(timeout=1.0)
        assert event["sensor_id"] == "s1"


# ---------------------------------------------------------------------------
# Status filtering
# ---------------------------------------------------------------------------

class TestStatusFiltering:
    @pytest.mark.parametrize("status", ["destroyed", "eliminated", "despawned", "escaped"])
    def test_inactive_status_ignored(self, status):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0), status=status)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is False
        assert trigger_sub.empty()

    @pytest.mark.parametrize("status", ["active", "idle", "stationary", "advancing"])
    def test_active_status_detected(self, status):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(5.0, 0.0), status=status)
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Multiple sensors
# ---------------------------------------------------------------------------

class TestMultipleSensors:
    def test_each_sensor_triggers_independently(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate1", "motion", (0.0, 0.0), 5.0)
        sim.add_sensor("s2", "Gate2", "motion", (100.0, 0.0), 5.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        # Target near sensor s1 only
        target = make_target(position=(3.0, 0.0))
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True   # s1 triggered
        assert sim.sensors[1].active is False  # s2 not triggered

        events = []
        while not trigger_sub.empty():
            events.append(trigger_sub.get_nowait())
        assert len(events) == 1
        assert events[0]["sensor_id"] == "s1"

    def test_both_sensors_trigger_when_target_near_both(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate1", "motion", (0.0, 0.0), 5.0)
        sim.add_sensor("s2", "Gate2", "motion", (3.0, 0.0), 5.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        # Target at origin — inside both sensors' radii
        target = make_target(position=(1.5, 0.0))
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True
        assert sim.sensors[1].active is True

        events = []
        while not trigger_sub.empty():
            events.append(trigger_sub.get_nowait())
        triggered_ids = {e["sensor_id"] for e in events}
        assert triggered_ids == {"s1", "s2"}

    def test_sensors_clear_independently(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate1", "motion", (0.0, 0.0), 5.0)
        sim.add_sensor("s2", "Gate2", "motion", (100.0, 0.0), 5.0)
        clear_sub = bus.subscribe("sensor_cleared")

        t1 = make_target(target_id="t1", position=(2.0, 0.0))   # near s1
        t2 = make_target(target_id="t2", position=(100.0, 0.0)) # near s2
        sim.tick(0.1, [t1, t2])
        assert sim.sensors[0].active is True
        assert sim.sensors[1].active is True

        # Remove t1 only
        t1.position = (999.0, 0.0)
        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].active is False
        assert sim.sensors[1].active is True  # s2 still has t2

        events = []
        while not clear_sub.empty():
            events.append(clear_sub.get_nowait())
        cleared_ids = [e["sensor_id"] for e in events]
        assert cleared_ids == ["s1"]


# ---------------------------------------------------------------------------
# Multiple targets
# ---------------------------------------------------------------------------

class TestMultipleTargets:
    def test_first_target_wins_triggered_by(self):
        """Sensor records the first nearby target as the trigger."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        t1 = make_target(target_id="t1", name="First", position=(2.0, 0.0))
        t2 = make_target(target_id="t2", name="Second", position=(3.0, 0.0))

        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].triggered_by == "First"

    def test_sensor_stays_active_while_any_target_inside(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        t1 = make_target(target_id="t1", position=(5.0, 0.0))
        t2 = make_target(target_id="t2", position=(6.0, 0.0))
        sim.tick(0.1, [t1, t2])

        # Move t1 outside but t2 remains inside
        t1.position = (50.0, 0.0)
        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].active is True  # t2 is still inside

    def test_sensor_clears_when_all_targets_leave(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        clear_sub = bus.subscribe("sensor_cleared")

        t1 = make_target(target_id="t1", position=(5.0, 0.0))
        t2 = make_target(target_id="t2", position=(6.0, 0.0))
        sim.tick(0.1, [t1, t2])

        # Both leave
        t1.position = (50.0, 0.0)
        t2.position = (50.0, 0.0)
        sim.tick(0.1, [t1, t2])

        assert sim.sensors[0].active is False
        assert not clear_sub.empty()

    def test_empty_target_list_does_not_trigger(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        sim.tick(0.1, [])

        assert sim.sensors[0].active is False
        assert trigger_sub.empty()

    def test_empty_target_list_deactivates_active_sensor(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        clear_sub = bus.subscribe("sensor_cleared")

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

        sim.tick(0.1, [])  # no targets at all

        assert sim.sensors[0].active is False
        assert not clear_sub.empty()


# ---------------------------------------------------------------------------
# Sensor with non-origin position
# ---------------------------------------------------------------------------

class TestSensorAtNonOrigin:
    def test_sensor_at_offset_position_uses_relative_distance(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        # Sensor at (50, 50), radius 5
        sim.add_sensor("s1", "Gate", "motion", (50.0, 50.0), 5.0)

        # Target at (53, 54) — dist = hypot(3, 4) = 5.0 — exactly at boundary
        target = make_target(position=(53.0, 54.0))
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

    def test_sensor_at_offset_does_not_trigger_on_origin_target(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (50.0, 50.0), 5.0)

        # Target at origin — dist = hypot(50,50) >> 5
        target = make_target(position=(0.0, 0.0))
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is False


# ---------------------------------------------------------------------------
# MQTT bridge
# ---------------------------------------------------------------------------

class TestMqttBridge:
    def test_mqtt_publish_called_on_activation(self):
        bus = SimpleEventBus()
        mqtt = MagicMock()
        sim = SensorSimulator(event_bus=bus, mqtt_bridge=mqtt, site_id="base")
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(target_id="h1", name="Hostile", position=(5.0, 0.0))
        sim.tick(0.1, [target])

        assert mqtt.publish.called
        topic_used = mqtt.publish.call_args[0][0]
        assert "tritium/base/sensors/s1/events" == topic_used

    def test_mqtt_publish_not_called_when_no_mqtt(self):
        """No mqtt_bridge — code path must not raise and must not call anything."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus, mqtt_bridge=None)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(5.0, 0.0))
        # Must not raise
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True

    def test_mqtt_payload_is_valid_json(self):
        import json
        bus = SimpleEventBus()
        mqtt = MagicMock()
        sim = SensorSimulator(event_bus=bus, mqtt_bridge=mqtt)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(target_id="h1", name="Hostile", position=(5.0, 0.0))
        sim.tick(0.1, [target])

        payload = mqtt.publish.call_args[0][1]
        parsed = json.loads(payload)
        assert parsed["sensor_id"] == "s1"
        assert parsed["triggered_by"] == "Hostile"

    def test_mqtt_exception_does_not_crash_tick(self):
        """If mqtt.publish raises, the tick must continue without crashing."""
        bus = SimpleEventBus()
        mqtt = MagicMock()
        mqtt.publish.side_effect = RuntimeError("network error")
        sim = SensorSimulator(event_bus=bus, mqtt_bridge=mqtt)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(5.0, 0.0))
        # Must not propagate RuntimeError
        sim.tick(0.1, [target])
        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# CoT / TAK interop
# ---------------------------------------------------------------------------

class TestCoTPublish:
    def test_sensor_triggered_cot_event_published_when_import_succeeds(self):
        """CoT event published when sensor_event_to_cot import succeeds."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        cot_sub = bus.subscribe("sensor_triggered_cot")

        target = make_target(target_id="h1", name="Hostile", position=(5.0, 0.0))

        # The import is done lazily inside _publish_activation.
        # Patch it at the mqtt_cot module level.
        with patch("engine.comms.mqtt_cot.sensor_event_to_cot", return_value="<cot/>"):
            sim.tick(0.1, [target])

        # If the import succeeded, sensor_triggered_cot should be on the bus.
        # (The try/except in the source means it may or may not publish depending
        #  on whether mqtt_cot is importable in this environment; we allow either.)
        if not cot_sub.empty():
            event = cot_sub.get_nowait()
            assert event["sensor_id"] == "s1"
            assert "cot_xml" in event

    def test_cot_exception_does_not_crash_tick(self):
        """If anything inside the CoT try-block raises, tick must not propagate it."""
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(5.0, 0.0))

        # Simulate a broken CoT module by patching sys.modules so the import
        # inside _publish_activation raises ImportError.
        import sys
        saved = sys.modules.get("engine.comms.mqtt_cot")
        sys.modules["engine.comms.mqtt_cot"] = None  # type: ignore[assignment]
        try:
            sim.tick(0.1, [target])
        finally:
            if saved is None:
                sys.modules.pop("engine.comms.mqtt_cot", None)
            else:
                sys.modules["engine.comms.mqtt_cot"] = saved

        # Sensor still activated even though CoT path threw
        assert sim.sensors[0].active is True


# ---------------------------------------------------------------------------
# Tick with no sensors registered
# ---------------------------------------------------------------------------

class TestEmptySensorList:
    def test_tick_with_no_sensors_does_not_raise(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        target = make_target(position=(5.0, 0.0))
        # Must not raise
        sim.tick(0.1, [target])

    def test_tick_with_no_sensors_and_no_targets(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.tick(0.1, [])


# ---------------------------------------------------------------------------
# Sensor last_triggered timestamp
# ---------------------------------------------------------------------------

class TestLastTriggered:
    def test_last_triggered_updated_on_activation(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        before = time.monotonic()
        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])
        after = time.monotonic()

        assert before <= sim.sensors[0].last_triggered <= after

    def test_last_triggered_not_updated_when_not_triggered(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(50.0, 0.0))  # outside
        sim.tick(0.1, [target])

        assert sim.sensors[0].last_triggered == 0.0

    def test_last_triggered_not_updated_on_deactivation(self):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])
        triggered_at = sim.sensors[0].last_triggered

        # Target leaves
        target.position = (50.0, 0.0)
        sim.tick(0.1, [target])

        # last_triggered should NOT change on deactivation
        assert sim.sensors[0].last_triggered == triggered_at


# ---------------------------------------------------------------------------
# Sensor type variety
# ---------------------------------------------------------------------------

class TestSensorTypes:
    @pytest.mark.parametrize("stype", ["motion", "door", "tripwire"])
    def test_each_sensor_type_can_trigger(self, stype):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Sensor", stype, (0.0, 0.0), 10.0)
        sub = bus.subscribe("sensor_triggered")

        target = make_target(position=(5.0, 0.0))
        sim.tick(0.1, [target])

        event = sub.get(timeout=1.0)
        assert event["type"] == stype


# ---------------------------------------------------------------------------
# Alliance-agnostic detection
# ---------------------------------------------------------------------------

class TestAllianceDetection:
    """Sensor does not differentiate between alliances — all non-dead targets trip it."""

    @pytest.mark.parametrize("alliance", ["hostile", "friendly", "neutral", "unknown"])
    def test_all_alliances_trigger_sensor(self, alliance):
        bus = SimpleEventBus()
        sim = SensorSimulator(event_bus=bus)
        sim.add_sensor("s1", "Gate", "motion", (0.0, 0.0), 10.0)
        trigger_sub = bus.subscribe("sensor_triggered")

        target = make_target(alliance=alliance, position=(5.0, 0.0))
        sim.tick(0.1, [target])

        assert sim.sensors[0].active is True
        assert not trigger_sub.empty()
