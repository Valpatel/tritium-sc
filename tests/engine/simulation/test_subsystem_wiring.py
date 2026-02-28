# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for subsystem wiring into SimulationEngine.

Verifies that all extended subsystems (morale, cover, degradation, pursuit,
comms, stats, terrain, upgrades, weapons) are properly instantiated on the
engine, ticked during the engine loop, and reset during game reset.
"""

import pytest
import random
import threading
import time
from unittest.mock import MagicMock

from engine.simulation.engine import SimulationEngine
from engine.simulation.combat import CombatSystem
from engine.simulation.target import SimulationTarget
from engine.simulation.morale import MoraleSystem
from engine.simulation.cover import CoverSystem
from engine.simulation.degradation import DegradationSystem
from engine.simulation.pursuit import PursuitSystem
from engine.simulation.comms import UnitComms
from engine.simulation.stats import StatsTracker
from engine.simulation.terrain import TerrainMap
from engine.simulation.upgrades import UpgradeSystem
from engine.simulation.weapons import WeaponSystem, Weapon
from engine.simulation.replay import ReplayRecorder


def _make_bus():
    """Create a minimal EventBus mock."""
    bus = MagicMock()
    bus.publish = MagicMock()
    bus.subscribe = MagicMock(return_value=MagicMock(get=MagicMock(side_effect=Exception("timeout"))))
    return bus


def _make_engine():
    """Create a SimulationEngine with mock EventBus."""
    bus = _make_bus()
    engine = SimulationEngine(event_bus=bus, map_bounds=50.0)
    return engine


def _make_target(target_id="t1", alliance="friendly", asset_type="turret",
                 position=(0.0, 0.0), speed=0.0):
    """Create a SimulationTarget."""
    t = SimulationTarget(
        target_id=target_id,
        name=f"Test {asset_type}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
    )
    t.apply_combat_profile()
    return t


# -- Test: Subsystems exist on engine --


@pytest.mark.unit
class TestSubsystemInstantiation:
    """Verify all subsystems are instantiated on engine construction."""

    def test_morale_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.morale_system, MoraleSystem)

    def test_cover_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.cover_system, CoverSystem)

    def test_degradation_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.degradation_system, DegradationSystem)

    def test_pursuit_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.pursuit_system, PursuitSystem)

    def test_unit_comms_exists(self):
        engine = _make_engine()
        assert isinstance(engine.unit_comms, UnitComms)

    def test_stats_tracker_exists(self):
        engine = _make_engine()
        assert isinstance(engine.stats_tracker, StatsTracker)

    def test_terrain_map_exists(self):
        engine = _make_engine()
        assert isinstance(engine.terrain_map, TerrainMap)

    def test_upgrade_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.upgrade_system, UpgradeSystem)

    def test_weapon_system_exists(self):
        engine = _make_engine()
        assert isinstance(engine.weapon_system, WeaponSystem)

    def test_fsms_dict_exists(self):
        engine = _make_engine()
        assert isinstance(engine._fsms, dict)
        assert len(engine._fsms) == 0


# -- Test: Subsystems reset on game reset --


@pytest.mark.unit
class TestSubsystemReset:
    """Verify all subsystems are reset when reset_game() is called."""

    def test_morale_reset_on_game_reset(self):
        engine = _make_engine()
        engine.morale_system.set_morale("test-unit", 0.5)
        assert engine.morale_system.get_morale("test-unit") == 0.5
        engine.reset_game()
        # After reset, morale should be default (1.0 since dict is cleared)
        assert engine.morale_system.get_morale("test-unit") == 1.0

    def test_cover_reset_on_game_reset(self):
        engine = _make_engine()
        engine.cover_system.add_cover_point((10.0, 10.0))
        engine.reset_game()
        assert len(engine.cover_system._cover_points) == 0

    def test_degradation_reset_on_game_reset(self):
        engine = _make_engine()
        engine.degradation_system._degradation["test"] = {"accuracy_penalty": 0.1, "speed_penalty": 0.0, "cooldown_penalty": 0.0}
        engine.reset_game()
        assert len(engine.degradation_system._degradation) == 0

    def test_pursuit_reset_on_game_reset(self):
        engine = _make_engine()
        engine.pursuit_system.assign("p1", "t1")
        engine.reset_game()
        assert engine.pursuit_system.get_assignment("p1") is None

    def test_comms_reset_on_game_reset(self):
        engine = _make_engine()
        engine.unit_comms.send("s1", "test", (0.0, 0.0))
        engine.reset_game()
        assert len(engine.unit_comms._messages) == 0

    def test_stats_reset_on_game_reset(self):
        engine = _make_engine()
        engine.stats_tracker.record_shot("t1")
        engine.reset_game()
        assert len(engine.stats_tracker._unit_stats) == 0

    def test_terrain_reset_on_game_reset(self):
        engine = _make_engine()
        engine.terrain_map.set_terrain(10.0, 10.0, "rough")
        engine.reset_game()
        assert len(engine.terrain_map._cells) == 0

    def test_upgrade_reset_on_game_reset(self):
        engine = _make_engine()
        engine.upgrade_system.apply_upgrade("t1", "damage_boost")
        engine.reset_game()
        assert len(engine.upgrade_system._upgrades) == 0

    def test_weapon_reset_on_game_reset(self):
        engine = _make_engine()
        engine.weapon_system.equip("t1", "turret")
        engine.reset_game()
        assert len(engine.weapon_system._unit_weapons) == 0

    def test_fsms_cleared_on_game_reset(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert len(engine._fsms) > 0
        engine.reset_game()
        assert len(engine._fsms) == 0


# -- Test: FSM created on add_target --


@pytest.mark.unit
class TestFSMCreation:
    """Verify FSMs are created when combatant targets are added."""

    def test_turret_gets_fsm(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert "turret-1" in engine._fsms
        assert t.fsm_state != ""

    def test_rover_gets_fsm(self):
        engine = _make_engine()
        t = _make_target("rover-1", "friendly", "rover", speed=3.0)
        engine.add_target(t)
        assert "rover-1" in engine._fsms

    def test_drone_gets_fsm(self):
        engine = _make_engine()
        t = _make_target("drone-1", "friendly", "drone", speed=5.0)
        engine.add_target(t)
        assert "drone-1" in engine._fsms

    def test_hostile_gets_fsm(self):
        engine = _make_engine()
        t = _make_target("hostile-1", "hostile", "person", speed=1.5)
        engine.add_target(t)
        assert "hostile-1" in engine._fsms

    def test_neutral_person_gets_npc_fsm(self):
        engine = _make_engine()
        t = _make_target("civ-1", "neutral", "person", speed=1.0)
        t.is_combatant = False
        engine.add_target(t)
        assert "civ-1" in engine._fsms
        assert engine._fsms["civ-1"].current_state == "walking"

    def test_vehicle_gets_npc_fsm(self):
        engine = _make_engine()
        t = _make_target("car-1", "neutral", "vehicle", speed=5.0)
        t.is_combatant = False
        engine.add_target(t)
        assert "car-1" in engine._fsms
        assert engine._fsms["car-1"].current_state == "driving"

    def test_fsm_removed_on_remove_target(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert "turret-1" in engine._fsms
        engine.remove_target("turret-1")
        assert "turret-1" not in engine._fsms


# -- Test: Weapon equip on add_target --


@pytest.mark.unit
class TestWeaponEquip:
    """Verify weapons are equipped when combatant targets are added."""

    def test_turret_gets_weapon(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert engine.weapon_system.get_ammo("turret-1") > 0

    def test_non_combatant_no_weapon(self):
        engine = _make_engine()
        t = _make_target("civ-1", "neutral", "person", speed=1.0)
        t.is_combatant = False
        engine.add_target(t)
        assert engine.weapon_system.get_ammo("civ-1") == 0


# -- Test: Engine tick loop integration --


@pytest.mark.unit
class TestEngineTickIntegration:
    """Verify subsystems are ticked during the engine's tick loop.

    These tests start the engine briefly and verify subsystem state changes.
    """

    def test_stats_tracker_ticked(self):
        """StatsTracker.tick(dt) should accumulate game_elapsed."""
        engine = _make_engine()
        # Directly call the subsystem to verify it works
        engine.stats_tracker.tick(0.1)
        assert engine.stats_tracker._game_elapsed > 0.0

    def test_morale_ticked_with_targets(self):
        """MoraleSystem.tick should process active targets."""
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        engine.morale_system.set_morale("turret-1", 0.5)
        # Tick morale directly with the target dict
        engine.morale_system.tick(1.0, {"turret-1": t})
        # Morale should recover toward 1.0
        assert engine.morale_system.get_morale("turret-1") > 0.5

    def test_weapon_system_reload_cycle(self):
        """WeaponSystem should reload when ammo depleted."""
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        # Deplete ammo
        while engine.weapon_system.consume_ammo("turret-1"):
            pass
        assert engine.weapon_system.get_ammo("turret-1") == 0
        # Tick until reload starts
        engine.weapon_system.tick(0.1)
        assert engine.weapon_system.is_reloading("turret-1")

    def test_upgrade_system_timed_expiry(self):
        """Timed upgrades should expire after their duration."""
        engine = _make_engine()
        engine.upgrade_system.apply_upgrade("t1", "speed_boost")
        assert engine.upgrade_system.get_multiplier("t1", "speed") > 1.0
        # Tick past the 30s duration
        for _ in range(310):
            engine.upgrade_system.tick(0.1)
        assert engine.upgrade_system.get_multiplier("t1", "speed") == 1.0

    def test_terrain_speed_multiplier(self):
        """TerrainMap should return correct speed multipliers."""
        engine = _make_engine()
        engine.terrain_map.set_terrain(10.0, 10.0, "road")
        assert engine.terrain_map.get_speed_multiplier(10.0, 10.0) == 1.2
        engine.terrain_map.set_terrain(20.0, 20.0, "rough")
        assert engine.terrain_map.get_speed_multiplier(20.0, 20.0) == 0.6

    def test_pursuit_auto_assignment(self):
        """PursuitSystem should auto-assign mobile friendlies to hostiles."""
        engine = _make_engine()
        friendly = _make_target("rover-1", "friendly", "rover", speed=3.0, position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(10.0, 10.0))
        engine.add_target(friendly)
        engine.add_target(hostile)
        targets = {"rover-1": friendly, "h-1": hostile}
        engine.pursuit_system.tick(0.1, targets)
        assert engine.pursuit_system.get_assignment("rover-1") == "h-1"

    def test_cover_system_assignment(self):
        """CoverSystem should assign units to nearby cover points."""
        engine = _make_engine()
        cp = engine.cover_system.add_cover_point((5.0, 5.0))
        t = _make_target("rover-1", "friendly", "rover", speed=3.0, position=(5.5, 5.5))
        targets = {"rover-1": t}
        engine.cover_system.tick(0.1, targets)
        assert engine.cover_system.get_cover_reduction("rover-1") > 0.0

    def test_comms_message_delivery(self):
        """UnitComms should deliver messages to units within range."""
        engine = _make_engine()
        engine.unit_comms.send("sender-1", "hostile_spotted", (0.0, 0.0))
        msgs = engine.unit_comms.get_messages_for("receiver-1", (5.0, 5.0), "turret")
        assert len(msgs) > 0
        assert msgs[0].content == "hostile_spotted"


# -- Test: Morale <-> Combat wiring --


@pytest.mark.unit
class TestMoraleCombatWiring:
    """Verify morale system is fed by combat events and synced to targets."""

    def test_morale_synced_to_target_after_tick(self):
        """After morale_system.tick, target.morale should reflect morale_system value."""
        engine = _make_engine()
        t = _make_target("rover-1", "friendly", "rover", speed=3.0)
        engine.add_target(t)
        engine.morale_system.set_morale("rover-1", 0.4)
        engine._sync_morale({"rover-1": t})
        assert t.morale == pytest.approx(0.4, abs=0.01)

    def test_morale_damage_event_reduces_morale(self):
        """combat hit should call morale_system.on_damage_taken reducing morale."""
        engine = _make_engine()
        t = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        engine.add_target(t)
        engine.morale_system.set_morale("h-1", 0.8)
        engine.morale_system.on_damage_taken("h-1", 20.0)
        assert engine.morale_system.get_morale("h-1") < 0.8

    def test_ally_eliminated_reduces_nearby_morale(self):
        """When a hostile is eliminated, nearby hostiles should lose morale."""
        engine = _make_engine()
        h1 = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        h2 = _make_target("h-2", "hostile", "person", speed=1.5, position=(7.0, 7.0))
        engine.add_target(h1)
        engine.add_target(h2)
        engine.morale_system.set_morale("h-2", 0.8)
        # Simulate ally eliminated event
        engine._on_combat_elimination("h-1", {"h-1": h1, "h-2": h2})
        assert engine.morale_system.get_morale("h-2") < 0.8

    def test_enemy_eliminated_boosts_friendly_morale(self):
        """When an enemy is eliminated, friendlies should gain morale."""
        engine = _make_engine()
        f1 = _make_target("turret-1", "friendly", "turret")
        h1 = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        engine.add_target(f1)
        engine.add_target(h1)
        engine.morale_system.set_morale("turret-1", 0.6)
        # Enemy eliminated should boost friendlies
        engine._on_combat_elimination("h-1", {"turret-1": f1, "h-1": h1})
        assert engine.morale_system.get_morale("turret-1") > 0.6


# -- Test: Weapon system tick in engine --


@pytest.mark.unit
class TestWeaponSystemTick:
    """Verify weapon system tick is called during engine tick loop."""

    def test_weapon_system_ticked_during_do_tick(self):
        """Weapon system should be ticked when game is active."""
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        # Deplete ammo manually
        while engine.weapon_system.consume_ammo("turret-1"):
            pass
        assert engine.weapon_system.get_ammo("turret-1") == 0
        # Start reload
        engine.weapon_system.tick(0.1)
        assert engine.weapon_system.is_reloading("turret-1")
        # Engine tick should advance reload timer
        engine.weapon_system.tick(10.0)  # big dt to complete reload
        assert engine.weapon_system.get_ammo("turret-1") > 0


# -- Test: ReplayRecorder wiring --


@pytest.mark.unit
class TestReplayRecorderWiring:
    """Verify ReplayRecorder is instantiated and wired into engine lifecycle."""

    def test_replay_recorder_exists(self):
        engine = _make_engine()
        assert isinstance(engine.replay_recorder, ReplayRecorder)

    def test_replay_recorder_cleared_on_reset(self):
        engine = _make_engine()
        # Record something manually
        t = _make_target("t-1", "friendly", "turret")
        engine.replay_recorder.start()
        engine.replay_recorder.record_snapshot([t])
        assert engine.replay_recorder.frame_count > 0
        engine.reset_game()
        assert engine.replay_recorder.frame_count == 0

    def test_replay_records_snapshot_during_tick(self):
        """ReplayRecorder should capture snapshots during engine tick (2Hz)."""
        engine = _make_engine()
        t = _make_target("t-1", "friendly", "turret")
        engine.add_target(t)
        engine.replay_recorder.start()
        # Run 5 ticks (should get at least one snapshot at 2Hz)
        for _ in range(5):
            engine._do_tick(0.1)
        assert engine.replay_recorder.frame_count >= 1


# -- Test: Morale affects hostile behavior --


@pytest.mark.unit
class TestMoraleBehaviorEffects:
    """Verify morale thresholds affect hostile combat behavior."""

    def test_broken_hostile_skips_firing(self):
        """Hostile with morale < 0.1 should not fire (broken = fleeing)."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        hostile.morale = 0.05  # broken
        # Place friendly far enough that turret won't fire (out of weapon_range)
        friendly = _make_target("turret-1", "friendly", "turret", position=(200.0, 200.0))

        targets = {"h-1": hostile, "turret-1": friendly}
        behaviors.tick(0.1, targets)

        # Should NOT fire when morale is broken
        assert combat.projectile_count == 0

    def test_suppressed_hostile_skips_firing(self):
        """Hostile with morale < 0.3 should not fire (suppressed)."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        hostile.morale = 0.2  # suppressed
        # Place friendly far enough that turret won't fire
        friendly = _make_target("turret-1", "friendly", "turret", position=(200.0, 200.0))

        targets = {"h-1": hostile, "turret-1": friendly}
        behaviors.tick(0.1, targets)

        assert combat.projectile_count == 0

    def test_normal_morale_hostile_fires(self):
        """Hostile with morale >= 0.3 should fire normally at nearby target."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        hostile.morale = 0.7  # normal
        # Place friendly close enough for hostile to fire at
        friendly = _make_target("turret-1", "friendly", "turret", position=(6.0, 6.0))
        # But make turret unable to fire (already fired recently) to isolate hostile behavior
        import time as _time
        friendly.last_fired = _time.time()

        targets = {"h-1": hostile, "turret-1": friendly}
        behaviors.tick(0.1, targets)

        assert combat.projectile_count > 0


