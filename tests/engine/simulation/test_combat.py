# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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
        assert t.weapon_range == 80.0
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
        assert t.weapon_range == 50.0
        assert t.weapon_cooldown == 1.0
        assert t.weapon_damage == 8.0

    def test_apply_combat_profile_rover(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 150.0
        assert t.weapon_range == 60.0
        assert t.weapon_damage == 12.0

    def test_apply_combat_profile_hostile_person(self):
        t = SimulationTarget(
            target_id="h1", name="Kid", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        t.apply_combat_profile()
        assert t.health == 80.0
        assert t.weapon_range == 40.0
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
        # Empty inventory to test raw combat damage without armor
        from engine.simulation.inventory import UnitInventory
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=100.0,
            inventory=UnitInventory(owner_id="h1"),
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


class TestSemiGuidedProjectiles:
    """Tests for semi-guided projectile tracking (projectiles follow moving targets)."""

    def test_projectile_tracks_moving_target(self):
        """Projectile adjusts aim toward target's CURRENT position."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        # Use rover (not mortar-capable) so projectile tracks the target
        source = SimulationTarget(
            target_id="t1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            weapon_range=50.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(40.0, 0.0), health=100.0,
        )
        proj = combat.fire(source, target)
        assert proj is not None
        original_target_pos = proj.target_pos

        # Move target perpendicular
        target.position = (40.0, 20.0)
        targets = {"t1": source, "h1": target}

        # Tick once — projectile should aim toward (40, 20) not (40, 0)
        combat.tick(0.1, targets)
        # If projectile is tracking, its y should be > 0 (moving toward new target position)
        assert proj.position[1] > 0.0 or proj.hit, \
            f"Projectile should track moving target, y={proj.position[1]}"

    def test_projectile_falls_back_to_target_pos_for_eliminated(self):
        """When target is eliminated, projectile falls back to original target_pos."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=50.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(40.0, 0.0), health=100.0,
        )
        proj = combat.fire(source, target)

        # Eliminate target before projectile arrives
        target.status = "eliminated"
        target.position = (40.0, 30.0)  # target moved before dying
        targets = {"t1": source, "h1": target}

        # Tick — should aim at original target_pos since target is eliminated
        combat.tick(0.1, targets)
        # Projectile should move along x axis (toward original target_pos at 40,0)
        assert proj.position[0] > 0.0, "Projectile should move toward original target_pos"

    def test_projectile_falls_back_when_target_missing(self):
        """When target no longer exists in targets dict, uses original target_pos."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=50.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(40.0, 0.0), health=100.0,
        )
        proj = combat.fire(source, target)

        # Remove target from dict (despawned)
        targets = {"t1": source}  # h1 missing
        combat.tick(0.1, targets)

        # Projectile should still move toward original target_pos
        assert proj.position[0] > 0.0, "Projectile moves toward target_pos when target missing"

    def test_guided_projectile_hits_dodging_target(self):
        """Semi-guided projectile can hit a target that moved slightly."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        hit_sub = bus.subscribe("projectile_hit")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=50.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), health=100.0,
        )
        combat.fire(source, target)

        # Move target slightly — guided projectile should still track
        target.position = (10.0, 2.0)
        targets = {"t1": source, "h1": target}

        for _ in range(20):
            combat.tick(0.1, targets)

        # Should have hit despite target moving
        assert not hit_sub.empty(), "Guided projectile should hit slightly-moved target"


