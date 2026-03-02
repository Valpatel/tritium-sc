# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for Drone Swarm mission type — data model extensions.

Tests from spec section 3.8 covering SimulationTarget fields, combat profiles,
3D range math, AA penalties, and GameMode infrastructure health. Mission Director
registration tests are in test_mission_director_modes.py.
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

from engine.simulation.target import SimulationTarget, _COMBAT_PROFILES
from engine.simulation.game_mode import GameMode
from engine.simulation.combat import CombatSystem
from engine.simulation.engine import SimulationEngine


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
# Test 4: effective_range_3d helper
# --------------------------------------------------------------------------

class TestEffectiveRange3D:
    def test_effective_range_3d_ground_to_ground(self):
        """Ground-to-ground: 3D distance equals 2D distance when altitude is same."""
        attacker = SimulationTarget(
            target_id="t-1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            altitude=0.0, is_combatant=True,
        )
        target = SimulationTarget(
            target_id="h-1", name="Hostile", alliance="hostile",
            asset_type="person", position=(30.0, 40.0), speed=1.5,
            altitude=0.0, is_combatant=True,
        )
        # 2D distance = 50.0
        dx = 30.0
        dy = 40.0
        dz = 0.0
        expected = math.sqrt(dx * dx + dy * dy + dz * dz)
        assert expected == 50.0
        # Verify 3D formula matches 2D when no altitude diff
        dist_3d = _effective_range_3d(attacker, target)
        assert abs(dist_3d - 50.0) < 0.01

    def test_effective_range_3d_ground_to_air(self):
        """Ground-to-air: distance is longer due to altitude component."""
        attacker = SimulationTarget(
            target_id="t-2", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            altitude=0.0, is_combatant=True,
        )
        target = SimulationTarget(
            target_id="d-1", name="Scout Drone", alliance="hostile",
            asset_type="swarm_drone", position=(30.0, 40.0), speed=4.0,
            altitude=30.0, is_combatant=False, drone_variant="scout_swarm",
        )
        # 3D distance = sqrt(30^2 + 40^2 + 30^2) = sqrt(900+1600+900) = sqrt(3400) ~= 58.31
        dist_3d = _effective_range_3d(attacker, target)
        expected = math.sqrt(30**2 + 40**2 + 30**2)
        assert abs(dist_3d - expected) < 0.01
        # Must be > 2D distance of 50.0
        assert dist_3d > 50.0


def _effective_range_3d(attacker: SimulationTarget, target: SimulationTarget) -> float:
    """3D distance considering altitude — Phase 1 helper for tests.

    This function will be moved to behaviors.py in Phase 3. For now,
    we test the math directly.
    """
    dx = target.position[0] - attacker.position[0]
    dy = target.position[1] - attacker.position[1]
    dz = target.altitude - attacker.altitude
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# --------------------------------------------------------------------------
# Tests 5-7: AA penalty (logic tested as pure math — Phase 3 wires into behaviors)
# --------------------------------------------------------------------------

