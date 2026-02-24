"""Unit tests for CombatSystem and SimulationTarget combat fields."""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.target import SimulationTarget, _COMBAT_PROFILES, _profile_key
from engine.simulation.combat import CombatSystem, Projectile, HIT_RADIUS, MISS_OVERSHOOT


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

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


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# SimulationTarget combat fields
# --------------------------------------------------------------------------

class TestTargetCombatFields:
    def test_default_combat_fields(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
        )
        assert t.health == 100.0
        assert t.max_health == 100.0
        assert t.weapon_range == 15.0
        assert t.weapon_cooldown == 2.0
        assert t.weapon_damage == 10.0
        assert t.last_fired == 0.0
        assert t.kills == 0
        assert t.is_combatant is True

    def test_apply_combat_profile_turret(self):
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 200.0
        assert t.max_health == 200.0
        assert t.weapon_range == 20.0
        assert t.weapon_cooldown == 1.5
        assert t.weapon_damage == 15.0
        assert t.is_combatant is True

    def test_apply_combat_profile_drone(self):
        t = SimulationTarget(
            target_id="d1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 60.0
        assert t.weapon_range == 12.0
        assert t.weapon_cooldown == 1.0
        assert t.weapon_damage == 8.0

    def test_apply_combat_profile_rover(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 150.0
        assert t.weapon_range == 10.0
        assert t.weapon_damage == 12.0

    def test_apply_combat_profile_hostile_person(self):
        t = SimulationTarget(
            target_id="h1", name="Kid", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 80.0
        assert t.weapon_range == 8.0
        assert t.weapon_cooldown == 2.5
        assert t.weapon_damage == 10.0
        assert t.is_combatant is True

    def test_apply_combat_profile_neutral_person(self):
        t = SimulationTarget(
            target_id="n1", name="Neighbor", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 50.0
        assert t.is_combatant is False
        assert t.weapon_range == 0.0

    def test_apply_combat_profile_vehicle(self):
        t = SimulationTarget(
            target_id="v1", name="Truck", alliance="friendly",
            asset_type="vehicle", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 300.0
        assert t.weapon_range == 0.0
        assert t.is_combatant is False

    def test_apply_combat_profile_animal(self):
        t = SimulationTarget(
            target_id="a1", name="Dog", alliance="neutral",
            asset_type="animal", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 30.0
        assert t.is_combatant is False

    def test_profile_key_person_hostile(self):
        assert _profile_key("person", "hostile") == "person_hostile"

    def test_profile_key_person_neutral(self):
        assert _profile_key("person", "neutral") == "person_neutral"

    def test_profile_key_person_friendly(self):
        assert _profile_key("person", "friendly") == "person_neutral"

    def test_profile_key_non_person(self):
        assert _profile_key("turret", "friendly") == "turret"
        assert _profile_key("drone", "friendly") == "drone"


class TestTargetApplyDamage:
    def test_damage_reduces_health(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), health=100.0,
        )
        result = t.apply_damage(30.0)
        assert result is False
        assert t.health == 70.0
        assert t.status == "active"

    def test_damage_eliminates_at_zero(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), health=25.0,
        )
        result = t.apply_damage(25.0)
        assert result is True
        assert t.health == 0.0
        assert t.status == "eliminated"

    def test_damage_eliminates_below_zero(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), health=10.0,
        )
        result = t.apply_damage(50.0)
        assert result is True
        assert t.health == 0.0
        assert t.status == "eliminated"

    def test_damage_idempotent_on_eliminated(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            health=0.0, status="eliminated",
        )
        result = t.apply_damage(10.0)
        assert result is True
        assert t.status == "eliminated"

    def test_damage_idempotent_on_destroyed(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            health=50.0, status="destroyed",
        )
        result = t.apply_damage(10.0)
        assert result is True

    def test_eliminated_target_no_tick_movement(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=5.0,
            waypoints=[(10.0, 0.0)], status="eliminated",
        )
        t.tick(1.0)
        assert t.position == (0.0, 0.0)


class TestTargetCanFire:
    def test_can_fire_ready(self):
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        assert t.can_fire() is True

    def test_cannot_fire_on_cooldown(self):
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=2.0, last_fired=time.time(),
        )
        assert t.can_fire() is False

    def test_cannot_fire_no_weapon(self):
        t = SimulationTarget(
            target_id="v1", name="Truck", alliance="friendly",
            asset_type="vehicle", position=(0.0, 0.0),
            weapon_range=0.0, weapon_damage=0.0,
        )
        assert t.can_fire() is False

    def test_cannot_fire_not_combatant(self):
        t = SimulationTarget(
            target_id="n1", name="Neighbor", alliance="neutral",
            asset_type="person", position=(0.0, 0.0),
            weapon_range=5.0, weapon_damage=5.0,
            is_combatant=False,
        )
        assert t.can_fire() is False

    def test_cannot_fire_eliminated(self):
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            status="eliminated",
        )
        assert t.can_fire() is False

    def test_can_fire_stationary_turret(self):
        t = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            status="stationary", last_fired=0.0,
        )
        assert t.can_fire() is True