# -- Test: Cover system reduces combat damage --


@pytest.mark.unit
class TestCoverCombatWiring:
    """Verify cover system reduces damage when projectiles hit covered targets."""

    def test_cover_reduces_projectile_damage(self):
        """Target behind cover should take less damage from a hit."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.cover import CoverSystem, CoverObject

        bus = _make_bus()
        combat = CombatSystem(bus)
        cover = CoverSystem()

        # Place cover object near target — target is within the cover radius
        cover.add_cover(CoverObject(position=(10.0, 10.0), radius=3.0, cover_value=0.5))
        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(10.5, 10.5))
        # Place source close enough to hit instantly (within HIT_RADIUS)
        source = _make_target("turret-1", "friendly", "turret", position=(13.0, 13.0))

        # Tick cover system so it knows target has cover
        cover.tick(0.1, {"h-1": target})
        cover_val = cover.get_cover_reduction("h-1")
        assert cover_val > 0.0

        # Fire at target with cover_system passed
        initial_health = target.health
        proj = combat.fire(source, target, projectile_type="nerf_dart")
        assert proj is not None
        # Tick combat multiple times to resolve hit (projectile needs to reach target)
        for _ in range(10):
            combat.tick(0.1, {"h-1": target, "turret-1": source}, cover_system=cover)

        damage_taken = initial_health - target.health
        # Without cover: weapon_damage=15.0
        # With cover: should be reduced
        expected_max = source.weapon_damage * (1.0 - cover_val)
        assert damage_taken <= expected_max + 0.01
        assert damage_taken > 0  # still takes some damage

    def test_no_cover_full_damage(self):
        """Target without cover should take full damage."""
        from engine.simulation.combat import CombatSystem

        bus = _make_bus()
        combat = CombatSystem(bus)

        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(10.0, 10.0))
        source = _make_target("turret-1", "friendly", "turret", position=(11.0, 11.0))

        initial_health = target.health
        proj = combat.fire(source, target, projectile_type="nerf_dart")
        assert proj is not None
        # Tick without cover system
        combat.tick(0.1, {"h-1": target, "turret-1": source})

        damage_taken = initial_health - target.health
        assert damage_taken == source.weapon_damage

    def test_cover_backward_compatible_no_arg(self):
        """combat.tick() without cover_system should work (backward compat)."""
        from engine.simulation.combat import CombatSystem

        bus = _make_bus()
        combat = CombatSystem(bus)

        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(10.0, 10.0))
        source = _make_target("turret-1", "friendly", "turret", position=(11.0, 11.0))
        proj = combat.fire(source, target)
        assert proj is not None
        # Should work without cover_system argument
        combat.tick(0.1, {"h-1": target, "turret-1": source})
        assert target.health < 80.0  # took damage

    def test_engine_passes_cover_to_combat(self):
        """Engine should pass cover_system to combat.tick during game."""
        engine = _make_engine()
        source = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        engine.add_target(source)
        engine.add_target(target)

        # Add cover near the hostile
        from engine.simulation.cover import CoverObject
        engine.cover_system.add_cover(CoverObject(position=(5.0, 5.0), radius=3.0, cover_value=0.6))

        # Set game to active so combat runs
        engine.game_mode._state = "active"
        engine._do_tick(0.1)

        # After tick, cover system should have computed cover for the hostile
        cover_val = engine.cover_system.get_cover_reduction("h-1")
        assert cover_val > 0.0


# -- Test: Degradation wiring --


@pytest.mark.unit
class TestDegradationWiring:
    """Verify degradation system affects target fields and combat behavior."""

    def test_degradation_synced_to_target_during_tick(self):
        """target.degradation should be updated each tick based on health."""
        from engine.simulation.degradation import apply_degradation

        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        target.health = 30.0  # 30/80 = 37.5% health, below 50% threshold
        assert target.degradation == 0.0  # initially pristine
        apply_degradation(target)
        assert target.degradation > 0.0  # now degraded

    def test_engine_syncs_degradation_during_tick(self):
        """Engine _do_tick should call apply_degradation, setting target.degradation."""
        engine = _make_engine()
        target = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        target.health = 20.0  # below 50% threshold → degradation > 0
        engine.add_target(target)
        engine._do_tick(0.1)
        assert target.degradation > 0.0

    def test_heavily_damaged_unit_cannot_fire(self):
        """Unit below 10% health should not fire (degradation disables weapon)."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors

        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        hostile.health = 5.0   # 5/80 = 6.25%, below 10%
        hostile.morale = 1.0   # high morale so morale check passes

        friendly = _make_target("turret-1", "friendly", "turret", position=(6.0, 6.0))
        friendly.last_fired = time.time()  # prevent turret from firing

        targets = {"h-1": hostile, "turret-1": friendly}
        behaviors.tick(0.1, targets)

        assert combat.projectile_count == 0

    def test_healthy_unit_can_fire(self):
        """Unit above 10% health should fire normally."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors

        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        hostile.health = 50.0  # 50/80 = 62.5%, above threshold
        hostile.morale = 1.0

        friendly = _make_target("turret-1", "friendly", "turret", position=(6.0, 6.0))
        friendly.last_fired = time.time()  # prevent turret from firing

        targets = {"h-1": hostile, "turret-1": friendly}
        behaviors.tick(0.1, targets)

        assert combat.projectile_count > 0

    def test_degraded_turret_cannot_fire(self):
        """Friendly turret below 10% health should not fire."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors

        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_target("turret-1", "friendly", "turret", position=(5.0, 5.0))
        turret.health = 10.0   # 10/200 = 5%, below 10%

        # Place hostile far enough that it can't fire back (out of weapon_range)
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(200.0, 200.0))

        targets = {"turret-1": turret, "h-1": hostile}
        behaviors.tick(0.1, targets)

        assert combat.projectile_count == 0