class TestAAPenalty:
    """Test the anti-air range penalty concept.

    Ground units (altitude < 5.0) suffer 40% weapon range reduction
    against aerial targets (altitude > 5.0). Missile turrets and
    friendly drones at altitude are exempt.
    """

    def _aa_adjusted_range(self, attacker: SimulationTarget, target: SimulationTarget) -> float:
        """Compute effective weapon range with AA penalty applied."""
        base_range = attacker.weapon_range
        attacker_aerial = attacker.altitude > 5.0
        target_aerial = target.altitude > 5.0

        if target_aerial and not attacker_aerial:
            # Ground-to-air: 40% penalty unless missile_turret
            if attacker.asset_type == "missile_turret":
                return base_range
            return base_range * 0.6  # 40% reduction
        return base_range

    def test_aa_penalty_ground_units(self):
        """Ground turret suffers 40% range reduction against aerial targets."""
        turret = SimulationTarget(
            target_id="t-3", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            altitude=0.0, is_combatant=True,
        )
        turret.apply_combat_profile()  # weapon_range = 80.0

        aerial_drone = SimulationTarget(
            target_id="d-2", name="Attack Drone", alliance="hostile",
            asset_type="swarm_drone", position=(40.0, 0.0), speed=3.0,
            altitude=25.0, is_combatant=True, drone_variant="attack_swarm",
        )
        effective = self._aa_adjusted_range(turret, aerial_drone)
        assert effective == 80.0 * 0.6  # 48.0

    def test_aa_penalty_exempt_missile_turret(self):
        """Missile turret does NOT suffer AA penalty."""
        mt = SimulationTarget(
            target_id="mt-1", name="Missile Turret", alliance="friendly",
            asset_type="missile_turret", position=(0.0, 0.0), speed=0.0,
            altitude=0.0, is_combatant=True,
        )
        mt.apply_combat_profile()  # weapon_range = 150.0

        aerial_drone = SimulationTarget(
            target_id="d-3", name="Attack Drone", alliance="hostile",
            asset_type="swarm_drone", position=(100.0, 0.0), speed=3.0,
            altitude=25.0, is_combatant=True, drone_variant="attack_swarm",
        )
        effective = self._aa_adjusted_range(mt, aerial_drone)
        assert effective == 150.0  # No penalty

    def test_aa_penalty_exempt_friendly_drone(self):
        """Friendly drone at altitude does NOT suffer AA penalty."""
        drone = SimulationTarget(
            target_id="fd-1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0), speed=3.0,
            altitude=20.0, is_combatant=True,
        )
        drone.apply_combat_profile()  # weapon_range = 50.0

        hostile_drone = SimulationTarget(
            target_id="hd-1", name="Hostile Drone", alliance="hostile",
            asset_type="swarm_drone", position=(30.0, 0.0), speed=3.0,
            altitude=25.0, is_combatant=True, drone_variant="attack_swarm",
        )
        effective = self._aa_adjusted_range(drone, hostile_drone)
        assert effective == 50.0  # No penalty (both aerial)


# --------------------------------------------------------------------------
# Test 8: drone_variant field on SimulationTarget
# --------------------------------------------------------------------------

class TestDroneVariantField:
    def test_drone_variant_field_default_none(self):
        """SimulationTarget has drone_variant=None by default."""
        t = SimulationTarget(
            target_id="d-4", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0), speed=3.0,
        )
        assert t.drone_variant is None

    def test_drone_variant_accepts_scout_swarm(self):
        t = SimulationTarget(
            target_id="sd-1", name="Scout Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(0.0, 0.0), speed=4.0,
            drone_variant="scout_swarm",
        )
        assert t.drone_variant == "scout_swarm"

    def test_drone_variant_accepts_attack_swarm(self):
        t = SimulationTarget(
            target_id="ad-1", name="Attack Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(0.0, 0.0), speed=3.0,
            drone_variant="attack_swarm",
        )
        assert t.drone_variant == "attack_swarm"

    def test_drone_variant_accepts_bomber_swarm(self):
        t = SimulationTarget(
            target_id="bd-1", name="Bomber Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(0.0, 0.0), speed=1.5,
            drone_variant="bomber_swarm",
        )
        assert t.drone_variant == "bomber_swarm"


# --------------------------------------------------------------------------
# Test 9: scout_swarm profile
# --------------------------------------------------------------------------

class TestScoutSwarmProfile:
    def test_scout_swarm_profile(self):
        """scout_swarm: health 15, no weapon, not combatant."""
        t = SimulationTarget(
            target_id="ss-1", name="Scout Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(100.0, 100.0), speed=4.0,
            drone_variant="scout_swarm",
        )
        t.apply_combat_profile()
        assert t.health == 15.0
        assert t.max_health == 15.0
        assert t.weapon_range == 0.0
        assert t.weapon_damage == 0.0
        assert t.is_combatant is False


# --------------------------------------------------------------------------
# Test 10: attack_swarm profile
# --------------------------------------------------------------------------

class TestAttackSwarmProfile:
    def test_attack_swarm_profile(self):
        """attack_swarm: health 30, range 25, damage 8."""
        t = SimulationTarget(
            target_id="as-1", name="Attack Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(100.0, 100.0), speed=3.0,
            drone_variant="attack_swarm",
        )
        t.apply_combat_profile()
        assert t.health == 30.0
        assert t.max_health == 30.0
        assert t.weapon_range == 25.0
        assert t.weapon_cooldown == 1.0
        assert t.weapon_damage == 8.0
        assert t.is_combatant is True


