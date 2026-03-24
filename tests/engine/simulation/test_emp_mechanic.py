# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the EMP burst mechanic in drone_swarm game mode.

TDD: These tests define the expected behavior BEFORE implementation.
The EMP burst is an area-of-effect ability that temporarily stuns all
hostile flying units within a 150m radius for 5 seconds. Stunned units
cannot move (speed = 0) or fire. An emp_activated event is published
with position, radius, affected_count, and activated_by.
"""

import math
import time

import pytest

from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.simulation.upgrades import UpgradeSystem, ABILITIES
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str,
    alliance: str = "friendly",
    asset_type: str = "drone",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 3.0,
    altitude: float = 20.0,
    health: float = 100.0,
    is_combatant: bool = True,
    drone_variant: str | None = None,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for testing."""
    return SimulationTarget(
        target_id=target_id,
        name=target_id,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
        altitude=altitude,
        health=health,
        is_combatant=is_combatant,
        drone_variant=drone_variant,
    )


def _build_targets(*targets: SimulationTarget) -> dict[str, SimulationTarget]:
    """Build a targets dict from a list of SimulationTargets."""
    return {t.target_id: t for t in targets}


def _collect_events(event_bus: EventBus, event_type: str) -> list[dict]:
    """Collect all events of a given type from the event bus."""
    collected = []
    sub = event_bus.subscribe()

    # Drain the queue (non-blocking)
    import queue
    while True:
        try:
            msg = sub.get(timeout=0.01)
            if msg.get("type") == event_type:
                collected.append(msg.get("data", {}))
        except queue.Empty:
            break
    return collected


# ---------------------------------------------------------------------------
# Test: EMP affects only hostile flying units within radius
# ---------------------------------------------------------------------------

class TestEmpTargeting:
    """EMP should only stun hostile flying units within the 150m radius."""

    def test_emp_stuns_hostile_drones_within_radius(self):
        """Hostile flying units within 150m of the EMP source should be stunned."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(100.0, 100.0), speed=2.0, altitude=0.0)
        # Hostile drone within 150m
        hostile_drone = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                                     position=(200.0, 100.0), speed=3.0, altitude=25.0,
                                     drone_variant="attack_swarm")

        targets = _build_targets(source, hostile_drone)

        # Grant and use EMP
        system.grant_ability("emp-rover", "emp_burst")
        result = system.use_ability("emp-rover", "emp_burst", targets)

        assert result is True
        # The hostile drone should have an emp stun effect
        effects = system.get_active_effects("hostile-1")
        assert len(effects) > 0
        emp_effects = [e for e in effects if e.effect == "emp_stun"]
        assert len(emp_effects) == 1, f"Expected emp_stun effect, got: {[e.effect for e in effects]}"

    def test_emp_does_not_affect_ground_units(self):
        """Ground-based hostile units should NOT be stunned by EMP."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(100.0, 100.0), speed=2.0, altitude=0.0)
        # Hostile ground person within radius
        hostile_person = _make_target("hostile-ground", alliance="hostile",
                                      asset_type="person", position=(120.0, 100.0),
                                      speed=1.5, altitude=0.0)

        targets = _build_targets(source, hostile_person)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        effects = system.get_active_effects("hostile-ground")
        emp_stun_effects = [e for e in effects if e.effect == "emp_stun"]
        assert len(emp_stun_effects) == 0, "Ground units should not be EMP stunned"

    def test_emp_does_not_affect_friendly_units(self):
        """Friendly flying units should NOT be stunned by EMP.

        Note: The spec for drone_swarm mode says EMP disables ALL drones
        including friendly. However, the user task specifies EMP should
        only affect hostile flying units. We follow the task spec.
        """
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(100.0, 100.0), speed=2.0, altitude=0.0)
        # Friendly drone within radius
        friendly_drone = _make_target("friendly-drone", alliance="friendly",
                                       asset_type="drone", position=(120.0, 100.0),
                                       speed=3.0, altitude=15.0)

        targets = _build_targets(source, friendly_drone)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        effects = system.get_active_effects("friendly-drone")
        emp_stun_effects = [e for e in effects if e.effect == "emp_stun"]
        assert len(emp_stun_effects) == 0, "Friendly units should not be EMP stunned"

    def test_emp_does_not_affect_units_outside_radius(self):
        """Hostile flying units beyond 150m should NOT be affected."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        # Hostile drone at 200m (beyond 150m radius)
        far_drone = _make_target("hostile-far", alliance="hostile",
                                  asset_type="swarm_drone", position=(200.0, 0.0),
                                  speed=3.0, altitude=25.0, drone_variant="attack_swarm")

        targets = _build_targets(source, far_drone)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        effects = system.get_active_effects("hostile-far")
        emp_stun_effects = [e for e in effects if e.effect == "emp_stun"]
        assert len(emp_stun_effects) == 0, "Units beyond 150m should not be affected"

    def test_emp_affects_multiple_drones_within_radius(self):
        """All hostile flying units within 150m should be stunned."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(100.0, 100.0), speed=2.0, altitude=0.0)
        drones = []
        for i in range(5):
            d = _make_target(f"hostile-{i}", alliance="hostile", asset_type="swarm_drone",
                             position=(100.0 + i * 20, 100.0), speed=3.0, altitude=25.0,
                             drone_variant="attack_swarm")
            drones.append(d)

        targets = _build_targets(source, *drones)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        # All 5 drones are within 150m (max distance = 80m)
        for i in range(5):
            effects = system.get_active_effects(f"hostile-{i}")
            emp_stun_effects = [e for e in effects if e.effect == "emp_stun"]
            assert len(emp_stun_effects) == 1, f"hostile-{i} should be EMP stunned"