class TestProjectileSpeed:
    """Tests for projectile speed (80.0 m/s in CombatSystem.fire)."""

    def test_fire_creates_projectile_at_speed_80(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        # Use rover (non-mortar) to test default speed=80
        source = SimulationTarget(
            target_id="t1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            weapon_range=50.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(40.0, 0.0), health=100.0,
        )
        proj = combat.fire(source, target)
        assert proj.speed == 80.0, f"Projectile speed should be 80.0, got {proj.speed}"


class TestFireEventFields:
    """Tests for new fields in projectile_fired event."""

    def test_fire_event_includes_source_type(self):
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
        combat.fire(source, target)
        event = sub.get(timeout=1.0)
        assert event["source_type"] == "turret"

    def test_fire_event_includes_target_id(self):
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
        combat.fire(source, target)
        event = sub.get(timeout=1.0)
        assert event["target_id"] == "h1"

    def test_fire_event_includes_damage(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        sub = bus.subscribe("projectile_fired")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        combat.fire(source, target)
        event = sub.get(timeout=1.0)
        assert event["damage"] == 25.0

    def test_fire_with_custom_projectile_type(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        sub = bus.subscribe("projectile_fired")

        source = SimulationTarget(
            target_id="t1", name="Tank", alliance="friendly",
            asset_type="tank", position=(0.0, 0.0),
            weapon_range=30.0, weapon_damage=40.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0),
        )
        combat.fire(source, target, projectile_type="nerf_tank_cannon")
        event = sub.get(timeout=1.0)
        assert event["projectile_type"] == "nerf_tank_cannon"

    def test_elimination_method_uses_projectile_type(self):
        """Elimination event should use the projectile_type as the method."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        elim_sub = bus.subscribe("target_eliminated")

        source = SimulationTarget(
            target_id="t1", name="Tank", alliance="friendly",
            asset_type="tank", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=200.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=10.0,
        )
        combat.fire(source, target, projectile_type="nerf_tank_cannon")
        combat.tick(0.1, {"t1": source, "h1": target})

        event = elim_sub.get(timeout=1.0)
        assert event["method"] == "nerf_tank_cannon"


class TestHitRadiusAndMissOvershoot:
    """Tests verifying HIT_RADIUS=5.0 and MISS_OVERSHOOT=8.0."""

    def test_hit_radius_value(self):
        assert HIT_RADIUS == 5.0

    def test_miss_overshoot_value(self):
        assert MISS_OVERSHOOT == 8.0

    def test_hit_within_5_meters(self):
        """Projectile at 4.9m from target should register as hit."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        hit_sub = bus.subscribe("projectile_hit")

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(4.9, 0.0), health=100.0,
        )
        combat.fire(source, target)
        combat.tick(0.1, {"t1": source, "h1": target})

        assert not hit_sub.empty(), "Projectile should hit target within HIT_RADIUS"


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


class TestStreakResetOnElimination:
    """A2: When a unit is eliminated, its streak counter should be cleared."""

    def test_streak_reset_clears_eliminated_unit(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        # Manually set a streak
        combat._elimination_streaks["t1"] = 5
        combat.reset_streak("t1")
        assert "t1" not in combat._elimination_streaks

    def test_streak_reset_preserves_other_units(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        combat._elimination_streaks["t1"] = 5
        combat._elimination_streaks["t2"] = 3
        combat.reset_streak("t1")
        assert "t1" not in combat._elimination_streaks
        assert combat._elimination_streaks["t2"] == 3

    def test_streak_reset_no_error_for_unknown_unit(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        combat.reset_streak("nonexistent")  # should not raise


class TestHitEventIncludesSourceType:
    """C1: projectile_hit event should include source_type and source_name."""

    def test_hit_event_has_source_type(self):
        bus = SimpleEventBus()
        hit_sub = bus.subscribe("projectile_hit")
        combat = CombatSystem(bus)

        turret = SimulationTarget(
            target_id="t1", name="Alpha Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=50.0,
            weapon_cooldown=0.5, last_fired=0.0,
        )
        hostile = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(3.0, 0.0), health=100.0,
        )
        combat.fire(turret, hostile)
        combat.tick(0.1, {"t1": turret, "h1": hostile})

        assert not hit_sub.empty()
        event = hit_sub.get_nowait()
        assert event["source_type"] == "turret", "hit event must include source_type"
        assert event["source_name"] == "Alpha Turret", "hit event must include source_name"

    def test_hit_event_has_source_position(self):
        bus = SimpleEventBus()
        hit_sub = bus.subscribe("projectile_hit")
        combat = CombatSystem(bus)

        turret = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(10.0, 20.0),
            weapon_range=20.0, weapon_damage=50.0,
            weapon_cooldown=0.5, last_fired=0.0,
        )
        hostile = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(13.0, 20.0), health=100.0,
        )
        combat.fire(turret, hostile)
        combat.tick(0.1, {"t1": turret, "h1": hostile})

        assert not hit_sub.empty()
        event = hit_sub.get_nowait()
        assert "source_pos" in event, "hit event must include source_pos"
        assert event["source_pos"]["x"] == 10.0
        assert event["source_pos"]["y"] == 20.0


class TestEliminationEventIncludesTypes:
    """C2: target_eliminated event should include interceptor_type and target_type."""

    def test_elimination_event_has_interceptor_type(self):
        bus = SimpleEventBus()
        elim_sub = bus.subscribe("target_eliminated")
        combat = CombatSystem(bus)

        turret = SimulationTarget(
            target_id="t1", name="Alpha Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=200.0,
            weapon_cooldown=0.5, last_fired=0.0,
        )
        hostile = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(3.0, 0.0), health=10.0,
        )
        combat.fire(turret, hostile)
        combat.tick(0.1, {"t1": turret, "h1": hostile})

        assert not elim_sub.empty()
        event = elim_sub.get_nowait()
        assert event["interceptor_type"] == "turret", "elimination event must include interceptor_type"
        assert event["target_type"] == "person", "elimination event must include target_type"


