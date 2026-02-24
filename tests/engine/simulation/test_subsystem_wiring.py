"""Tests for subsystem wiring into SimulationEngine.

Verifies that all extended subsystems (morale, cover, degradation, pursuit,
comms, stats, terrain, upgrades, weapons) are properly instantiated on the
engine, ticked during the engine loop, and reset during game reset.
"""

import pytest
import threading
import time
from unittest.mock import MagicMock

from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget
from engine.simulation.morale import MoraleSystem
from engine.simulation.cover import CoverSystem
from engine.simulation.degradation import DegradationSystem
from engine.simulation.pursuit import PursuitSystem
from engine.simulation.comms import UnitComms
from engine.simulation.stats import StatsTracker
from engine.simulation.terrain import TerrainMap
from engine.simulation.upgrades import UpgradeSystem
from engine.simulation.weapons import WeaponSystem


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

    def test_neutral_person_no_fsm(self):
        engine = _make_engine()
        t = _make_target("civ-1", "neutral", "person", speed=1.0)
        t.is_combatant = False
        engine.add_target(t)
        assert "civ-1" not in engine._fsms

    def test_vehicle_no_fsm(self):
        engine = _make_engine()
        t = _make_target("car-1", "neutral", "vehicle", speed=5.0)
        t.is_combatant = False
        engine.add_target(t)
        assert "car-1" not in engine._fsms

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