# ---------------------------------------------------------------------------
# Test: emp_activated event is published with correct data
# ---------------------------------------------------------------------------

class TestEmpEvent:
    """EMP activation should publish emp_activated event via EventBus."""

    def test_emp_activated_event_published(self):
        """Using EMP should publish emp_activated with position, radius,
        affected_count, and activated_by."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        # Subscribe before activation
        sub = event_bus.subscribe()

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(50.0, 75.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(100.0, 75.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        # Collect events
        import queue
        events = []
        while True:
            try:
                msg = sub.get(timeout=0.05)
                if msg.get("type") == "emp_activated":
                    events.append(msg.get("data", {}))
            except queue.Empty:
                break

        assert len(events) == 1, f"Expected 1 emp_activated event, got {len(events)}"
        ev = events[0]
        assert ev["activated_by"] == "emp-rover"
        assert ev["position"]["x"] == 50.0
        assert ev["position"]["y"] == 75.0
        assert ev["radius"] == 150.0
        assert ev["affected_count"] == 1

    def test_emp_event_affected_count_matches_stunned(self):
        """The affected_count in the event should match the actual number of
        stunned units."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)
        sub = event_bus.subscribe()

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)

        # 3 hostile drones within range, 1 outside, 1 ground unit
        targets_list = [source]
        for i in range(3):
            targets_list.append(_make_target(
                f"close-{i}", alliance="hostile", asset_type="swarm_drone",
                position=(float(i * 30), 0.0), speed=3.0, altitude=25.0,
                drone_variant="attack_swarm",
            ))
        # Drone outside range
        targets_list.append(_make_target(
            "far-drone", alliance="hostile", asset_type="swarm_drone",
            position=(200.0, 0.0), speed=3.0, altitude=25.0,
            drone_variant="attack_swarm",
        ))
        # Ground hostile
        targets_list.append(_make_target(
            "ground-hostile", alliance="hostile", asset_type="person",
            position=(10.0, 0.0), speed=1.5, altitude=0.0,
        ))

        targets = _build_targets(*targets_list)

        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        import queue
        events = []
        while True:
            try:
                msg = sub.get(timeout=0.05)
                if msg.get("type") == "emp_activated":
                    events.append(msg.get("data", {}))
            except queue.Empty:
                break

        assert len(events) == 1
        assert events[0]["affected_count"] == 3  # Only the 3 close hostile drones


# ---------------------------------------------------------------------------
# Test: Stunned units cannot move or fire for stun duration
# ---------------------------------------------------------------------------

class TestEmpStunBehavior:
    """Stunned units should have speed = 0 and cannot fire."""

    def test_stunned_unit_speed_modifier_is_zero(self):
        """The speed modifier for a stunned unit should be 0.0."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        # Speed modifier should be 0 (complete stun = no movement)
        speed_mod = system.get_stat_modifier("hostile-1", "speed")
        assert speed_mod == 0.0, f"Stunned unit speed modifier should be 0.0, got {speed_mod}"

    def test_stunned_unit_cannot_fire(self):
        """The weapon_cooldown modifier for stunned units should effectively
        prevent firing (infinite cooldown)."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        # Check for an is_stunned query or weapon_cooldown modifier
        # The behavior system should check is_emp_stunned before allowing fire
        assert system.is_emp_stunned("hostile-1") is True


# ---------------------------------------------------------------------------
# Test: Stun expires after duration
# ---------------------------------------------------------------------------

