# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for unit mission and backstory system.

Every unit (friendly, hostile, neutral) gets:
- A backstory/personality (LLM-generated async, scripted fallback)
- Active mission goals (patrol, scout, hold, etc.)
- Starter missions assigned immediately at spawn

Friendly units must NEVER sit idle — always patrolling, scouting, or pursuing goals.
"""

import pytest
import math
from unittest.mock import MagicMock

from engine.simulation.target import SimulationTarget


def _make_target(tid, x, y, alliance="friendly", asset_type="rover",
                 speed=3.0, status="active"):
    t = SimulationTarget(
        target_id=tid, name=f"Unit-{tid}", alliance=alliance,
        asset_type=asset_type, position=(x, y), speed=speed,
    )
    t.status = status
    return t


class TestUnitMissionSystemImport:
    def test_import(self):
        from engine.simulation.unit_missions import UnitMissionSystem
        assert UnitMissionSystem is not None

    def test_create(self):
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        assert sys is not None


class TestStarterMissions:
    """Test immediate starter mission assignment."""

    def test_friendly_gets_starter_mission(self):
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover")
        mission = sys.assign_starter_mission(t)
        assert mission is not None
        assert "type" in mission
        assert mission["type"] in ("patrol", "scout", "hold", "escort", "sweep")

    def test_turret_gets_hold_mission(self):
        """Stationary turrets should get 'hold' missions."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("t1", 5, 5, "friendly", "turret", speed=0)
        mission = sys.assign_starter_mission(t)
        assert mission["type"] == "hold"

    def test_drone_gets_scout_mission(self):
        """Drones should get scout/patrol missions."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("d1", 0, 0, "friendly", "drone", speed=6)
        mission = sys.assign_starter_mission(t)
        assert mission["type"] in ("scout", "patrol", "sweep")

    def test_rover_gets_patrol_mission(self):
        """Rovers should get patrol missions."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover", speed=3)
        mission = sys.assign_starter_mission(t)
        assert mission["type"] in ("patrol", "scout", "sweep", "escort")

    def test_mission_has_waypoints(self):
        """Patrol/scout missions should include waypoints."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover", speed=3)
        mission = sys.assign_starter_mission(t)
        if mission["type"] in ("patrol", "scout", "sweep"):
            assert "waypoints" in mission
            assert len(mission["waypoints"]) >= 2

    def test_hostile_gets_mission(self):
        """Hostiles should also get missions."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("h1", 20, 20, "hostile", "person", speed=1.5)
        mission = sys.assign_starter_mission(t)
        assert mission is not None
        assert mission["type"] in ("assault", "infiltrate", "scout", "advance")

    def test_neutral_gets_mission(self):
        """Neutrals should get civilian missions."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("n1", 10, 10, "neutral", "person", speed=1.2)
        mission = sys.assign_starter_mission(t)
        assert mission is not None
        assert mission["type"] in ("commute", "wander", "errand", "walk")


class TestBackstoryGeneration:
    """Test backstory/personality generation."""

    def test_scripted_backstory(self):
        """Scripted fallback should produce a backstory immediately."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover")
        story = sys.generate_backstory_scripted(t)
        assert isinstance(story, str)
        assert len(story) > 20

    def test_backstory_varies_by_type(self):
        """Different unit types should get different backstories."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        rover = _make_target("r1", 0, 0, "friendly", "rover")
        drone = _make_target("d1", 0, 0, "friendly", "drone", speed=6)
        turret = _make_target("t1", 0, 0, "friendly", "turret", speed=0)

        stories = {
            sys.generate_backstory_scripted(rover),
            sys.generate_backstory_scripted(drone),
            sys.generate_backstory_scripted(turret),
        }
        # Should have at least 2 distinct stories
        assert len(stories) >= 2

    def test_backstory_for_hostile(self):
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("h1", 20, 20, "hostile", "person")
        story = sys.generate_backstory_scripted(t)
        assert isinstance(story, str)
        assert len(story) > 20

    def test_backstory_for_neutral(self):
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("n1", 10, 10, "neutral", "person")
        story = sys.generate_backstory_scripted(t)
        assert isinstance(story, str)
        assert len(story) > 20

    def test_llm_prompt_generation(self):
        """Should be able to generate an LLM prompt for backstory."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover")
        prompt = sys.build_backstory_prompt(t)
        assert isinstance(prompt, str)
        assert "rover" in prompt.lower() or "unit" in prompt.lower()


class TestTickIntegration:
    """Test the mission system tick integration."""

    def test_tick_assigns_missions_to_idle_units(self):
        """Idle friendly units should get missions during tick."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        targets = {}
        # Create idle friendly rover with no waypoints
        r = _make_target("r1", 0, 0, "friendly", "rover")
        r.waypoints = []
        targets[r.target_id] = r

        sys.tick(0.1, targets)
        # After tick, rover should have waypoints (assigned a mission)
        assert len(r.waypoints) > 0 or r.target_id in sys._missions

    def test_tick_does_not_reassign_active_units(self):
        """Units with active waypoints should not be reassigned."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        targets = {}
        r = _make_target("r1", 0, 0, "friendly", "rover")
        r.waypoints = [(10, 10), (20, 20)]
        targets[r.target_id] = r

        # Assign a mission manually
        sys._missions[r.target_id] = {"type": "patrol", "waypoints": [(10, 10), (20, 20)]}

        old_waypoints = list(r.waypoints)
        sys.tick(0.1, targets)
        # Waypoints should not change
        assert r.waypoints == old_waypoints

    def test_patrol_loops(self):
        """Patrol missions should loop — when target reaches end, restart."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        targets = {}
        r = _make_target("r1", 0, 0, "friendly", "rover")
        r.waypoints = []
        r.status = "active"
        targets[r.target_id] = r

        # Assign a patrol mission
        patrol_wps = [(10, 10), (20, 20), (-10, -10)]
        sys._missions[r.target_id] = {"type": "patrol", "waypoints": patrol_wps}

        # Simulate reaching end of waypoints
        r.waypoints = []
        sys.tick(0.1, targets)
        # Should have reassigned the patrol waypoints
        assert len(r.waypoints) > 0


class TestLLMBackstoryAsync:
    """Test async LLM backstory generation."""

    def test_request_llm_backstory(self):
        """Should queue an LLM backstory request."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover")
        sys.request_llm_backstory(t)
        assert t.target_id in sys._pending_backstories

    def test_backstory_stored_after_generation(self):
        """After generation, backstory should be stored."""
        from engine.simulation.unit_missions import UnitMissionSystem
        sys = UnitMissionSystem()
        t = _make_target("r1", 0, 0, "friendly", "rover")
        # Simulate completed backstory
        sys._backstories[t.target_id] = "A veteran rover unit, designation R-1."
        assert sys.get_backstory(t.target_id) is not None
        assert "R-1" in sys.get_backstory(t.target_id)