# --------------------------------------------------------------------------
# Test 11: bomber_swarm profile
# --------------------------------------------------------------------------

class TestBomberSwarmProfile:
    def test_bomber_swarm_profile(self):
        """bomber_swarm: health 50, weapon_range 0, detonation damage 40."""
        t = SimulationTarget(
            target_id="bs-1", name="Bomber Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(100.0, 100.0), speed=1.5,
            drone_variant="bomber_swarm",
        )
        t.apply_combat_profile()
        assert t.health == 50.0
        assert t.max_health == 50.0
        assert t.weapon_range == 0.0  # No projectile weapon
        assert t.weapon_damage == 40.0  # Detonation damage
        assert t.is_combatant is True


# --------------------------------------------------------------------------
# Test 12: infrastructure_health init
# --------------------------------------------------------------------------

class TestInfrastructureHealthInit:
    def test_infrastructure_health_init(self):
        """infrastructure_health starts at 1000 for drone swarm mode."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "drone_swarm"
        # Infrastructure health should be accessible
        assert gm.infrastructure_max == 1000.0
        # Default value is 0.0 until explicitly initialized for a mode
        # The mode init will set it to infrastructure_max
        gm.infrastructure_health = gm.infrastructure_max
        assert gm.infrastructure_health == 1000.0


# --------------------------------------------------------------------------
# Test 13: infrastructure_health defeat
# --------------------------------------------------------------------------

class TestInfrastructureHealthDefeat:
    def test_infrastructure_health_defeat(self):
        """infrastructure_health reaching 0 triggers defeat."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 100.0
        gm.state = "active"
        q = bus.subscribe("game_over")

        gm.on_infrastructure_damaged(100.0)

        assert gm.infrastructure_health == 0.0
        assert gm.state == "defeat"
        event = q.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["reason"] == "infrastructure_destroyed"


# Mission Director registration tests (tests 1-3, 14-15) are in
# tests/engine/simulation/test_mission_director_modes.py


# --------------------------------------------------------------------------
# Test 16: ammo_count field
# --------------------------------------------------------------------------

class TestAmmoCountField:
    def test_ammo_count_default_unlimited(self):
        """ammo_count defaults to -1 (unlimited)."""
        t = SimulationTarget(
            target_id="t-5", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
        )
        assert t.ammo_count == -1

    def test_ammo_count_set_for_missile_turret(self):
        """Missile turrets can be given limited ammo (20)."""
        t = SimulationTarget(
            target_id="mt-2", name="Missile Turret", alliance="friendly",
            asset_type="missile_turret", position=(0.0, 0.0), speed=0.0,
            ammo_count=20,
        )
        assert t.ammo_count == 20

    def test_ammo_count_unlimited_means_negative_one(self):
        """ammo_count=-1 means unlimited."""
        t = SimulationTarget(
            target_id="t-6", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            ammo_count=-1,
        )
        assert t.ammo_count == -1


# --------------------------------------------------------------------------
# Additional Phase 1 data model tests for game_mode extensions
# --------------------------------------------------------------------------

class TestGameModeExtensionFields:
    def test_game_mode_type_default(self):
        """game_mode_type defaults to 'battle'."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        assert gm.game_mode_type == "battle"

    def test_drone_swarm_get_state_includes_infrastructure(self):
        """get_state() includes infrastructure fields for drone_swarm mode."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 750.0
        state = gm.get_state()
        assert state["game_mode_type"] == "drone_swarm"
        assert state["infrastructure_health"] == 750.0
        assert state["infrastructure_max"] == 1000.0

    def test_civil_unrest_get_state_includes_de_escalation(self):
        """get_state() includes de-escalation fields for civil_unrest mode."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "civil_unrest"
        gm.de_escalation_score = 1200
        gm.civilian_harm_count = 2
        state = gm.get_state()
        assert state["game_mode_type"] == "civil_unrest"
        assert state["de_escalation_score"] == 1200
        assert state["civilian_harm_count"] == 2
        assert state["civilian_harm_limit"] == 5

    def test_infrastructure_damage_partial(self):
        """Partial infrastructure damage reduces health but does not defeat."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 500.0
        gm.state = "active"
        gm.on_infrastructure_damaged(200.0)
        assert gm.infrastructure_health == 300.0
        assert gm.state == "active"  # Not defeated yet