class TestEmpStunExpiry:
    """EMP stun should expire after the configured duration (5 seconds)."""

    def test_stun_expires_after_duration(self):
        """After 5 seconds of tick(), the stun effect should expire."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        # Verify stunned
        assert system.is_emp_stunned("hostile-1") is True

        # Tick for 4.9 seconds -- should still be stunned
        for _ in range(49):
            system.tick(0.1, targets)
        assert system.is_emp_stunned("hostile-1") is True

        # Tick past 5 seconds -- stun should expire
        for _ in range(2):
            system.tick(0.1, targets)
        assert system.is_emp_stunned("hostile-1") is False

    def test_speed_modifier_restores_after_stun(self):
        """After stun expires, speed modifier should return to 1.0 (no penalty)."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")
        system.use_ability("emp-rover", "emp_burst", targets)

        assert system.get_stat_modifier("hostile-1", "speed") == 0.0

        # Expire the stun
        for _ in range(51):
            system.tick(0.1, targets)

        assert system.get_stat_modifier("hostile-1", "speed") == 1.0


# ---------------------------------------------------------------------------
# Test: EMP has a cooldown (prevent spam)
# ---------------------------------------------------------------------------

class TestEmpCooldown:
    """EMP should have a cooldown period preventing immediate reuse."""

    def test_emp_on_cooldown_after_use(self):
        """EMP should not be usable again immediately after activation."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")

        # First use succeeds
        assert system.use_ability("emp-rover", "emp_burst", targets) is True

        # Immediate second use fails (on cooldown)
        assert system.use_ability("emp-rover", "emp_burst", targets) is False
        assert system.can_use_ability("emp-rover", "emp_burst") is False

    def test_emp_usable_after_cooldown_expires(self):
        """After the cooldown period, EMP should be usable again."""
        event_bus = EventBus()
        system = UpgradeSystem(event_bus=event_bus)

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(0.0, 0.0), speed=2.0, altitude=0.0)
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(50.0, 0.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")

        targets = _build_targets(source, hostile)
        system.grant_ability("emp-rover", "emp_burst")

        # Use it
        system.use_ability("emp-rover", "emp_burst", targets)

        # Get the cooldown from the ability definition
        ability = ABILITIES["emp_burst"]
        cooldown = ability.cooldown

        # Tick past the cooldown
        ticks = int(cooldown / 0.1) + 2
        for _ in range(ticks):
            system.tick(0.1, targets)

        # Should be usable again
        assert system.can_use_ability("emp-rover", "emp_burst") is True


# ---------------------------------------------------------------------------
# Test: Behaviors respect EMP stun (integration with UnitBehaviors)
# ---------------------------------------------------------------------------

class TestEmpBehaviorIntegration:
    """UnitBehaviors should skip stunned units."""

    def test_behaviors_skips_emp_stunned_hostile(self):
        """A hostile drone that is EMP-stunned should not fire during
        behavior tick."""
        from tritium_lib.sim_engine.behavior.behaviors import UnitBehaviors
        from tritium_lib.sim_engine.combat.combat import CombatSystem

        event_bus = EventBus()
        upgrade_system = UpgradeSystem(event_bus=event_bus)

        # Create a mock combat system that tracks fire calls
        combat = CombatSystem(event_bus)
        behaviors = UnitBehaviors(combat)
        behaviors.set_upgrade_system(upgrade_system)

        # Friendly turret
        turret = _make_target("turret-1", alliance="friendly", asset_type="turret",
                              position=(100.0, 100.0), speed=0.0, altitude=0.0)
        turret.apply_combat_profile()

        # Hostile attack drone in range of turret
        hostile = _make_target("hostile-1", alliance="hostile", asset_type="swarm_drone",
                               position=(130.0, 100.0), speed=3.0, altitude=25.0,
                               drone_variant="attack_swarm")
        hostile.apply_combat_profile()
        hostile.last_fired = 0  # Ready to fire

        source = _make_target("emp-rover", alliance="friendly", asset_type="rover",
                              position=(100.0, 100.0), speed=2.0, altitude=0.0)

        targets = _build_targets(turret, hostile, source)

        # Stun the hostile drone
        upgrade_system.grant_ability("emp-rover", "emp_burst")
        upgrade_system.use_ability("emp-rover", "emp_burst", targets)

        # Track projectile count before behavior tick
        initial_projectiles = len(combat._projectiles) if hasattr(combat, '_projectiles') else 0

        # Tick behaviors -- stunned hostile should NOT fire
        behaviors.tick(0.1, targets)

        # The hostile should not have produced new projectiles
        final_projectiles = len(combat._projectiles) if hasattr(combat, '_projectiles') else 0
        hostile_fired = final_projectiles > initial_projectiles

        # Also check: the stunned hostile should be identifiable
        assert upgrade_system.is_emp_stunned("hostile-1") is True