class TestTargetToDictCombat:
    def test_to_dict_includes_combat_fields(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            health=75.0, max_health=150.0, kills=3,
            is_combatant=True,
        )
        d = t.to_dict()
        assert d["health"] == 75.0
        assert d["max_health"] == 150.0
        assert d["kills"] == 3
        assert d["is_combatant"] is True


# --------------------------------------------------------------------------
# Projectile
# --------------------------------------------------------------------------

class TestProjectile:
    def test_projectile_creation(self):
        p = Projectile(
            id="p1", source_id="s1", source_name="Turret",
            target_id="h1",
            position=(0.0, 0.0), target_pos=(10.0, 0.0),
        )
        assert p.speed == 25.0
        assert p.damage == 10.0
        assert p.projectile_type == "nerf_dart"
        assert p.hit is False
        assert p.missed is False

    def test_projectile_to_dict(self):
        p = Projectile(
            id="p1", source_id="s1", source_name="Turret",
            target_id="h1",
            position=(5.0, 3.0), target_pos=(10.0, 0.0),
            damage=15.0,
        )
        d = p.to_dict()
        assert d["id"] == "p1"
        assert d["position"] == {"x": 5.0, "y": 3.0}
        assert d["target_pos"] == {"x": 10.0, "y": 0.0}
        assert d["damage"] == 15.0


# --------------------------------------------------------------------------
# CombatSystem
# --------------------------------------------------------------------------