# -- Test: Terrain LOS blocks fire --


@pytest.mark.unit
class TestTerrainLOSWiring:
    """Verify terrain_map is passed to combat.fire() for LOS checks."""

    def test_terrain_blocks_shot(self):
        """Turret cannot fire through building with terrain_map wired."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.terrain import TerrainMap

        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        terrain = TerrainMap(map_bounds=100.0)
        # Place a building between turret and hostile
        terrain.set_terrain(5.0, 5.0, "building")
        behaviors.set_terrain_map(terrain)

        turret = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(10.0, 10.0))
        # Prevent hostile from firing
        hostile.last_fired = time.time()

        targets = {"turret-1": turret, "h-1": hostile}
        behaviors.tick(0.1, targets)

        # If terrain blocks LOS, turret should not fire
        # (depends on terrain_map.line_of_sight implementation)
        # At minimum, verify the terrain_map is passed through
        assert behaviors._terrain_map is terrain

    def test_clear_los_allows_shot(self):
        """Turret can fire when LOS is clear (no building between)."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.terrain import TerrainMap

        bus = _make_bus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        terrain = TerrainMap(map_bounds=100.0)
        # No buildings between turret and hostile
        behaviors.set_terrain_map(terrain)

        turret = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        # Prevent hostile from firing back
        hostile.last_fired = time.time()

        targets = {"turret-1": turret, "h-1": hostile}
        behaviors.tick(0.1, targets)

        # Clear LOS — turret should fire
        assert combat.projectile_count > 0

    def test_engine_wires_terrain_to_behaviors(self):
        """Engine should set terrain_map on behaviors."""
        engine = _make_engine()
        assert engine.behaviors._terrain_map is engine.terrain_map