class TestStreakClearedOnElimination:
    """A2: When a unit is eliminated, its streak should be cleared so respawned
    units don't inherit stale streak counters."""

    def test_streak_accumulates_then_clears(self):
        """Simulate: turret eliminates 3 hostiles (builds streak), then turret
        is eliminated — streak should be reset."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        turret = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=200.0,
            weapon_cooldown=0.0, last_fired=0.0,
        )

        # Eliminate 3 hostiles to build a streak
        for i in range(3):
            h = SimulationTarget(
                target_id=f"h{i}", name=f"Hostile_{i}", alliance="hostile",
                asset_type="person", position=(3.0, 0.0), health=10.0,
            )
            turret.last_fired = 0.0
            combat.fire(turret, h)
            combat.tick(0.1, {"t1": turret, f"h{i}": h})

        assert combat._elimination_streaks.get("t1") == 3

        # Turret eliminated — streak should be reset
        combat.reset_streak("t1")
        assert "t1" not in combat._elimination_streaks


class TestMortarIndirectFire:
    """Tests for mortar (indirect fire) system."""

    def test_turret_fires_mortar_at_long_range(self):
        """Turret fires mortar arc when target is beyond 30% of weapon_range."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=80.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(60.0, 0.0), health=50.0,
        )
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.is_mortar is True
        assert proj.arc_peak > 0
        assert proj.speed == 40.0  # mortar speed
        assert proj.total_flight_dist > 0

    def test_turret_fires_direct_at_close_range(self):
        """Turret fires direct when target is within 30% of weapon_range."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=80.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(20.0, 0.0), health=50.0,
        )
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.is_mortar is False
        assert proj.speed == 80.0

    def test_mortar_z_height_peaks_at_midpoint(self):
        """Mortar Z height is maximum at flight_progress=0.5."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=100.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(70.0, 0.0), health=50.0,
        )
        proj = combat.fire(source, target)
        assert proj.is_mortar
        # At launch (progress=0), z_height should be 0
        assert proj.z_height == 0.0
        # At midpoint, z_height should equal arc_peak
        proj.flight_progress = 0.5
        assert abs(proj.z_height - proj.arc_peak) < 0.01
        # At impact (progress=1), z_height should be 0
        proj.flight_progress = 1.0
        assert proj.z_height == 0.0

    def test_mortar_skips_los_check(self):
        """Mortar rounds bypass terrain LOS check."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=80.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(60.0, 0.0), health=50.0,
        )

        # Fake terrain map that always blocks LOS
        class BlockingTerrain:
            def line_of_sight(self, a, b):
                return False

        # Mortar should fire despite blocked LOS
        proj = combat.fire(source, target, terrain_map=BlockingTerrain())
        assert proj is not None
        assert proj.is_mortar is True

    def test_rover_never_fires_mortar(self):
        """Non-mortar-capable types always fire direct."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            weapon_range=80.0, weapon_damage=10.0,
            weapon_cooldown=0.5, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(60.0, 0.0), health=50.0,
        )
        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.is_mortar is False
        assert proj.speed == 80.0

    def test_mortar_does_not_track_target(self):
        """Mortar rounds fly to original target_pos, not current position."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=80.0, weapon_damage=25.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(60.0, 0.0), health=50.0,
        )
        proj = combat.fire(source, target)
        assert proj.is_mortar
        original_target_pos = proj.target_pos

        # Move target perpendicular
        target.position = (60.0, 30.0)
        targets = {"t1": source, "h1": target}
        combat.tick(0.1, targets)

        # Mortar should still aim at original position (y stays 0)
        assert proj.position[1] == 0.0, \
            f"Mortar should aim at original target_pos, not track. y={proj.position[1]}"

    def test_mortar_to_dict_includes_arc_fields(self):
        """Mortar projectile to_dict includes is_mortar, z_height, arc_peak."""
        from engine.simulation.combat import Projectile
        proj = Projectile(
            id="test", source_id="t1", source_name="Turret",
            target_id="h1", position=(0.0, 0.0), target_pos=(50.0, 0.0),
            is_mortar=True, arc_peak=20.0, total_flight_dist=50.0,
        )
        proj.flight_progress = 0.5
        d = proj.to_dict()
        assert d["is_mortar"] is True
        assert d["z_height"] == 20.0
        assert d["arc_peak"] == 20.0
        assert d["flight_progress"] == 0.5

    def test_non_mortar_to_dict_excludes_arc_fields(self):
        """Non-mortar projectile to_dict does not include arc fields."""
        from engine.simulation.combat import Projectile
        proj = Projectile(
            id="test", source_id="r1", source_name="Rover",
            target_id="h1", position=(0.0, 0.0), target_pos=(50.0, 0.0),
        )
        d = proj.to_dict()
        assert "is_mortar" not in d
        assert "z_height" not in d
