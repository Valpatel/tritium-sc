# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for InfrastructureHealth — infrastructure damage tracking for drone swarm mode."""

from __future__ import annotations

import math
import queue

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.infrastructure import InfrastructureHealth

pytestmark = pytest.mark.unit


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def infra(event_bus: EventBus) -> InfrastructureHealth:
    return InfrastructureHealth(event_bus=event_bus, max_health=1000.0)


# -- Init ----------------------------------------------------------------------


class TestInfrastructureInit:
    """Health starts at max_health."""

    def test_initial_health(self, infra: InfrastructureHealth) -> None:
        assert infra.get_state()["health"] == 1000.0

    def test_initial_max_health(self, infra: InfrastructureHealth) -> None:
        assert infra.get_state()["max_health"] == 1000.0

    def test_initial_percent(self, infra: InfrastructureHealth) -> None:
        assert infra.get_state()["percent"] == 100.0

    def test_custom_max_health(self, event_bus: EventBus) -> None:
        infra = InfrastructureHealth(event_bus=event_bus, max_health=500.0)
        assert infra.get_state()["health"] == 500.0
        assert infra.get_state()["max_health"] == 500.0

    def test_not_destroyed_initially(self, infra: InfrastructureHealth) -> None:
        assert infra.is_destroyed() is False


# -- apply_damage --------------------------------------------------------------