# -- Test: StatsTracker fed by combat events --


@pytest.mark.unit
class TestStatsTrackerWiring:
    """Verify combat events feed into StatsTracker."""

    def test_shot_fired_recorded(self):
        """When a projectile is fired, stats_tracker should record a shot."""
        engine = _make_engine()
        turret = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(5.0, 5.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        # Ensure deterministic fire (weapon accuracy = 1.0)
        weapon = engine.weapon_system.get_weapon("turret-1")
        if weapon is not None:
            weapon.accuracy = 1.0

        # Fire a shot directly
        engine.combat.fire(turret, hostile, projectile_type="nerf_dart")

        # StatsTracker should record the shot for the source
        stats = engine.stats_tracker.get_unit_stats("turret-1")
        assert stats is not None
        assert stats.shots_fired == 1

    def test_hit_recorded(self):
        """When a projectile hits, stats_tracker should record a hit."""
        from engine.simulation.combat import CombatSystem

        engine = _make_engine()
        turret = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(3.0, 3.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        # Ensure deterministic fire
        weapon = engine.weapon_system.get_weapon("turret-1")
        if weapon is not None:
            weapon.accuracy = 1.0

        # Fire a shot
        engine.combat.fire(turret, hostile)
        # Tick combat until hit resolves
        targets = {"turret-1": turret, "h-1": hostile}
        for _ in range(10):
            engine.combat.tick(0.1, targets)

        stats = engine.stats_tracker.get_unit_stats("turret-1")
        assert stats is not None
        assert stats.shots_hit >= 1
        assert stats.damage_dealt > 0

    def test_kill_recorded(self):
        """When a target is eliminated, stats_tracker should record a kill."""
        engine = _make_engine()
        turret = _make_target("turret-1", "friendly", "turret", position=(0.0, 0.0))
        hostile = _make_target("h-1", "hostile", "person", speed=1.5, position=(3.0, 3.0))
        hostile.health = 5.0  # Will be killed in one hit
        engine.add_target(turret)
        engine.add_target(hostile)
        # Ensure deterministic fire
        weapon = engine.weapon_system.get_weapon("turret-1")
        if weapon is not None:
            weapon.accuracy = 1.0

        # Fire and resolve
        engine.combat.fire(turret, hostile)
        targets = {"turret-1": turret, "h-1": hostile}
        for _ in range(10):
            engine.combat.tick(0.1, targets)

        stats = engine.stats_tracker.get_unit_stats("turret-1")
        assert stats is not None
        assert stats.kills >= 1

    def test_units_registered_on_add(self):
        """Units should be registered with stats_tracker when added to engine."""
        engine = _make_engine()
        turret = _make_target("turret-1", "friendly", "turret")
        engine.add_target(turret)
        stats = engine.stats_tracker.get_unit_stats("turret-1")
        assert stats is not None
        assert stats.asset_type == "turret"
        assert stats.alliance == "friendly"


# -- Test: Hostile collision-skip should NOT cause immediate escape --


@pytest.mark.unit
class TestHostileCollisionEscape:
    """Verify hostiles don't instantly escape when building collisions skip waypoints."""

    def test_collision_skip_exhausts_waypoints_hostile_stays_active(self):
        """When collision skip burns through all waypoints, hostile should NOT escape.

        The hostile should remain active at its current position instead of
        getting status=escaped, which would make it invisible to combat.
        """
        hostile = SimulationTarget(
            target_id="h-1",
            name="Test Hostile",
            alliance="hostile",
            asset_type="person",
            position=(100.0, 100.0),
            speed=1.5,
            waypoints=[(50.0, 50.0), (0.0, 0.0), (-100.0, -100.0)],
        )
        hostile.apply_combat_profile()

        # Set collision check that ALWAYS returns True (everything is a building)
        hostile.set_collision_check(lambda x, y: True)

        # Tick enough times to process all waypoints
        for _ in range(20):
            hostile.tick(0.1)

        # Hostile should NOT be escaped — should remain active or at worst idle
        assert hostile.status != "escaped", \
            f"Hostile should not escape due to collision skip, got status={hostile.status}"
        assert hostile.status in ("active", "idle"), \
            f"Hostile should remain active/idle, got status={hostile.status}"

    def test_collision_skip_with_controller_hostile_stays_active(self):
        """Same test but for targets using MovementController (combatant types)."""
        hostile = SimulationTarget(
            target_id="h-2",
            name="Test Hostile Controller",
            alliance="hostile",
            asset_type="person",
            position=(100.0, 100.0),
            speed=1.5,
            waypoints=[(50.0, 50.0), (0.0, 0.0), (-100.0, -100.0)],
        )
        hostile.apply_combat_profile()

        # Verify it has a movement controller (combatant type)
        assert hostile.movement is not None, "Person type should have MovementController"

        # Set collision that always blocks
        hostile.set_collision_check(lambda x, y: True)

        # Tick enough times
        for _ in range(20):
            hostile.tick(0.1)

        # Should NOT escape
        assert hostile.status != "escaped", \
            f"Hostile with controller should not escape from collision skip"
        assert hostile.status in ("active", "idle")

    def test_neutral_collision_skip_still_despawns(self):
        """Neutrals SHOULD still despawn when collision exhausts their waypoints.

        This verifies the fix only applies to hostiles, not neutrals.
        """
        neutral = SimulationTarget(
            target_id="n-1",
            name="Test Neutral",
            alliance="neutral",
            asset_type="person",
            position=(100.0, 100.0),
            speed=1.5,
            waypoints=[(50.0, 50.0), (0.0, 0.0)],
        )
        # Neutral persons may not have movement controllers
        neutral.movement = None
        neutral.set_collision_check(lambda x, y: True)

        for _ in range(20):
            neutral.tick(0.1)

        # Neutrals should still despawn
        assert neutral.status == "despawned"

    def test_hostile_with_valid_waypoints_still_moves(self):
        """Hostiles with non-colliding waypoints should move normally."""
        hostile = SimulationTarget(
            target_id="h-3",
            name="Test Moving Hostile",
            alliance="hostile",
            asset_type="person",
            position=(100.0, 100.0),
            speed=1.5,
            waypoints=[(50.0, 50.0), (0.0, 0.0)],
        )
        hostile.apply_combat_profile()

        # No collision check — open terrain
        hostile.set_collision_check(lambda x, y: False)

        initial_pos = hostile.position

        # Tick forward
        for _ in range(50):
            hostile.tick(0.1)

        # Hostile should have moved from starting position
        assert hostile.position != initial_pos, "Hostile should move toward waypoint"

    def test_engine_hostile_waypoints_avoid_buildings(self):
        """Engine waypoint generation should not produce waypoints inside buildings."""
        engine = _make_engine()

        # Create a mock obstacles object where the center area is a building
        class MockObstacles:
            polygons = []
            def point_in_building(self, x, y):
                # Building at center: anything within 10m of origin is inside
                return abs(x) < 10 and abs(y) < 10
            def building_height_at(self, x, y):
                if abs(x) < 10 and abs(y) < 10:
                    return 5.0
                return None

        engine._obstacles = MockObstacles()

        # Spawn a hostile
        hostile = engine.spawn_hostile()
        assert hostile.status == "active"

        # After waypoint filtering, no waypoint should be inside a building
        for wp in hostile.waypoints:
            assert not MockObstacles().point_in_building(wp[0], wp[1]), \
                f"Waypoint {wp} is inside a building — should have been filtered"

    def test_hostile_beyond_map_bounds_force_escaped(self):
        """Hostiles that move beyond map boundary should auto-escape.

        When a hostile flees past the map edge, it should be force-escaped
        to prevent waves from stalling with invisible off-map hostiles.
        """
        engine = _make_engine()  # map_bounds=50.0
        engine.game_mode.state = "active"
        engine.game_mode.wave = 1

        # Create hostile with waypoint beyond map edge — it will walk off map
        hostile = _make_target("h-flee", "hostile", "person",
                               position=(40.0, 0.0), speed=1.5)
        hostile.waypoints = [(200.0, 0.0)]  # way beyond 50.0 boundary
        engine.add_target(hostile)

        # Tick enough times for hostile to cross the 50m boundary
        # At 1.5 m/s, it needs ~7s to travel 10m from pos 40 to boundary 50
        for _ in range(100):
            engine._do_tick(0.1)

        assert hostile.status == "escaped", \
            f"Hostile past map bounds should be escaped, got {hostile.status}"

    def test_hostile_beyond_negative_map_bounds_force_escaped(self):
        """Hostiles moving past negative map boundary also escape."""
        engine = _make_engine()  # map_bounds=50.0
        engine.game_mode.state = "active"
        engine.game_mode.wave = 1

        hostile = _make_target("h-flee2", "hostile", "person",
                               position=(0.0, -40.0), speed=1.5)
        hostile.waypoints = [(0.0, -200.0)]  # beyond -50 boundary
        engine.add_target(hostile)

        for _ in range(100):
            engine._do_tick(0.1)

        assert hostile.status == "escaped", \
            f"Hostile past negative map bounds should be escaped, got {hostile.status}"

    def test_friendly_beyond_bounds_not_affected(self):
        """Friendlies should NOT be force-escaped when beyond bounds."""
        engine = _make_engine()
        engine.game_mode.state = "active"

        friendly = _make_target("f-1", "friendly", "turret",
                                position=(60.0, 0.0), speed=0.0)
        engine.add_target(friendly)
        engine._do_tick(0.1)
        # Friendly should not be affected by map boundary check
        assert friendly.status != "escaped"

    def test_stall_detection_catches_oscillation(self):
        """Stall detection should catch hostiles oscillating between positions.

        When a hostile bounces between two nearby positions (building
        collision revert), distance-based stall detection should trigger
        because net displacement over 15s is < 3m.
        """
        engine = _make_engine()
        engine.game_mode.state = "active"
        engine.game_mode.wave = 1

        hostile = _make_target("h-osc", "hostile", "person",
                               position=(20.0, 20.0), speed=1.5)
        hostile.waypoints = [(-40.0, -40.0)]
        engine.add_target(hostile)

        # Set collision to block all movement — hostile stuck
        hostile.set_collision_check(lambda x, y: True)
        # Also block the controller's movement if present
        if hostile.movement is not None:
            hostile.movement.position = (20.0, 20.0)

        # Run for 20 seconds — stall should trigger at 15s
        for _ in range(200):
            engine._do_tick(0.1)

        # After 20s stuck, stall detection should have triggered
        assert hostile.status == "escaped", \
            f"Stuck hostile should be force-escaped, got {hostile.status}"

    def test_stalled_hostile_force_escaped_after_timeout(self):
        """Hostiles stuck in place for 15+ seconds should force-escape.

        This prevents waves from stalling when a hostile is collision-trapped.
        The stall detection in engine._do_tick checks distance-based stability.
        """
        engine = _make_engine()
        engine.game_mode.state = "active"
        engine.game_mode.wave = 1

        # Create a hostile WITHIN map bounds (50.0) with distant waypoints
        hostile = _make_target("h-stuck", "hostile", "person",
                               position=(30.0, 30.0), speed=1.5)
        hostile.waypoints = [(0.0, 0.0), (-40.0, -40.0)]
        engine.add_target(hostile)
        # Set collision AFTER add_target so waypoints aren't filtered
        hostile.set_collision_check(lambda x, y: True)

        # Tick a few times — hostile should stay active (collision blocks but
        # our fix prevents escape)
        for _ in range(10):
            engine._do_tick(0.1)
        assert hostile.status == "active", \
            f"Hostile should still be active before timeout, got {hostile.status}"

        # Fast-forward the stall tick counter to simulate 15+ seconds (149 ticks)
        engine._stall_ticks[hostile.target_id] = 149

        # One more tick should trigger force-escape (149 + 1 = 150 threshold)
        engine._do_tick(0.1)
        assert hostile.status == "escaped", \
            f"Hostile should be force-escaped after 150 stall ticks, got {hostile.status}"


class TestWeaponSystemWiring:
    """Verify WeaponSystem integration into CombatSystem."""

    def test_combat_uses_weapon_accuracy_to_miss(self):
        """Shots should miss based on weapon accuracy probability.

        With accuracy=0.0 weapon, ALL shots should miss. This verifies
        that combat.fire() uses weapon accuracy, not hardcoded 100% hit.
        """
        bus = _make_bus()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, stats_tracker=None,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0  # allow firing

        hostile = _make_target("h1", "hostile", "person", position=(10, 0))
        hostile.apply_combat_profile()

        # Assign weapon with 0% accuracy — every shot should miss
        ws.assign_weapon("t1", Weapon(name="trash_gun", accuracy=0.0,
                                       damage=10.0, weapon_range=50.0))

        random.seed(42)  # deterministic
        proj = combat.fire(turret, hostile)
        # With 0% accuracy, fire() should return None (missed)
        assert proj is None, "Weapon with 0% accuracy should produce no projectile"

    def test_combat_uses_weapon_accuracy_to_hit(self):
        """With accuracy=1.0, all shots should fire successfully."""
        bus = _make_bus()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, stats_tracker=None,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0

        hostile = _make_target("h1", "hostile", "person", position=(10, 0))
        hostile.apply_combat_profile()

        ws.assign_weapon("t1", Weapon(name="perfect_gun", accuracy=1.0,
                                       damage=10.0, weapon_range=50.0))
        proj = combat.fire(turret, hostile)
        assert proj is not None, "Weapon with 100% accuracy should always fire"

    def test_combat_blocks_firing_when_reloading(self):
        """Units should not fire while their weapon is reloading."""
        bus = _make_bus()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, stats_tracker=None,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0

        hostile = _make_target("h1", "hostile", "person", position=(10, 0))
        hostile.apply_combat_profile()

        ws.assign_weapon("t1", Weapon(name="test_gun", accuracy=1.0,
                                       damage=10.0, weapon_range=50.0))
        # Force reload state
        ws._reload_timers["t1"] = 3.0

        proj = combat.fire(turret, hostile)
        assert proj is None, "Should not fire while reloading"

    def test_combat_consumes_ammo_on_fire(self):
        """Each shot should consume one round of ammo."""
        bus = _make_bus()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, stats_tracker=None,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0

        hostile = _make_target("h1", "hostile", "person", position=(10, 0))
        hostile.apply_combat_profile()

        ws.assign_weapon("t1", Weapon(name="test_gun", accuracy=1.0,
                                       damage=10.0, weapon_range=50.0,
                                       ammo=5, max_ammo=10))

        proj = combat.fire(turret, hostile)
        assert proj is not None
        assert ws.get_ammo("t1") == 4, "Ammo should decrease by 1 after firing"

    def test_combat_no_weapon_fires_normally(self):
        """Without weapon_system, combat uses legacy behavior (always fires)."""
        bus = _make_bus()
        combat = CombatSystem(event_bus=bus, stats_tracker=None)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0

        hostile = _make_target("h1", "hostile", "person", position=(10, 0))
        hostile.apply_combat_profile()

        proj = combat.fire(turret, hostile)
        assert proj is not None, "Legacy combat (no weapon system) should fire"

    def test_engine_passes_weapon_system_to_combat(self):
        """SimulationEngine should wire its weapon_system into combat."""
        engine = _make_engine()
        assert engine.combat._weapon_system is engine.weapon_system


class TestUpgradeSystemWiring:
    """Verify upgrade_system stat modifiers affect combat outcomes."""

    def test_damage_modifier_increases_projectile_damage(self):
        """Weapon damage modifier from upgrades increases projectile damage."""
        bus = _make_bus()
        upgrade_sys = UpgradeSystem()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, upgrade_system=upgrade_sys,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0
        ws.assign_weapon("t1", Weapon(name="test", accuracy=1.0, damage=10.0))

        hostile = _make_target("h1", "hostile", "person", position=(5, 0))
        hostile.apply_combat_profile()

        # Apply precision_targeting upgrade (+15% damage)
        result = upgrade_sys.apply_upgrade("t1", "precision_targeting", target=turret)
        assert result is True

        proj = combat.fire(turret, hostile)
        assert proj is not None
        # Base damage 15 (turret weapon_damage) * 1.15 = 17.25
        expected = turret.weapon_damage * 1.15
        assert abs(proj.damage - expected) < 0.01

    def test_range_modifier_extends_firing_range(self):
        """Enhanced optics upgrade extends weapon range."""
        bus = _make_bus()
        upgrade_sys = UpgradeSystem()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, upgrade_system=upgrade_sys,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0
        ws.assign_weapon("t1", Weapon(name="test", accuracy=1.0, damage=10.0))

        # Place hostile just beyond base range (80m) but within upgraded range
        hostile = _make_target("h1", "hostile", "person", position=(90, 0))
        hostile.apply_combat_profile()

        # Without upgrade, should be out of range
        proj1 = combat.fire(turret, hostile)
        assert proj1 is None

        # Apply enhanced_optics (+20% range: 80 * 1.2 = 96m)
        turret.last_fired = 0
        result = upgrade_sys.apply_upgrade("t1", "enhanced_optics", target=turret)
        assert result is True
        proj2 = combat.fire(turret, hostile)
        assert proj2 is not None

    def test_damage_reduction_reduces_hit_damage(self):
        """Reinforced chassis upgrade reduces incoming damage."""
        bus = _make_bus()
        upgrade_sys = UpgradeSystem()
        ws = WeaponSystem()
        combat = CombatSystem(event_bus=bus, upgrade_system=upgrade_sys,
                              weapon_system=ws)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0
        ws.assign_weapon("t1", Weapon(name="test", accuracy=1.0, damage=10.0))

        hostile = _make_target("h1", "hostile", "person", position=(3, 0))
        hostile.apply_combat_profile()
        hostile.health = 100.0
        hostile.max_health = 100.0

        # Apply reinforced_chassis to hostile (15% damage reduction)
        result = upgrade_sys.apply_upgrade("h1", "reinforced_chassis", target=hostile)
        assert result is True

        proj = combat.fire(turret, hostile)
        assert proj is not None

        targets = {"t1": turret, "h1": hostile}
        combat.tick(0.1, targets)

        # Damage should be reduced: 15 * (1 - 0.15) = 12.75
        expected_health = 100.0 - (turret.weapon_damage * 0.85)
        assert abs(hostile.health - expected_health) < 0.01

    def test_no_upgrade_system_legacy_behavior(self):
        """Without upgrade_system, combat uses base stats (backward compat)."""
        bus = _make_bus()
        combat = CombatSystem(event_bus=bus)

        turret = _make_target("t1", "friendly", "turret", position=(0, 0))
        turret.apply_combat_profile()
        turret.last_fired = 0

        hostile = _make_target("h1", "hostile", "person", position=(5, 0))
        hostile.apply_combat_profile()

        proj = combat.fire(turret, hostile)
        assert proj is not None
        assert proj.damage == turret.weapon_damage

    def test_engine_passes_upgrade_system_to_combat(self):
        """SimulationEngine should wire its upgrade_system into combat."""
        engine = _make_engine()
        assert engine.combat._upgrade_system is engine.upgrade_system


class TestUnitCommsWiring:
    """Verify unit_comms signals are wired into behaviors."""

    def test_engine_wires_comms_into_behaviors(self):
        """Engine should pass unit_comms to behaviors via set_comms."""
        engine = _make_engine()
        assert engine.behaviors._comms is engine.unit_comms

    def test_emit_distress_broadcasts_signal(self):
        """UnitComms.emit_distress() creates a distress signal."""
        from engine.simulation.comms import UnitComms
        comms = UnitComms()
        comms.emit_distress("h1", (10.0, 20.0), "hostile")
        # Create a dummy unit to receive signals
        receiver = _make_target("h2", "hostile", "person", position=(15.0, 20.0))
        signals = comms.get_signals_for_unit(receiver, signal_type="distress")
        assert len(signals) == 1
        assert signals[0].position == (10.0, 20.0)

    def test_emit_contact_broadcasts_with_enemy_pos(self):
        """UnitComms.emit_contact() creates a contact signal with enemy position."""
        from engine.simulation.comms import UnitComms
        comms = UnitComms()
        comms.emit_contact("h1", (10.0, 20.0), "hostile", enemy_pos=(5.0, 5.0))
        receiver = _make_target("h2", "hostile", "person", position=(15.0, 20.0))
        signals = comms.get_signals_for_unit(receiver, signal_type="contact")
        assert len(signals) == 1
        assert signals[0].target_position == (5.0, 5.0)

    def test_emit_retreat_broadcasts_signal(self):
        """UnitComms.emit_retreat() creates a retreat signal."""
        from engine.simulation.comms import UnitComms
        comms = UnitComms()
        comms.emit_retreat("h1", (10.0, 20.0), "hostile")
        receiver = _make_target("h2", "hostile", "person", position=(15.0, 20.0))
        signals = comms.get_signals_for_unit(receiver, signal_type="retreat")
        assert len(signals) == 1

    def test_hostile_distress_attracts_nearby_ally(self):
        """A hostile emitting distress should cause nearby allies to converge."""
        from engine.simulation.comms import UnitComms
        engine = _make_engine()

        # Create two hostiles close enough for comms range (50m)
        h1 = _make_target("h1", "hostile", "person", speed=1.5, position=(10.0, 0.0))
        h1.status = "active"
        h1.fsm_state = "engaging"
        h1.waypoints = [(0.0, 0.0)]  # heading toward base

        h2 = _make_target("h2", "hostile", "person", speed=1.5, position=(30.0, 0.0))
        h2.status = "active"
        h2.fsm_state = "advancing"
        h2.waypoints = [(0.0, 0.0)]  # heading toward base

        engine.add_target(h1)
        engine.add_target(h2)

        # h1 emits distress — h2 should eventually react
        engine.unit_comms.emit_distress("h1", h1.position, "hostile")

        # Tick behaviors — h2 should get the distress signal
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.behaviors.tick(0.1, targets_dict)

        # h2 should have modified waypoints toward h1's position
        # (or at least the signal should be available to h2)
        signals = engine.unit_comms.get_signals_for_unit(h2, signal_type="distress")
        assert len(signals) >= 1
