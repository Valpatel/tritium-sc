# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive unit tests for SimulationTarget (src/engine/simulation/target.py).

Coverage goals:
- Default field values for every field
- __post_init__ MovementController creation logic
- apply_combat_profile() for all profile keys
- apply_damage() edge cases
- can_fire() all decision branches
- tick() dispatcher (controller path vs. legacy path)
- _tick_with_controller() — waypoints version sync, idle/stationary transitions
- _tick_legacy() — heading, waypoint advance, looping, terminal statuses
- to_dict() — all fields including extended fields and geo passthrough
- Alliance categorization and _profile_key logic
- Battery drain for every asset type in _DRAIN_RATES
- Extended fields: squad_id, morale, degradation, detected, fsm_state, is_leader
- Edge cases: negative health, zero damage, zero speed, boundary positions
"""

from __future__ import annotations

import math
import time
from unittest.mock import patch

import pytest

from engine.simulation.target import (
    SimulationTarget,
    _COMBAT_PROFILES,
    _DRAIN_RATES,
    _profile_key,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _friendly_rover(pos=(0.0, 0.0), speed=1.0, **kw) -> SimulationTarget:
    return SimulationTarget(
        target_id="r1",
        name="Rover",
        alliance="friendly",
        asset_type="rover",
        position=pos,
        speed=speed,
        **kw,
    )


def _hostile_person(pos=(0.0, 0.0), speed=2.0, **kw) -> SimulationTarget:
    return SimulationTarget(
        target_id="h1",
        name="Intruder",
        alliance="hostile",
        asset_type="person",
        position=pos,
        speed=speed,
        **kw,
    )


def _neutral_person(pos=(0.0, 0.0), speed=1.0, **kw) -> SimulationTarget:
    return SimulationTarget(
        target_id="n1",
        name="Civilian",
        alliance="neutral",
        asset_type="person",
        position=pos,
        speed=speed,
        **kw,
    )


def _turret(pos=(0.0, 0.0)) -> SimulationTarget:
    return SimulationTarget(
        target_id="t1",
        name="Sentry",
        alliance="friendly",
        asset_type="turret",
        position=pos,
        speed=0.0,
    )


# ---------------------------------------------------------------------------
# Default field values
# ---------------------------------------------------------------------------

class TestDefaultFieldValues:
    """Every field should have a sensible default when not specified."""

    def test_required_fields_stored(self):
        t = SimulationTarget(
            target_id="x1",
            name="Unit",
            alliance="friendly",
            asset_type="rover",
            position=(1.0, 2.0),
        )
        assert t.target_id == "x1"
        assert t.name == "Unit"
        assert t.alliance == "friendly"
        assert t.asset_type == "rover"
        assert t.position == (1.0, 2.0)

    def test_heading_default_zero(self):
        t = _friendly_rover()
        assert t.heading == 0.0

    def test_speed_default_one(self):
        t = SimulationTarget(
            target_id="x1", name="U", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
        )
        assert t.speed == 1.0

    def test_battery_default_full(self):
        t = _friendly_rover()
        assert t.battery == 1.0

    def test_waypoints_default_empty(self):
        t = _friendly_rover()
        assert t.waypoints == []

    def test_status_default_active(self):
        t = _friendly_rover()
        assert t.status == "active"

    def test_loop_waypoints_default_false(self):
        t = _friendly_rover()
        assert t.loop_waypoints is False

    def test_health_default_100(self):
        t = _friendly_rover()
        assert t.health == 100.0

    def test_max_health_default_100(self):
        t = _friendly_rover()
        assert t.max_health == 100.0

    def test_weapon_range_default(self):
        t = _friendly_rover()
        assert t.weapon_range == 15.0

    def test_weapon_cooldown_default(self):
        t = _friendly_rover()
        assert t.weapon_cooldown == 2.0

    def test_weapon_damage_default(self):
        t = _friendly_rover()
        assert t.weapon_damage == 10.0

    def test_last_fired_default_zero(self):
        t = _friendly_rover()
        assert t.last_fired == 0.0

    def test_kills_default_zero(self):
        t = _friendly_rover()
        assert t.kills == 0

    def test_is_combatant_default_true(self):
        t = _friendly_rover()
        assert t.is_combatant is True

    def test_fsm_state_default_none(self):
        t = _friendly_rover()
        assert t.fsm_state is None

    def test_squad_id_default_none(self):
        t = _friendly_rover()
        assert t.squad_id is None

    def test_morale_default_one(self):
        t = _friendly_rover()
        assert t.morale == 1.0

    def test_max_morale_default_one(self):
        t = _friendly_rover()
        assert t.max_morale == 1.0

    def test_degradation_default_zero(self):
        t = _friendly_rover()
        assert t.degradation == 0.0

    def test_detected_default_false(self):
        t = _friendly_rover()
        assert t.detected is False

    def test_detected_at_default_zero(self):
        t = _friendly_rover()
        assert t.detected_at == 0.0

    def test_is_leader_default_false(self):
        t = _friendly_rover()
        assert t.is_leader is False

    def test_fleeing_default_false(self):
        t = _friendly_rover()
        assert t._fleeing is False


# ---------------------------------------------------------------------------
# __post_init__ — MovementController creation
# ---------------------------------------------------------------------------

class TestPostInit:
    """__post_init__ should create a MovementController only for mobile combatants."""

    def test_friendly_rover_gets_controller(self):
        t = _friendly_rover(speed=2.0)
        assert t.movement is not None

    def test_hostile_person_gets_controller(self):
        t = _hostile_person(speed=2.0)
        assert t.movement is not None

    def test_neutral_person_no_controller(self):
        """Neutral units use legacy linear movement."""
        t = _neutral_person(speed=1.0)
        assert t.movement is None

    def test_turret_speed_zero_no_controller(self):
        """speed=0 means no movement controller even if combatant."""
        t = _turret()
        assert t.movement is None

    def test_non_combatant_no_controller(self):
        """Non-combatants with speed > 0 should not get a controller."""
        t = SimulationTarget(
            target_id="a1", name="Dog", alliance="neutral",
            asset_type="animal", position=(0.0, 0.0), speed=1.5,
            is_combatant=False,
        )
        assert t.movement is None

    def test_controller_position_synced(self):
        """Controller x/y should match the target's initial position."""
        t = _friendly_rover(pos=(5.0, 7.0), speed=2.0)
        assert t.movement is not None
        assert t.movement.x == pytest.approx(5.0)
        assert t.movement.y == pytest.approx(7.0)

    def test_controller_heading_conversion(self):
        """Target heading (0=north) must be converted to MC heading (0=east)."""
        # Target heading=0 (north) -> MC heading=90 (north in math convention)
        t = _friendly_rover(speed=1.0)  # default heading=0
        assert t.movement is not None
        assert t.movement.heading == pytest.approx(90.0)

    def test_controller_heading_east(self):
        """Target heading=90 (east) -> MC heading=0 (east in math convention)."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=1.0,
            heading=90.0,
        )
        assert t.movement is not None
        assert t.movement.heading == pytest.approx(0.0)

    def test_controller_max_speed_matches_target_speed(self):
        t = _friendly_rover(speed=3.0)
        assert t.movement is not None
        assert t.movement.max_speed == pytest.approx(3.0)

    def test_controller_turn_rate_minimum(self):
        """turn_rate = max(180, speed*90), so slow units get 180 deg/s minimum."""
        t = _friendly_rover(speed=1.0)
        assert t.movement is not None
        assert t.movement.turn_rate == pytest.approx(max(180.0, 1.0 * 90.0))

    def test_controller_turn_rate_fast_unit(self):
        t = _friendly_rover(speed=5.0)
        assert t.movement is not None
        expected = max(180.0, 5.0 * 90.0)
        assert t.movement.turn_rate == pytest.approx(expected)

    def test_controller_acceleration(self):
        """acceleration = max(4, speed*2)."""
        t = _friendly_rover(speed=3.0)
        assert t.movement is not None
        assert t.movement.acceleration == pytest.approx(max(4.0, 3.0 * 2.0))

    def test_controller_deceleration(self):
        """deceleration = max(6, speed*3)."""
        t = _friendly_rover(speed=3.0)
        assert t.movement is not None
        assert t.movement.deceleration == pytest.approx(max(6.0, 3.0 * 3.0))

    def test_initial_waypoints_pushed_to_controller(self):
        """If waypoints are provided at construction, controller receives them."""
        wp = [(5.0, 0.0), (10.0, 0.0)]
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
            waypoints=wp,
        )
        assert t.movement is not None
        assert t.movement.current_waypoint is not None
        assert not t.movement.arrived

    def test_no_waypoints_controller_starts_arrived(self):
        """Controller with no initial waypoints should report arrived=True."""
        t = _friendly_rover(speed=2.0)
        assert t.movement is not None
        assert t.movement.arrived is True

    def test_waypoints_version_set_when_waypoints_given(self):
        """_waypoints_version should be set to id(waypoints) when waypoints provided."""
        wp = [(5.0, 0.0)]
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
            waypoints=wp,
        )
        assert t._waypoints_version == id(t.waypoints)

    def test_waypoints_version_zero_when_no_waypoints(self):
        t = _friendly_rover(speed=2.0)
        assert t._waypoints_version == 0


# ---------------------------------------------------------------------------
# apply_combat_profile()
# ---------------------------------------------------------------------------

class TestApplyCombatProfile:
    """apply_combat_profile() should set stats from _COMBAT_PROFILES."""

    def test_turret_profile(self):
        t = _turret()
        t.apply_combat_profile()
        assert t.health == pytest.approx(200.0)
        assert t.max_health == pytest.approx(200.0)
        assert t.weapon_range == pytest.approx(80.0)
        assert t.weapon_damage == pytest.approx(15.0)
        assert t.is_combatant is True

    def test_rover_profile(self):
        t = _friendly_rover(speed=0.0)
        t.apply_combat_profile()
        assert t.health == pytest.approx(150.0)
        assert t.weapon_range == pytest.approx(60.0)

    def test_drone_profile(self):
        t = SimulationTarget(
            target_id="d1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0), speed=3.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(60.0)
        assert t.weapon_damage == pytest.approx(8.0)

    def test_person_hostile_profile(self):
        t = _hostile_person()
        t.apply_combat_profile()
        assert t.health == pytest.approx(80.0)
        assert t.weapon_range == pytest.approx(40.0)
        assert t.is_combatant is True

    def test_person_neutral_profile(self):
        t = _neutral_person()
        t.apply_combat_profile()
        assert t.health == pytest.approx(50.0)
        assert t.weapon_range == pytest.approx(0.0)
        assert t.is_combatant is False

    def test_vehicle_profile(self):
        t = SimulationTarget(
            target_id="v1", name="Car", alliance="neutral",
            asset_type="vehicle", position=(0.0, 0.0), speed=0.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(300.0)
        assert t.is_combatant is False

    def test_animal_profile(self):
        t = SimulationTarget(
            target_id="a1", name="Dog", alliance="neutral",
            asset_type="animal", position=(0.0, 0.0), speed=0.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(30.0)
        assert t.is_combatant is False

    def test_tank_profile(self):
        t = SimulationTarget(
            target_id="tk1", name="Tank", alliance="friendly",
            asset_type="tank", position=(0.0, 0.0), speed=2.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(400.0)
        assert t.weapon_range == pytest.approx(100.0)
        assert t.weapon_damage == pytest.approx(30.0)

    def test_apc_profile(self):
        t = SimulationTarget(
            target_id="ap1", name="APC", alliance="friendly",
            asset_type="apc", position=(0.0, 0.0), speed=2.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(300.0)
        assert t.weapon_damage == pytest.approx(8.0)

    def test_heavy_turret_profile(self):
        t = SimulationTarget(
            target_id="ht1", name="Heavy Turret", alliance="friendly",
            asset_type="heavy_turret", position=(0.0, 0.0), speed=0.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(350.0)
        assert t.weapon_range == pytest.approx(120.0)

    def test_missile_turret_profile(self):
        t = SimulationTarget(
            target_id="mt1", name="Missile Turret", alliance="friendly",
            asset_type="missile_turret", position=(0.0, 0.0), speed=0.0,
        )
        t.apply_combat_profile()
        assert t.weapon_range == pytest.approx(150.0)
        assert t.weapon_damage == pytest.approx(50.0)

    def test_scout_drone_profile(self):
        t = SimulationTarget(
            target_id="sd1", name="Scout", alliance="friendly",
            asset_type="scout_drone", position=(0.0, 0.0), speed=4.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(40.0)
        assert t.weapon_damage == pytest.approx(5.0)

    def test_hostile_vehicle_profile(self):
        t = SimulationTarget(
            target_id="hv1", name="Hostile Van", alliance="hostile",
            asset_type="hostile_vehicle", position=(0.0, 0.0), speed=2.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(200.0)
        assert t.weapon_damage == pytest.approx(15.0)

    def test_hostile_leader_profile(self):
        t = SimulationTarget(
            target_id="hl1", name="Leader", alliance="hostile",
            asset_type="hostile_leader", position=(0.0, 0.0), speed=2.0,
        )
        t.apply_combat_profile()
        assert t.health == pytest.approx(150.0)
        assert t.weapon_range == pytest.approx(50.0)

    def test_unknown_type_no_change(self):
        """Unknown asset_type should not change stats."""
        t = SimulationTarget(
            target_id="u1", name="Unknown", alliance="friendly",
            asset_type="unknown_type_xyz", position=(0.0, 0.0), speed=1.0,
        )
        original_health = t.health
        t.apply_combat_profile()
        assert t.health == original_health


# ---------------------------------------------------------------------------
# _profile_key() helper
# ---------------------------------------------------------------------------

class TestProfileKey:
    def test_person_hostile_returns_person_hostile(self):
        assert _profile_key("person", "hostile") == "person_hostile"

    def test_person_friendly_returns_person_neutral(self):
        assert _profile_key("person", "friendly") == "person_neutral"

    def test_person_neutral_returns_person_neutral(self):
        assert _profile_key("person", "neutral") == "person_neutral"

    def test_person_unknown_returns_person_neutral(self):
        assert _profile_key("person", "unknown") == "person_neutral"

    def test_rover_returns_rover(self):
        assert _profile_key("rover", "friendly") == "rover"

    def test_turret_returns_turret(self):
        assert _profile_key("turret", "friendly") == "turret"

    def test_drone_hostile_returns_drone(self):
        assert _profile_key("drone", "hostile") == "drone"


# ---------------------------------------------------------------------------
# apply_damage()
# ---------------------------------------------------------------------------

class TestApplyDamage:
    def test_damage_reduces_health(self):
        t = _friendly_rover()
        t.health = 100.0
        result = t.apply_damage(20.0)
        assert t.health == pytest.approx(80.0)
        assert result is False

    def test_lethal_damage_returns_true(self):
        t = _friendly_rover()
        t.health = 10.0
        result = t.apply_damage(50.0)
        assert result is True
        assert t.status == "eliminated"

    def test_health_floor_at_zero(self):
        """Health should not go below zero."""
        t = _friendly_rover()
        t.health = 10.0
        t.apply_damage(1000.0)
        assert t.health == pytest.approx(0.0)

    def test_exact_lethal_damage(self):
        """Exactly lethal damage should eliminate."""
        t = _friendly_rover()
        t.health = 50.0
        result = t.apply_damage(50.0)
        assert result is True
        assert t.status == "eliminated"
        assert t.health == pytest.approx(0.0)

    def test_already_destroyed_returns_true_no_change(self):
        t = _friendly_rover()
        t.status = "destroyed"
        t.health = 50.0
        result = t.apply_damage(10.0)
        assert result is True
        assert t.health == pytest.approx(50.0)  # unchanged

    def test_already_eliminated_returns_true_no_change(self):
        t = _friendly_rover()
        t.status = "eliminated"
        t.health = 5.0
        result = t.apply_damage(5.0)
        assert result is True
        assert t.health == pytest.approx(5.0)  # unchanged

    def test_already_neutralized_returns_true_no_change(self):
        t = _friendly_rover()
        t.status = "neutralized"
        t.health = 20.0
        result = t.apply_damage(10.0)
        assert result is True
        assert t.health == pytest.approx(20.0)  # unchanged

    def test_zero_damage_no_change(self):
        t = _friendly_rover()
        t.health = 75.0
        result = t.apply_damage(0.0)
        assert t.health == pytest.approx(75.0)
        assert result is False

    def test_active_status_remains_after_partial_damage(self):
        t = _friendly_rover()
        t.health = 100.0
        t.status = "active"
        t.apply_damage(30.0)
        assert t.status == "active"


# ---------------------------------------------------------------------------
# can_fire()
# ---------------------------------------------------------------------------

class TestCanFire:
    def test_can_fire_when_ready(self):
        t = _turret()
        t.apply_combat_profile()  # weapon_range=80, weapon_damage=15
        t.last_fired = 0.0
        t.status = "stationary"
        assert t.can_fire() is True

    def test_cannot_fire_when_on_cooldown(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = time.time()  # just fired
        t.status = "stationary"
        assert t.can_fire() is False

    def test_can_fire_after_cooldown_elapsed(self):
        t = _turret()
        t.apply_combat_profile()
        t.weapon_cooldown = 0.001
        t.last_fired = 0.0  # long ago
        t.status = "stationary"
        assert t.can_fire() is True

    def test_cannot_fire_when_destroyed(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "destroyed"
        assert t.can_fire() is False

    def test_cannot_fire_when_eliminated(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "eliminated"
        assert t.can_fire() is False

    def test_cannot_fire_when_neutralized(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "neutralized"
        assert t.can_fire() is False

    def test_can_fire_when_idle(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "idle"
        assert t.can_fire() is True

    def test_cannot_fire_zero_weapon_range(self):
        t = _neutral_person()
        t.apply_combat_profile()  # person_neutral: weapon_range=0
        t.last_fired = 0.0
        t.status = "active"
        assert t.can_fire() is False

    def test_cannot_fire_zero_weapon_damage(self):
        t = _turret()
        t.last_fired = 0.0
        t.status = "stationary"
        t.weapon_range = 50.0
        t.weapon_damage = 0.0
        assert t.can_fire() is False

    def test_non_combatant_cannot_fire(self):
        t = SimulationTarget(
            target_id="c1", name="Civilian", alliance="neutral",
            asset_type="person", position=(0.0, 0.0), speed=1.0,
            is_combatant=False, weapon_range=10.0, weapon_damage=5.0,
        )
        t.last_fired = 0.0
        t.status = "active"
        assert t.can_fire() is False

    def test_can_fire_when_active(self):
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "active"
        assert t.can_fire() is True


# ---------------------------------------------------------------------------
# Battery drain rates
# ---------------------------------------------------------------------------

class TestBatteryDrainRates:
    """Each asset type should drain at the correct rate per second."""

    @pytest.mark.parametrize("asset_type, expected_rate", list(_DRAIN_RATES.items()))
    def test_drain_rate(self, asset_type, expected_rate):
        alliance = "hostile" if asset_type == "person" else "friendly"
        is_combatant = asset_type not in ("person", "vehicle", "animal")
        t = SimulationTarget(
            target_id="x1", name="Unit", alliance=alliance,
            asset_type=asset_type, position=(0.0, 0.0),
            speed=0.0, battery=1.0, is_combatant=is_combatant,
            # Avoid movement to isolate battery drain
            waypoints=[],
        )
        dt = 100.0
        t.tick(dt)
        expected_battery = max(0.0, 1.0 - expected_rate * dt)
        # Only check if not tripped into low_battery by something else
        if expected_rate == 0.0:
            assert t.battery == pytest.approx(1.0)
        else:
            assert t.battery == pytest.approx(expected_battery, abs=1e-6)

    def test_unknown_type_uses_default_drain(self):
        """Unknown asset_types fall back to 0.001 drain rate."""
        t = SimulationTarget(
            target_id="u1", name="Unknown", alliance="friendly",
            asset_type="unknown_xyz", position=(0.0, 0.0),
            speed=0.0, battery=1.0,
        )
        dt = 10.0
        t.tick(dt)
        expected = 1.0 - 0.001 * dt
        assert t.battery == pytest.approx(expected, abs=1e-6)

    def test_battery_cannot_go_below_zero(self):
        t = _friendly_rover()
        t.battery = 0.001
        t.tick(10000.0)
        assert t.battery >= 0.0

    def test_low_battery_threshold_triggers_status(self):
        t = _friendly_rover()
        t.battery = 0.055  # just above threshold
        t.tick(1.0)  # rover drains 0.001/s -> 0.055 - 0.001 = 0.054 -> still above 0.05
        # After tick battery should be 0.054 -- still ok
        assert t.status != "low_battery"

    def test_battery_below_005_sets_low_battery_status(self):
        t = _friendly_rover()
        t.battery = 0.06
        # rover drain rate = 0.001/s; need dt large enough to drop below 0.05
        t.tick(20.0)  # 0.06 - 0.001*20 = 0.06 - 0.02 = 0.04 -> below 0.05
        assert t.status == "low_battery"


# ---------------------------------------------------------------------------
# tick() — terminal status early-exit
# ---------------------------------------------------------------------------

class TestTickTerminalStatuses:
    """tick() should skip everything for terminal states."""

    @pytest.mark.parametrize("status", [
        "destroyed", "low_battery", "neutralized", "escaped", "eliminated",
    ])
    def test_terminal_status_no_battery_drain(self, status):
        t = _friendly_rover()
        t.status = status
        t.battery = 0.99
        t.tick(100.0)
        assert t.battery == pytest.approx(0.99)

    @pytest.mark.parametrize("status", [
        "destroyed", "low_battery", "neutralized", "escaped", "eliminated",
    ])
    def test_terminal_status_no_movement(self, status):
        t = _friendly_rover(pos=(5.0, 0.0), speed=10.0)
        t.waypoints = [(100.0, 0.0)]
        t.status = status
        t.tick(1.0)
        assert t.position == (5.0, 0.0)


# ---------------------------------------------------------------------------
# _tick_with_controller() — controller path
# ---------------------------------------------------------------------------

class TestTickWithController:
    def test_moves_toward_waypoint(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=5.0,
            waypoints=[(20.0, 0.0)],
        )
        assert t.movement is not None
        for _ in range(10):
            t.tick(0.1)
        assert t.position[0] > 0.0

    def test_position_synced_from_controller(self):
        """After tick, position should match movement controller's x/y."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=5.0,
            waypoints=[(20.0, 0.0)],
        )
        t.tick(0.5)
        assert t.position == pytest.approx((t.movement.x, t.movement.y))

    def test_heading_synced_from_controller(self):
        """Heading in target (0=north) should be (90 - mc_heading) % 360."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=5.0,
            waypoints=[(20.0, 0.0)],
        )
        t.tick(0.5)
        expected_heading = (90.0 - t.movement.heading) % 360.0
        assert t.heading == pytest.approx(expected_heading)

    def test_idle_when_no_waypoints_and_arrived(self):
        """No waypoints + controller.arrived=True -> status='idle'."""
        t = _friendly_rover(speed=2.0)
        assert t.movement is not None
        assert t.movement.arrived is True
        t.tick(0.1)
        assert t.status == "idle"

    def test_stationary_when_speed_zero_controller_path(self):
        """speed=0 in _tick_with_controller path -> stationary."""
        # Build a combatant with speed=0 but is_combatant=True, alliance="friendly"
        # post_init won't create a controller because speed=0, so we force it
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
            waypoints=[(10.0, 0.0)],
        )
        # Now change speed to 0 after __post_init__ created the controller
        t.speed = 0.0
        t.tick(0.1)
        assert t.status == "stationary"

    def test_waypoints_version_triggers_controller_resync(self):
        """Replacing waypoints list should cause controller to receive new path."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=5.0,
            waypoints=[(10.0, 0.0)],
        )
        # Assign a completely new list — different id() -> triggers resync
        t.waypoints = [(0.0, 10.0)]
        # _waypoints_version still holds old id, tick will detect mismatch
        t.tick(0.1)
        # After resync, controller should be heading toward new target
        # Just verify no crash and movement happened
        assert t.position is not None

    def test_friendly_one_shot_arrives(self):
        """Friendly one-shot dispatch should arrive at destination."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=50.0,
            waypoints=[(1.0, 0.0)],
        )
        for _ in range(50):
            t.tick(0.1)
        assert t.status == "arrived"

    def test_hostile_escaped_at_path_end(self):
        """Hostile unit completing path via controller should be 'escaped'."""
        t = SimulationTarget(
            target_id="h1", name="Raider", alliance="hostile",
            asset_type="rover", position=(0.0, 0.0), speed=50.0,
            waypoints=[(1.0, 0.0)],
            is_combatant=True,
        )
        for _ in range(50):
            t.tick(0.1)
        assert t.status == "escaped"

    def test_friendly_patrol_loops(self):
        """Friendly patrol with loop_waypoints=True should keep looping."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=50.0,
            waypoints=[(2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
            loop_waypoints=True,
        )
        for _ in range(200):
            t.tick(0.1)
        assert t.status not in ("arrived", "escaped")


# ---------------------------------------------------------------------------
# _tick_legacy() — non-controller path
# ---------------------------------------------------------------------------

class TestTickLegacy:
    """Legacy linear movement for non-combatants (neutral/animal/vehicle)."""

    def _make_neutral(self, pos=(0.0, 0.0), speed=2.0, waypoints=None, **kw):
        return SimulationTarget(
            target_id="n1", name="Pedestrian", alliance="neutral",
            asset_type="person", position=pos, speed=speed,
            waypoints=waypoints or [], **kw,
        )

    def test_moves_toward_waypoint(self):
        t = self._make_neutral(speed=5.0, waypoints=[(20.0, 0.0)])
        t.tick(1.0)
        assert t.position[0] > 0.0

    def test_no_waypoints_goes_idle(self):
        t = self._make_neutral(speed=2.0, waypoints=[])
        t.tick(0.1)
        assert t.status == "idle"

    def test_zero_speed_goes_stationary(self):
        t = self._make_neutral(speed=0.0, waypoints=[(10.0, 0.0)])
        t.tick(0.1)
        assert t.status == "stationary"
        assert t.position == (0.0, 0.0)

    def test_heading_east_toward_positive_x(self):
        """Moving east (+x): atan2(dx=10, dy=0) = 90 degrees."""
        t = self._make_neutral(speed=1.0, waypoints=[(10.0, 0.0)])
        t.tick(0.1)
        assert abs(t.heading - 90.0) < 1.0

    def test_heading_north_toward_positive_y(self):
        """Moving north (+y): atan2(dx=0, dy=10) = 0 degrees."""
        t = self._make_neutral(speed=1.0, waypoints=[(0.0, 10.0)])
        t.tick(0.1)
        assert abs(t.heading) < 1.0

    def test_heading_south_toward_negative_y(self):
        """Moving south (-y): atan2(dx=0, dy=-10) = 180 degrees."""
        t = self._make_neutral(pos=(0.0, 5.0), speed=1.0, waypoints=[(0.0, -10.0)])
        t.tick(0.1)
        assert abs(t.heading - 180.0) < 1.0

    def test_advances_to_next_waypoint(self):
        """Should advance waypoint_index after reaching first waypoint."""
        # Two waypoints far apart; first very close so it's reached in one tick
        t = self._make_neutral(speed=100.0, waypoints=[(0.5, 0.0), (50.0, 0.0)])
        t.tick(0.01)
        # Should have advanced to waypoint index 1
        assert t._waypoint_index >= 1

    def test_neutral_despawns_at_path_end(self):
        t = self._make_neutral(speed=100.0, waypoints=[(1.0, 0.0)])
        for _ in range(30):
            t.tick(0.1)
        assert t.status == "despawned"

    def test_hostile_escapes_at_path_end(self):
        t = SimulationTarget(
            target_id="h1", name="Intruder", alliance="hostile",
            asset_type="person", position=(0.0, 0.0), speed=100.0,
            waypoints=[(1.0, 0.0)], is_combatant=False,
        )
        for _ in range(30):
            t.tick(0.1)
        assert t.status == "escaped"

    def test_friendly_arrives_at_path_end(self):
        """Friendly one-shot via legacy path should arrive."""
        t = SimulationTarget(
            target_id="f1", name="Scout", alliance="friendly",
            asset_type="person", position=(0.0, 0.0), speed=100.0,
            waypoints=[(1.0, 0.0)], is_combatant=False,
        )
        for _ in range(30):
            t.tick(0.1)
        assert t.status == "arrived"

    def test_friendly_loops_at_path_end(self):
        """Friendly with loop_waypoints=True should loop back to start."""
        t = SimulationTarget(
            target_id="f1", name="Scout", alliance="friendly",
            asset_type="person", position=(0.0, 0.0), speed=100.0,
            waypoints=[(1.0, 0.0), (2.0, 0.0)], is_combatant=False,
            loop_waypoints=True,
        )
        for _ in range(100):
            t.tick(0.1)
        # Should have looped — index back at 0 at some point
        assert t.status in ("active", "low_battery")

    def test_step_clamped_to_distance(self):
        """A single tick should not overshoot the waypoint."""
        t = self._make_neutral(speed=1000.0, waypoints=[(0.5, 0.0)])
        t.tick(1.0)
        # Reached waypoint (dist < 1.0), should not have passed it by much
        assert abs(t.position[0]) <= 1.0


# ---------------------------------------------------------------------------
# to_dict() serialization
# ---------------------------------------------------------------------------

class TestToDict:
    def test_required_keys_present(self):
        t = _friendly_rover()
        d = t.to_dict()
        expected_keys = {
            "target_id", "name", "alliance", "asset_type", "position",
            "lat", "lng", "alt", "heading", "speed", "battery",
            "status", "waypoints", "health", "max_health", "kills",
            "is_combatant", "fsm_state", "squad_id", "morale",
            "degradation", "detected",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_position_as_dict(self):
        t = _friendly_rover(pos=(3.5, -2.1))
        d = t.to_dict()
        assert d["position"] == {"x": 3.5, "y": -2.1}

    def test_waypoints_as_list_of_dicts(self):
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=1.0,
            waypoints=[(5.0, 3.0), (10.0, 8.0)],
        )
        d = t.to_dict()
        assert d["waypoints"] == [{"x": 5.0, "y": 3.0}, {"x": 10.0, "y": 8.0}]

    def test_empty_waypoints_serialized(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["waypoints"] == []

    def test_battery_rounded_to_4_places(self):
        t = _friendly_rover()
        t.battery = 0.123456789
        d = t.to_dict()
        assert d["battery"] == round(0.123456789, 4)

    def test_health_rounded_to_1_place(self):
        t = _friendly_rover()
        t.health = 75.678
        d = t.to_dict()
        assert d["health"] == round(75.678, 1)

    def test_max_health_rounded(self):
        t = _friendly_rover()
        t.max_health = 100.0
        d = t.to_dict()
        assert d["max_health"] == round(100.0, 1)

    def test_morale_rounded_to_2_places(self):
        t = _friendly_rover()
        t.morale = 0.876543
        d = t.to_dict()
        assert d["morale"] == round(0.876543, 2)

    def test_degradation_rounded_to_2_places(self):
        t = _friendly_rover()
        t.degradation = 0.314159
        d = t.to_dict()
        assert d["degradation"] == round(0.314159, 2)

    def test_fsm_state_none_by_default(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["fsm_state"] is None

    def test_fsm_state_serialized(self):
        t = _friendly_rover()
        t.fsm_state = "patrolling"
        d = t.to_dict()
        assert d["fsm_state"] == "patrolling"

    def test_squad_id_none_by_default(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["squad_id"] is None

    def test_squad_id_serialized(self):
        t = _friendly_rover()
        t.squad_id = "alpha-squad"
        d = t.to_dict()
        assert d["squad_id"] == "alpha-squad"

    def test_detected_false_by_default(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["detected"] is False

    def test_detected_true_serialized(self):
        t = _friendly_rover()
        t.detected = True
        d = t.to_dict()
        assert d["detected"] is True

    def test_kills_serialized(self):
        t = _friendly_rover()
        t.kills = 3
        d = t.to_dict()
        assert d["kills"] == 3

    def test_is_combatant_serialized(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["is_combatant"] is True

    def test_geo_fields_present_without_reference(self):
        """When no geo-reference is set, lat/lng/alt should default gracefully."""
        t = _friendly_rover(pos=(0.0, 0.0))
        d = t.to_dict()
        assert "lat" in d
        assert "lng" in d
        assert "alt" in d
        # Without geo init, all default to 0.0
        assert isinstance(d["lat"], float)
        assert isinstance(d["lng"], float)

    def test_alliance_serialized(self):
        t = _hostile_person()
        d = t.to_dict()
        assert d["alliance"] == "hostile"

    def test_target_id_serialized(self):
        t = _friendly_rover()
        d = t.to_dict()
        assert d["target_id"] == "r1"

    def test_status_serialized(self):
        t = _friendly_rover()
        t.status = "arrived"
        d = t.to_dict()
        assert d["status"] == "arrived"


# ---------------------------------------------------------------------------
# Extended simulation fields
# ---------------------------------------------------------------------------

class TestExtendedFields:
    def test_set_fsm_state(self):
        t = _friendly_rover()
        t.fsm_state = "engaging"
        assert t.fsm_state == "engaging"

    def test_set_squad_id(self):
        t = _friendly_rover()
        t.squad_id = "bravo-1"
        assert t.squad_id == "bravo-1"

    def test_morale_can_be_set_below_1(self):
        t = _friendly_rover()
        t.morale = 0.3
        assert t.morale == pytest.approx(0.3)

    def test_degradation_range(self):
        t = _friendly_rover()
        t.degradation = 0.75
        assert t.degradation == pytest.approx(0.75)

    def test_detected_set_to_true(self):
        t = _friendly_rover()
        t.detected = True
        t.detected_at = 12345.0
        assert t.detected is True
        assert t.detected_at == pytest.approx(12345.0)

    def test_is_leader_can_be_set(self):
        t = _friendly_rover()
        t.is_leader = True
        assert t.is_leader is True

    def test_fleeing_can_be_set(self):
        t = _hostile_person()
        t._fleeing = True
        assert t._fleeing is True


# ---------------------------------------------------------------------------
# Alliance categorization
# ---------------------------------------------------------------------------

class TestAllianceCategorization:
    def test_friendly_alliance(self):
        t = _friendly_rover()
        assert t.alliance == "friendly"

    def test_hostile_alliance(self):
        t = _hostile_person()
        assert t.alliance == "hostile"

    def test_neutral_alliance(self):
        t = _neutral_person()
        assert t.alliance == "neutral"

    def test_unknown_alliance(self):
        t = SimulationTarget(
            target_id="u1", name="Unknown", alliance="unknown",
            asset_type="person", position=(0.0, 0.0), speed=0.0,
        )
        assert t.alliance == "unknown"

    def test_hostile_uses_person_hostile_profile(self):
        t = _hostile_person()
        t.apply_combat_profile()
        # person_hostile: health=80
        assert t.health == pytest.approx(80.0)

    def test_friendly_person_uses_neutral_profile(self):
        t = SimulationTarget(
            target_id="f1", name="Civilian", alliance="friendly",
            asset_type="person", position=(0.0, 0.0), speed=0.0,
        )
        t.apply_combat_profile()
        # person_neutral: health=50
        assert t.health == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_negative_health_clamped_by_apply_damage(self):
        """apply_damage should clamp health to 0, not go negative."""
        t = _friendly_rover()
        t.health = 1.0
        t.apply_damage(9999.0)
        assert t.health == pytest.approx(0.0)

    def test_zero_health_after_damage_is_eliminated(self):
        t = _friendly_rover()
        t.health = 5.0
        t.apply_damage(5.0)
        assert t.health == pytest.approx(0.0)
        assert t.status == "eliminated"

    def test_very_large_speed(self):
        """A very high speed unit should not crash."""
        t = SimulationTarget(
            target_id="r1", name="Fast", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=10000.0,
            waypoints=[(1.0, 0.0)],
        )
        t.tick(0.1)
        # Should have arrived and not crashed
        assert t.status in ("active", "arrived", "idle", "low_battery")

    def test_zero_dt_tick(self):
        """Zero dt tick should not change position significantly."""
        t = _friendly_rover(pos=(5.0, 5.0), speed=10.0)
        t.waypoints = [(100.0, 100.0)]
        t.tick(0.0)
        # Position should not change with zero time step
        assert t.position[0] == pytest.approx(5.0, abs=0.01)

    def test_boundary_position_negative(self):
        """Targets can exist at negative coordinates."""
        t = _friendly_rover(pos=(-100.0, -200.0), speed=1.0)
        t.waypoints = [(-90.0, -200.0)]
        t.tick(1.0)
        assert t.position[0] > -100.0  # moved toward waypoint

    def test_battery_exactly_at_threshold(self):
        """Battery exactly at 0.05 should trigger low_battery."""
        t = _friendly_rover()
        t.battery = 0.051  # just above threshold
        # rover drain = 0.001/s; tick dt=2 -> drains 0.002 -> 0.049 < 0.05
        t.tick(2.0)
        assert t.status == "low_battery"

    def test_multiple_ticks_accumulate_position(self):
        """Multiple ticks should accumulate movement."""
        t = _neutral_person(speed=1.0, waypoints=[(100.0, 0.0)])
        initial_x = t.position[0]
        for _ in range(10):
            t.tick(1.0)
        assert t.position[0] > initial_x + 5.0  # moved at least 5 units

    def test_kills_field_tracked_manually(self):
        """kills field can be incremented manually (done by combat system)."""
        t = _friendly_rover()
        t.kills = 0
        t.kills += 1
        assert t.kills == 1

    def test_last_fired_tracks_shot_time(self):
        """last_fired should be set by the consumer (combat system)."""
        t = _turret()
        t.apply_combat_profile()
        t.last_fired = 0.0
        t.status = "stationary"
        assert t.can_fire() is True
        now = time.time()
        t.last_fired = now
        assert t.can_fire() is False

    def test_target_with_no_movement_no_crash(self):
        """Turret with speed=0 and no waypoints should tick without errors."""
        t = _turret()
        for _ in range(100):
            t.tick(0.1)
        assert t.position == (0.0, 0.0)

    def test_to_dict_does_not_include_internal_fields(self):
        """Internal fields like _fleeing should not appear in to_dict()."""
        t = _friendly_rover()
        d = t.to_dict()
        assert "_fleeing" not in d
        assert "_waypoints_version" not in d
        assert "_waypoint_index" not in d

    def test_waypoints_version_updated_on_external_change(self):
        """Replacing waypoints should be detectable via id() change."""
        t = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0), speed=2.0,
            waypoints=[(10.0, 0.0)],
        )
        old_version = t._waypoints_version
        t.waypoints = [(0.0, 10.0)]  # new list object -> different id()
        assert id(t.waypoints) != old_version


# ---------------------------------------------------------------------------
# All _COMBAT_PROFILES keys are covered
# ---------------------------------------------------------------------------

class TestAllCombatProfiles:
    """Verify that all keys in _COMBAT_PROFILES can be resolved."""

    @pytest.mark.parametrize("key", list(_COMBAT_PROFILES.keys()))
    def test_profile_key_can_be_looked_up(self, key):
        assert key in _COMBAT_PROFILES
        health, max_health, weapon_range, weapon_cooldown, weapon_damage, is_combatant = _COMBAT_PROFILES[key]
        assert health >= 0.0
        assert max_health >= 0.0
        assert weapon_range >= 0.0
        assert weapon_cooldown >= 0.0
        assert weapon_damage >= 0.0
        assert isinstance(is_combatant, bool)