class TestApplyDamage:
    """apply_damage(100) reduces health by 100."""

    def test_reduces_health(self, infra: InfrastructureHealth) -> None:
        result = infra.apply_damage(100.0, source_id="attacker-1", source_type="attack")
        assert result == 900.0
        assert infra.get_state()["health"] == 900.0

    def test_multiple_damages(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(200.0, source_id="a1", source_type="attack")
        infra.apply_damage(300.0, source_id="a2", source_type="attack")
        assert infra.get_state()["health"] == 500.0

    def test_returns_current_health(self, infra: InfrastructureHealth) -> None:
        h = infra.apply_damage(250.0, source_id="a1", source_type="attack")
        assert h == 750.0


# -- Floor at zero -------------------------------------------------------------


class TestApplyDamageFloor:
    """Can't go below 0."""

    def test_floors_at_zero(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(1500.0, source_id="a1", source_type="nuke")
        assert infra.get_state()["health"] == 0.0

    def test_returns_zero_when_floored(self, infra: InfrastructureHealth) -> None:
        h = infra.apply_damage(2000.0, source_id="a1", source_type="nuke")
        assert h == 0.0

    def test_damage_after_destroyed(self, infra: InfrastructureHealth) -> None:
        """Further damage after reaching 0 stays at 0."""
        infra.apply_damage(1000.0, source_id="a1", source_type="nuke")
        h = infra.apply_damage(100.0, source_id="a2", source_type="attack")
        assert h == 0.0


# -- Event published ----------------------------------------------------------


class TestApplyDamageEvent:
    """EventBus receives infrastructure_damage event."""

    def test_publishes_event(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        infra.apply_damage(40.0, source_id="bomber-3", source_type="bomber_detonation")
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 1

    def test_event_payload(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        infra.apply_damage(40.0, source_id="bomber-3", source_type="bomber_detonation")
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        data = damage_events[0]["data"]
        assert data["health"] == 960.0
        assert data["max_health"] == 1000.0
        assert data["damage"] == 40.0
        assert data["source_id"] == "bomber-3"
        assert data["source_type"] == "bomber_detonation"

    def test_multiple_events(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        infra.apply_damage(100.0, source_id="a1", source_type="attack")
        infra.apply_damage(200.0, source_id="a2", source_type="bomber")
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 2


# -- is_destroyed --------------------------------------------------------------


class TestIsDestroyed:
    """True when health <= 0."""

    def test_not_destroyed_with_health(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(999.0, source_id="a1", source_type="attack")
        assert infra.is_destroyed() is False

    def test_destroyed_at_zero(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(1000.0, source_id="a1", source_type="attack")
        assert infra.is_destroyed() is True

    def test_destroyed_past_zero(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(2000.0, source_id="a1", source_type="attack")
        assert infra.is_destroyed() is True


# -- get_state -----------------------------------------------------------------


class TestGetState:
    """Returns correct dict with health, max_health, percent."""

    def test_full_health_state(self, infra: InfrastructureHealth) -> None:
        state = infra.get_state()
        assert state == {"health": 1000.0, "max_health": 1000.0, "percent": 100.0}

    def test_half_health_state(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(500.0, source_id="a1", source_type="attack")
        state = infra.get_state()
        assert state["health"] == 500.0
        assert state["percent"] == 50.0

    def test_zero_health_state(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(1000.0, source_id="a1", source_type="attack")
        state = infra.get_state()
        assert state["health"] == 0.0
        assert state["percent"] == 0.0


# -- Bomber detonation ---------------------------------------------------------


class TestBomberDetonation:
    """Bomber detonation within 15m of POI applies full damage."""

    def test_near_poi_full_damage(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # Detonate at (55, 50) — 5m away, within 15m radius
        infra.apply_bomber_detonation(
            position=(55.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 900.0

    def test_at_exact_poi_location(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        infra.apply_bomber_detonation(
            position=(50.0, 50.0), damage=200.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 800.0

    def test_at_15m_boundary(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # Exactly 15m away should still count
        infra.apply_bomber_detonation(
            position=(65.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 900.0

    def test_far_from_poi_no_damage(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # Detonate at (100, 100) — ~70m away, outside 15m radius
        infra.apply_bomber_detonation(
            position=(100.0, 100.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 1000.0

    def test_just_outside_15m(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # 15.1m away
        infra.apply_bomber_detonation(
            position=(65.1, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 1000.0

    def test_multiple_poi_buildings(self, infra: InfrastructureHealth) -> None:
        """Detonation near ANY POI building triggers damage."""
        poi_buildings = [(10.0, 10.0), (90.0, 90.0)]
        # Near second POI
        infra.apply_bomber_detonation(
            position=(88.0, 90.0), damage=150.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 850.0

    def test_publishes_event_with_bomber_type(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        poi_buildings = [(50.0, 50.0)]
        infra.apply_bomber_detonation(
            position=(50.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 1
        assert damage_events[0]["data"]["source_type"] == "bomber_detonation"

    def test_no_event_when_far(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        poi_buildings = [(50.0, 50.0)]
        infra.apply_bomber_detonation(
            position=(200.0, 200.0), damage=100.0, poi_buildings=poi_buildings
        )
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 0


# -- Attack fire ---------------------------------------------------------------


class TestAttackFire:
    """Attack fire within 10m of POI applies 25% damage."""

    def test_near_poi_quarter_damage(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # Impact at (55, 50) — 5m away, within 10m radius
        infra.apply_attack_fire(
            position=(55.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        # 25% of 100 = 25 damage
        assert infra.get_state()["health"] == 975.0

    def test_at_exact_poi_location(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(50.0, 50.0), damage=200.0, poi_buildings=poi_buildings
        )
        # 25% of 200 = 50 damage
        assert infra.get_state()["health"] == 950.0

    def test_at_10m_boundary(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(60.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 975.0

    def test_far_from_poi_no_damage(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(100.0, 100.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 1000.0

    def test_just_outside_10m(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(60.1, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        assert infra.get_state()["health"] == 1000.0

    def test_publishes_event_with_attack_fire_type(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(50.0, 50.0), damage=100.0, poi_buildings=poi_buildings
        )
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 1
        assert damage_events[0]["data"]["source_type"] == "attack_fire"

    def test_no_event_when_far(
        self, infra: InfrastructureHealth, event_bus: EventBus
    ) -> None:
        q = event_bus.subscribe()
        poi_buildings = [(50.0, 50.0)]
        infra.apply_attack_fire(
            position=(200.0, 200.0), damage=100.0, poi_buildings=poi_buildings
        )
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        damage_events = [e for e in events if e["type"] == "infrastructure_damage"]
        assert len(damage_events) == 0


# -- Multiple damage sources --------------------------------------------------


class TestMultipleDamageSources:
    """Accumulative damage tracking from multiple sources."""

    def test_accumulative_damage(self, infra: InfrastructureHealth) -> None:
        poi_buildings = [(50.0, 50.0)]
        # Direct damage
        infra.apply_damage(100.0, source_id="a1", source_type="direct")
        # Bomber near POI (full damage)
        infra.apply_bomber_detonation(
            position=(50.0, 50.0), damage=200.0, poi_buildings=poi_buildings
        )
        # Attack fire near POI (25% of 400 = 100)
        infra.apply_attack_fire(
            position=(50.0, 50.0), damage=400.0, poi_buildings=poi_buildings
        )
        # Total: 100 + 200 + 100 = 400 damage
        assert infra.get_state()["health"] == 600.0

    def test_percent_updates_correctly(self, infra: InfrastructureHealth) -> None:
        infra.apply_damage(250.0, source_id="a1", source_type="attack")
        assert infra.get_state()["percent"] == 75.0
        infra.apply_damage(250.0, source_id="a2", source_type="attack")
        assert infra.get_state()["percent"] == 50.0

    def test_empty_poi_list(self, infra: InfrastructureHealth) -> None:
        """No POIs = no damage from proximity methods."""
        infra.apply_bomber_detonation(
            position=(50.0, 50.0), damage=200.0, poi_buildings=[]
        )
        assert infra.get_state()["health"] == 1000.0
        infra.apply_attack_fire(
            position=(50.0, 50.0), damage=200.0, poi_buildings=[]
        )
        assert infra.get_state()["health"] == 1000.0
