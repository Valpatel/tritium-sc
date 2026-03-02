# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for subsystem cleanup when units are removed.

Verifies that remove_unit() on each subsystem properly clears all
per-unit state, preventing memory leaks during long play sessions.
"""

import pytest

from engine.simulation.morale import MoraleSystem
from engine.simulation.weapons import WeaponSystem, Weapon
from engine.simulation.pursuit import PursuitSystem
from engine.simulation.upgrades import UpgradeSystem
from engine.simulation.hostile_commander import HostileCommander, Objective
from engine.simulation.unit_missions import UnitMissionSystem
from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.cover import CoverSystem
from engine.simulation.vision import VisionSystem
from engine.simulation.lod import LODSystem
from engine.simulation.stats import StatsTracker
from engine.simulation.squads import SquadManager
from engine.simulation.npc import NPCManager, NPCMission
from engine.simulation.target import SimulationTarget

pytestmark = pytest.mark.unit


class TestMoraleSystemCleanup:
    """MoraleSystem should clean up _morale and _last_hit_time on remove."""

    def test_remove_unit_clears_morale(self):
        ms = MoraleSystem()
        ms.set_morale("h1", 0.5)
        ms.on_damage_taken("h1", 10.0)
        assert "h1" in ms._morale
        assert "h1" in ms._last_hit_time

        ms.remove_unit("h1")
        assert "h1" not in ms._morale
        assert "h1" not in ms._last_hit_time

    def test_remove_unit_preserves_other_units(self):
        ms = MoraleSystem()
        ms.set_morale("h1", 0.5)
        ms.set_morale("h2", 0.8)
        ms.remove_unit("h1")
        assert ms.get_morale("h2") == 0.8

    def test_remove_unknown_unit_no_error(self):
        ms = MoraleSystem()
        ms.remove_unit("nonexistent")  # should not raise


class TestWeaponSystemCleanup:
    """WeaponSystem should clean up _weapons and _reload_timers on remove."""

    def test_remove_unit_clears_weapon(self):
        ws = WeaponSystem()
        ws.assign_weapon("t1", Weapon(name="turret_cannon", damage=15.0))
        assert ws.get_weapon("t1") is not None

        ws.remove_unit("t1")
        assert ws.get_weapon("t1") is None

    def test_remove_unit_clears_reload_timer(self):
        ws = WeaponSystem()
        ws.assign_weapon("t1", Weapon(name="turret_cannon", damage=15.0))
        ws._reload_timers["t1"] = 2.5

        ws.remove_unit("t1")
        assert "t1" not in ws._reload_timers

    def test_remove_unknown_unit_no_error(self):
        ws = WeaponSystem()
        ws.remove_unit("nonexistent")


class TestPursuitSystemCleanup:
    """PursuitSystem should clean up _pursuit_assignments on remove."""

    def test_remove_unit_clears_assignment(self):
        ps = PursuitSystem()
        ps.assign("r1", "h1")
        assert ps.get_assignment("r1") == "h1"

        ps.remove_unit("r1")
        assert ps.get_assignment("r1") is None

    def test_remove_unit_clears_intercept_point(self):
        ps = PursuitSystem()
        ps._intercept_points["h1"] = (10.0, 20.0)

        ps.remove_unit("h1")
        assert "h1" not in ps._intercept_points

    def test_remove_unknown_unit_no_error(self):
        ps = PursuitSystem()
        ps.remove_unit("nonexistent")


class TestUpgradeSystemCleanup:
    """UpgradeSystem should clean up all per-unit state on remove."""

    def test_remove_unit_clears_upgrades(self):
        us = UpgradeSystem()
        us._unit_upgrades["t1"] = ["armor_plating"]
        us._unit_abilities["t1"] = ["speed_boost"]
        us._ability_cooldowns[("t1", "speed_boost")] = 5.0
        us._upgrades["t1"] = {"weapon_damage": {"multiplier": 1.15, "remaining": 30.0}}

        us.remove_unit("t1")
        assert "t1" not in us._unit_upgrades
        assert "t1" not in us._unit_abilities
        assert ("t1", "speed_boost") not in us._ability_cooldowns
        assert "t1" not in us._upgrades

    def test_remove_unit_clears_active_effects(self):
        """Active effects referencing the removed unit should be cleared."""
        us = UpgradeSystem()
        from engine.simulation.upgrades import ActiveEffect
        us._active_effects.append(ActiveEffect(
            target_id="t1", ability_id="speed_boost",
            effect="speed_boost", magnitude=1.5, remaining=10.0,
        ))
        us._active_effects.append(ActiveEffect(
            target_id="t2", ability_id="speed_boost",
            effect="speed_boost", magnitude=1.3, remaining=5.0,
        ))

        us.remove_unit("t1")
        assert len(us._active_effects) == 1
        assert us._active_effects[0].target_id == "t2"

    def test_remove_unknown_unit_no_error(self):
        us = UpgradeSystem()
        us.remove_unit("nonexistent")


class TestEngineRemoveTargetCleansSubsystems:
    """engine.remove_target() should call remove_unit() on all subsystems."""

    def test_remove_target_cleans_weapon_system(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
        )
        engine.add_target(target)
        assert engine.weapon_system.get_weapon("t1") is not None

        engine.remove_target("t1")
        assert engine.weapon_system.get_weapon("t1") is None

    def test_remove_target_cleans_morale(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        engine.add_target(target)
        engine.morale_system.set_morale("h1", 0.5)

        engine.remove_target("h1")
        # After removal, morale should return default (1.0) — entry cleared
        assert engine.morale_system.get_morale("h1") == 1.0


class TestHostileCommanderCleanup:
    """HostileCommander should clean up _objectives on remove_unit()."""

    def test_remove_unit_clears_objective(self):
        hc = HostileCommander()
        hc._objectives["h1"] = Objective(
            type="assault",
            target_position=(10.0, 20.0),
            priority=3,
        )
        assert "h1" in hc._objectives

        hc.remove_unit("h1")
        assert "h1" not in hc._objectives

    def test_remove_unit_nonexistent_is_safe(self):
        hc = HostileCommander()
        hc.remove_unit("nonexistent")  # should not raise

    def test_remove_unit_preserves_others(self):
        hc = HostileCommander()
        hc._objectives["h1"] = Objective(type="assault", target_position=(0, 0))
        hc._objectives["h2"] = Objective(type="flank", target_position=(5, 5))

        hc.remove_unit("h1")
        assert "h1" not in hc._objectives
        assert "h2" in hc._objectives


class TestUnitMissionsCleanup:
    """UnitMissions should clean up _missions and _backstories on remove_unit()."""

    def test_remove_unit_clears_mission(self):
        um = UnitMissionSystem()
        um._missions["h1"] = {"type": "assault", "description": "Attack!"}
        assert "h1" in um._missions

        um.remove_unit("h1")
        assert "h1" not in um._missions

    def test_remove_unit_clears_backstory(self):
        um = UnitMissionSystem()
        um._backstories["h1"] = "Born in the shadows..."
        assert "h1" in um._backstories

        um.remove_unit("h1")
        assert "h1" not in um._backstories

    def test_remove_unit_clears_both(self):
        um = UnitMissionSystem()
        um._missions["h1"] = {"type": "recon"}
        um._backstories["h1"] = "A mysterious figure..."

        um.remove_unit("h1")
        assert "h1" not in um._missions
        assert "h1" not in um._backstories

    def test_remove_nonexistent_is_safe(self):
        um = UnitMissionSystem()
        um.remove_unit("nonexistent")  # should not raise


class TestEngineRemoveTargetCleansCommanderAndMissions:
    """engine.remove_target() should clean up hostile_commander and unit_missions."""

    def test_remove_cleans_hostile_commander(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.hostile_commander._objectives["h1"] = Objective(
            type="assault", target_position=(0, 0),
        )

        engine.remove_target("h1")
        assert "h1" not in engine.hostile_commander._objectives

    def test_remove_cleans_unit_missions(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.unit_missions._missions["h1"] = {"type": "patrol"}
        engine.unit_missions._backstories["h1"] = "A warrior..."

        engine.remove_target("h1")
        assert "h1" not in engine.unit_missions._missions
        assert "h1" not in engine.unit_missions._backstories


# ================================================================
# Wave 2: Additional subsystem cleanup (behaviors, cover, vision,
# lod, stats, squads)
# ================================================================


class TestBehaviorsCleanup:
    """UnitBehaviors should clean up all per-unit dicts on remove_unit()."""

    def test_remove_unit_clears_dodge_state(self):
        from unittest.mock import MagicMock
        b = UnitBehaviors(MagicMock())
        b._last_dodge["h1"] = 123.0
        b._last_flank["h1"] = 456.0
        b.remove_unit("h1")
        assert "h1" not in b._last_dodge
        assert "h1" not in b._last_flank

    def test_remove_unit_clears_speed_state(self):
        from unittest.mock import MagicMock
        b = UnitBehaviors(MagicMock())
        b._base_speeds["h1"] = 2.5
        b._detected_base_speeds["h1"] = 3.0
        b._bomber_original_speeds["h1"] = 1.8
        b.remove_unit("h1")
        assert "h1" not in b._base_speeds
        assert "h1" not in b._detected_base_speeds
        assert "h1" not in b._bomber_original_speeds

    def test_remove_unknown_unit_no_error(self):
        from unittest.mock import MagicMock
        b = UnitBehaviors(MagicMock())
        b.remove_unit("nonexistent")

    def test_remove_preserves_other_units(self):
        from unittest.mock import MagicMock
        b = UnitBehaviors(MagicMock())
        b._last_dodge["h1"] = 1.0
        b._last_dodge["h2"] = 2.0
        b.remove_unit("h1")
        assert "h2" in b._last_dodge


class TestCoverSystemCleanup:
    """CoverSystem should clean up per-unit state on remove_unit()."""

    def test_remove_unit_clears_cover(self):
        cs = CoverSystem()
        cs._unit_cover["h1"] = 0.5
        cs.remove_unit("h1")
        assert "h1" not in cs._unit_cover

    def test_remove_unit_clears_assignment(self):
        cs = CoverSystem()
        cs._assignments["h1"] = "some_cover_point"
        cs.remove_unit("h1")
        assert "h1" not in cs._assignments

    def test_remove_unknown_unit_no_error(self):
        cs = CoverSystem()
        cs.remove_unit("nonexistent")


class TestVisionSystemCleanup:
    """VisionSystem should clean up _sweep_angles on remove_unit()."""

    def test_remove_unit_clears_sweep_angle(self):
        vs = VisionSystem()
        vs._sweep_angles["t1"] = 45.0
        vs.remove_unit("t1")
        assert "t1" not in vs._sweep_angles

    def test_remove_unknown_unit_no_error(self):
        vs = VisionSystem()
        vs.remove_unit("nonexistent")

    def test_reset_clears_all(self):
        vs = VisionSystem()
        vs._sweep_angles["t1"] = 45.0
        vs._sweep_angles["t2"] = 90.0
        vs.reset()
        assert len(vs._sweep_angles) == 0


class TestLODSystemCleanup:
    """LODSystem should clean up _tiers on remove_unit()."""

    def test_remove_unit_clears_tier(self):
        from engine.simulation.lod import LODTier
        ls = LODSystem()
        ls._tiers["t1"] = LODTier.MEDIUM
        ls.remove_unit("t1")
        assert "t1" not in ls._tiers

    def test_remove_unknown_unit_no_error(self):
        ls = LODSystem()
        ls.remove_unit("nonexistent")

    def test_reset_clears_all(self):
        from engine.simulation.lod import LODTier
        ls = LODSystem()
        ls._tiers["t1"] = LODTier.FULL
        ls._tiers["t2"] = LODTier.MEDIUM
        ls.reset()
        assert len(ls._tiers) == 0


class TestStatsTrackerCleanup:
    """StatsTracker should clean up per-unit state on remove_unit()."""

    def test_remove_unit_clears_stats(self):
        st = StatsTracker()
        st._unit_stats["h1"] = "stats_placeholder"
        st._last_positions["h1"] = (10.0, 20.0)
        st.remove_unit("h1")
        assert "h1" not in st._unit_stats
        assert "h1" not in st._last_positions

    def test_remove_unknown_unit_no_error(self):
        st = StatsTracker()
        st.remove_unit("nonexistent")

    def test_remove_preserves_other_units(self):
        st = StatsTracker()
        st._unit_stats["h1"] = "stats1"
        st._unit_stats["h2"] = "stats2"
        st.remove_unit("h1")
        assert "h2" in st._unit_stats


class TestSquadManagerCleanup:
    """SquadManager should clean up _hold_base_speeds on remove_unit()."""

    def test_remove_unit_clears_hold_speed(self):
        sm = SquadManager()
        sm._hold_base_speeds["h1"] = 2.5
        sm.remove_unit("h1")
        assert "h1" not in sm._hold_base_speeds

    def test_remove_unknown_unit_no_error(self):
        sm = SquadManager()
        sm.remove_unit("nonexistent")


class TestEngineRemoveTargetCleansAllSubsystems:
    """engine.remove_target() should clean up all subsystem per-unit state."""

    def test_remove_cleans_behaviors(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.behaviors._last_dodge["h1"] = 1.0
        engine.behaviors._base_speeds["h1"] = 2.0

        engine.remove_target("h1")
        assert "h1" not in engine.behaviors._last_dodge
        assert "h1" not in engine.behaviors._base_speeds

    def test_remove_cleans_cover_system(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.cover_system._unit_cover["h1"] = 0.5

        engine.remove_target("h1")
        assert "h1" not in engine.cover_system._unit_cover

    def test_remove_cleans_vision_system(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
        )
        engine.add_target(target)
        engine.vision_system._sweep_angles["t1"] = 90.0

        engine.remove_target("t1")
        assert "t1" not in engine.vision_system._sweep_angles

    def test_remove_cleans_stats_tracker(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.stats_tracker._unit_stats["h1"] = "stats"
        engine.stats_tracker._last_positions["h1"] = (10, 10)

        engine.remove_target("h1")
        assert "h1" not in engine.stats_tracker._unit_stats
        assert "h1" not in engine.stats_tracker._last_positions

    def test_remove_cleans_squad_manager(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 10.0),
        )
        engine.add_target(target)
        engine.squad_manager._hold_base_speeds["h1"] = 2.5

        engine.remove_target("h1")
        assert "h1" not in engine.squad_manager._hold_base_speeds


# ================================================================
# Wave 3: NPCManager cleanup (missions, vehicle_types, bindings,
# npc_ids, used_names)
# ================================================================


class TestNPCManagerCleanup:
    """NPCManager should clean up all per-unit dicts on remove_unit()."""

    def _make_engine_mock(self):
        from unittest.mock import MagicMock
        engine = MagicMock()
        engine._map_bounds = 100.0
        engine.get_targets.return_value = []
        return engine

    def test_remove_unit_clears_missions(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.add("v1")
        nm._missions["v1"] = NPCMission(
            mission_type="commute",
            origin=(0.0, 0.0),
            destination=(50.0, 50.0),
        )

        nm.remove_unit("v1")
        assert "v1" not in nm._missions

    def test_remove_unit_clears_vehicle_types(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.add("v1")
        nm._vehicle_types["v1"] = "sedan"

        nm.remove_unit("v1")
        assert "v1" not in nm._vehicle_types

    def test_remove_unit_clears_bindings(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.add("v1")
        nm._bindings["v1"] = {"source": "cot", "track_id": "ext-1"}

        nm.remove_unit("v1")
        assert "v1" not in nm._bindings

    def test_remove_unit_clears_npc_ids(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.add("v1")

        nm.remove_unit("v1")
        assert "v1" not in nm._npc_ids

    def test_remove_unit_clears_all_four_dicts(self):
        """All per-unit dicts should be cleaned in a single remove_unit call."""
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.add("v1")
        nm._missions["v1"] = NPCMission(
            mission_type="patrol",
            origin=(0.0, 0.0),
            destination=(10.0, 10.0),
        )
        nm._vehicle_types["v1"] = "pickup"
        nm._bindings["v1"] = {"source": "mqtt", "track_id": "robot-7"}

        nm.remove_unit("v1")
        assert "v1" not in nm._npc_ids
        assert "v1" not in nm._missions
        assert "v1" not in nm._vehicle_types
        assert "v1" not in nm._bindings

    def test_remove_unit_preserves_other_units(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.update({"v1", "v2"})
        nm._missions["v1"] = NPCMission("commute", (0, 0), (10, 10))
        nm._missions["v2"] = NPCMission("patrol", (5, 5), (20, 20))
        nm._vehicle_types["v1"] = "sedan"
        nm._vehicle_types["v2"] = "suv"

        nm.remove_unit("v1")
        assert "v2" in nm._npc_ids
        assert "v2" in nm._missions
        assert "v2" in nm._vehicle_types

    def test_remove_nonexistent_unit_no_error(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm.remove_unit("nonexistent")  # should not raise

    def test_npc_count_decreases_after_remove(self):
        engine = self._make_engine_mock()
        nm = NPCManager(engine)
        nm._npc_ids.update({"v1", "v2", "p1"})
        assert nm.npc_count == 3

        nm.remove_unit("v1")
        assert nm.npc_count == 2


class TestEngineRemoveTargetCleansNPCManager:
    """engine.remove_target() should call npc_manager.remove_unit()."""

    def test_remove_target_cleans_npc_manager(self):
        from unittest.mock import MagicMock
        from engine.simulation.engine import SimulationEngine

        bus = MagicMock()
        bus.publish = MagicMock()
        bus.subscribe = MagicMock(return_value=MagicMock(
            get=MagicMock(side_effect=Exception("timeout"))
        ))
        engine = SimulationEngine(bus)

        # Manually set up npc_manager (normally done in start())
        engine._npc_manager = NPCManager(engine)

        target = SimulationTarget(
            target_id="v1", name="Red Sedan", alliance="neutral",
            asset_type="vehicle", position=(10.0, 10.0),
        )
        engine.add_target(target)

        # Simulate NPCManager tracking this unit
        engine._npc_manager._npc_ids.add("v1")
        engine._npc_manager._missions["v1"] = NPCMission(
            mission_type="commute",
            origin=(10.0, 10.0),
            destination=(50.0, 50.0),
        )
        engine._npc_manager._vehicle_types["v1"] = "sedan"
        engine._npc_manager._bindings["v1"] = {
            "source": "cot", "track_id": "ext-1",
        }

        engine.remove_target("v1")

        assert "v1" not in engine._npc_manager._npc_ids
        assert "v1" not in engine._npc_manager._missions
        assert "v1" not in engine._npc_manager._vehicle_types
        assert "v1" not in engine._npc_manager._bindings