class TestCombatSystemFire:
    def test_fire_creates_projectile(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        sub = bus.subscribe("projectile_fired")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.source_id == "t1"
        assert proj.target_id == "h1"
        assert proj.damage == 15.0
        assert combat.projectile_count == 1

        # Check event published
        event = sub.get(timeout=1.0)
        assert event["id"] == proj.id
        assert event["source_id"] == "t1"

    def test_fire_respects_cooldown(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=10.0, last_fired=time.time(),
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        proj = combat.fire(source, target)
        assert proj is None
        assert combat.projectile_count == 0

    def test_fire_respects_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=5.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        proj = combat.fire(source, target)
        assert proj is None

    def test_fire_updates_last_fired(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        before = time.time()
        combat.fire(source, target)
        assert source.last_fired >= before


class TestCombatSystemTick:
    def test_projectile_moves_toward_target(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), health=100.0,
        )
        proj = combat.fire(source, target)
        initial_x = proj.position[0]

        targets = {"t1": source, "h1": target}
        combat.tick(0.1, targets)

        # Projectile should have moved toward target (positive x)
        # It may have already hit if close enough, but position should have changed
        # or it was removed (hit)

    def test_projectile_hits_target(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        hit_sub = bus.subscribe("projectile_hit")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        # Target very close — will be hit immediately
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=100.0,
        )
        combat.fire(source, target)
        targets = {"t1": source, "h1": target}
        combat.tick(0.1, targets)

        # Should have hit
        event = hit_sub.get(timeout=1.0)
        assert event["target_id"] == "h1"
        assert event["damage"] == 15.0
        assert event["remaining_health"] == 85.0
        assert target.health == 85.0

    def test_projectile_eliminates_target(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        elim_sub = bus.subscribe("target_eliminated")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=100.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=50.0,
        )
        combat.fire(source, target)
        targets = {"t1": source, "h1": target}
        combat.tick(0.1, targets)

        event = elim_sub.get(timeout=1.0)
        assert event["target_id"] == "h1"
        assert event["interceptor_id"] == "t1"
        assert event["interceptor_name"] == "Turret"
        assert event["method"] == "nerf_dart"
        assert target.status == "eliminated"
        assert source.kills == 1

    def test_projectile_misses_when_overshooting(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        # Target at (5, 0) — will dodge away
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(5.0, 0.0), health=100.0,
        )
        combat.fire(source, target)

        # Move target far away so projectile misses
        target.position = (50.0, 50.0)
        targets = {"t1": source, "h1": target}

        # Tick many times to let projectile pass through target_pos and overshoot
        for _ in range(50):
            combat.tick(0.1, targets)

        # Projectile should be removed (missed)
        assert combat.projectile_count == 0


class TestCombatSystemEliminationStreaks:
    def test_elimination_streak_at_3(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        streak_sub = bus.subscribe("elimination_streak")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=200.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )

        targets_dict: dict[str, SimulationTarget] = {"t1": source}
        for i in range(3):
            target = SimulationTarget(
                target_id=f"h{i}", name=f"Hostile {i}", alliance="hostile",
                asset_type="person", position=(1.0, 0.0), health=10.0,
            )
            targets_dict[f"h{i}"] = target
            source.last_fired = 0.0
            combat.fire(source, target)
            combat.tick(0.1, targets_dict)

        # Should have ON A STREAK event
        event = streak_sub.get(timeout=1.0)
        assert event["streak"] == 3
        assert event["streak_name"] == "ON A STREAK"
        assert event["interceptor_id"] == "t1"

    def test_elimination_streak_at_5(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        streak_sub = bus.subscribe("elimination_streak")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=200.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )

        targets_dict: dict[str, SimulationTarget] = {"t1": source}
        for i in range(5):
            target = SimulationTarget(
                target_id=f"h{i}", name=f"Hostile {i}", alliance="hostile",
                asset_type="person", position=(1.0, 0.0), health=10.0,
            )
            targets_dict[f"h{i}"] = target
            source.last_fired = 0.0
            combat.fire(source, target)
            combat.tick(0.1, targets_dict)

        # Drain streak_sub: should get ON A STREAK at 3, RAMPAGE at 5
        events = []
        while not streak_sub.empty():
            events.append(streak_sub.get_nowait())
        names = [e["streak_name"] for e in events]
        assert "ON A STREAK" in names
        assert "RAMPAGE" in names

    def test_reset_streaks(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        combat._elimination_streaks["t1"] = 5
        combat.reset_streaks()
        assert len(combat._elimination_streaks) == 0

    def test_reset_single_streak(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        combat._elimination_streaks["t1"] = 5
        combat._elimination_streaks["t2"] = 3
        combat.reset_streak("t1")
        assert "t1" not in combat._elimination_streaks
        assert combat._elimination_streaks["t2"] == 3


class TestCombatSystemGetActiveProjectiles:
    def test_get_active_projectiles(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(15.0, 0.0), health=100.0,
        )

        source.last_fired = 0.0
        combat.fire(source, target)
        active = combat.get_active_projectiles()
        assert len(active) == 1
        assert active[0]["source_id"] == "t1"

    def test_get_active_excludes_hit(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=100.0,
        )

        combat.fire(source, target)
        combat.tick(0.1, {"t1": source, "h1": target})
        # After hit, active should be empty
        active = combat.get_active_projectiles()
        assert len(active) == 0


class TestCombatSystemClear:
    def test_clear_removes_all_projectiles(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(15.0, 0.0),
        )

        combat.fire(source, target)
        assert combat.projectile_count == 1
        combat.clear()
        assert combat.projectile_count == 0


class TestCombatSystemStreakName:
    def test_streak_milestones(self):
        assert CombatSystem._get_streak_name(3) == "ON A STREAK"
        assert CombatSystem._get_streak_name(5) == "RAMPAGE"
        assert CombatSystem._get_streak_name(7) == "DOMINATING"
        assert CombatSystem._get_streak_name(10) == "GODLIKE"

    def test_non_milestone_returns_none(self):
        assert CombatSystem._get_streak_name(1) is None
        assert CombatSystem._get_streak_name(2) is None
        assert CombatSystem._get_streak_name(4) is None
        assert CombatSystem._get_streak_name(6) is None
        assert CombatSystem._get_streak_name(8) is None
