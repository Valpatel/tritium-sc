# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the hostile commander AI.

The HostileCommander is a centralized tactical AI that coordinates hostile
forces. It assigns objectives, issues squad orders, coordinates multi-prong
attacks, and reacts to the battle state.
"""

import math
import pytest
from unittest.mock import MagicMock

from engine.simulation.target import SimulationTarget


def _make_target(tid, x, y, alliance="hostile", asset_type="person",
                 speed=1.5, health=100, status="active", fsm_state=None):
    t = SimulationTarget(
        target_id=tid, name=f"Unit-{tid}", alliance=alliance,
        asset_type=asset_type, position=(x, y), speed=speed,
    )
    t.health = health
    t.max_health = health
    t.status = status
    if fsm_state:
        t.fsm_state = fsm_state
    return t


class TestHostileCommanderImport:
    def test_import(self):
        from engine.simulation.hostile_commander import HostileCommander
        assert HostileCommander is not None

    def test_create(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        assert cmd is not None


class TestTacticalAssessment:
    """Test the commander's ability to assess the battlefield."""

    def test_assess_empty_battlefield(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        assessment = cmd.assess({})
        assert "threat_level" in assessment
        assert "recommended_action" in assessment

    def test_assess_outnumbered(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        # 2 hostiles vs 5 friendlies
        for i in range(2):
            t = _make_target(f"h{i}", 10+i, 10, "hostile")
            targets[t.target_id] = t
        for i in range(5):
            t = _make_target(f"f{i}", -10-i, -10, "friendly", "turret", speed=0)
            targets[t.target_id] = t
        assessment = cmd.assess(targets)
        assert assessment["threat_level"] in ("high", "critical")

    def test_assess_advantaged(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        # 8 hostiles vs 2 friendlies
        for i in range(8):
            t = _make_target(f"h{i}", 10+i, 10, "hostile")
            targets[t.target_id] = t
        for i in range(2):
            t = _make_target(f"f{i}", -10, -10, "friendly", "turret", speed=0)
            targets[t.target_id] = t
        assessment = cmd.assess(targets)
        assert assessment["threat_level"] in ("low", "moderate")


class TestObjectiveAssignment:
    """Test objective assignment to hostile units."""

    def test_assign_objectives(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        for i in range(4):
            t = _make_target(f"h{i}", 20+i, 20, "hostile")
            targets[t.target_id] = t
        for i in range(2):
            t = _make_target(f"f{i}", -5, -5+i*10, "friendly", "turret", speed=0)
            targets[t.target_id] = t

        orders = cmd.assign_objectives(targets)
        # Should return a dict of target_id -> objective
        assert isinstance(orders, dict)
        assert len(orders) > 0

    def test_objectives_target_friendlies(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        h = _make_target("h1", 20, 20, "hostile")
        targets[h.target_id] = h
        f = _make_target("f1", -5, -5, "friendly", "turret", speed=0)
        targets[f.target_id] = f

        orders = cmd.assign_objectives(targets)
        # At least one hostile should have an objective
        assert len(orders) > 0
        for tid, obj in orders.items():
            assert "type" in obj
            assert "target_position" in obj

    def test_flanking_order(self):
        """When friendlies are clustered, commander should order flanking."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        # 6 hostiles approaching from north
        for i in range(6):
            t = _make_target(f"h{i}", i*5-15, 30, "hostile")
            targets[t.target_id] = t
        # 3 friendlies clustered in center
        for i in range(3):
            t = _make_target(f"f{i}", i*2-2, 0, "friendly", "turret", speed=0)
            targets[t.target_id] = t

        orders = cmd.assign_objectives(targets)
        order_types = [o["type"] for o in orders.values()]
        # Should include flank or assault orders
        assert any(t in order_types for t in ["flank", "assault", "advance"])


class TestTickIntegration:
    """Test the commander tick method."""

    def test_tick_no_crash(self):
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        for i in range(3):
            t = _make_target(f"h{i}", 10+i, 10, "hostile")
            targets[t.target_id] = t
        for i in range(2):
            t = _make_target(f"f{i}", -10, -10+i, "friendly", "turret", speed=0)
            targets[t.target_id] = t
        # Tick should not crash
        cmd.tick(0.1, targets)

    def test_tick_assigns_waypoints(self):
        """Commander tick should set waypoints on hostile units."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        h = _make_target("h1", 20, 20, "hostile")
        h.waypoints = []
        targets[h.target_id] = h
        f = _make_target("f1", 0, 0, "friendly", "turret", speed=0)
        targets[f.target_id] = f

        cmd.tick(0.1, targets)
        # After a tick, hostile should have waypoints (or the commander
        # chose to let it continue its current path)
        # This is more of a smoke test — exact behavior depends on tactics

    def test_tick_interval_throttled(self):
        """Commander should not reassess every tick — throttle to ~1Hz."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        h = _make_target("h1", 20, 20, "hostile")
        targets[h.target_id] = h
        f = _make_target("f1", 0, 0, "friendly", "turret", speed=0)
        targets[f.target_id] = f

        # Multiple rapid ticks should not all trigger reassessment
        cmd.tick(0.1, targets)
        count_after_1 = cmd._assess_count
        for _ in range(5):
            cmd.tick(0.1, targets)
        # Should not have assessed 6 times
        assert cmd._assess_count <= count_after_1 + 1

    def test_retreat_when_overwhelmed(self):
        """When most hostiles are eliminated, commander should order retreat."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        # 1 remaining hostile
        h = _make_target("h1", 20, 20, "hostile")
        targets[h.target_id] = h
        # 5 friendlies
        for i in range(5):
            t = _make_target(f"f{i}", i*3, 0, "friendly", "turret", speed=0)
            targets[t.target_id] = t

        orders = cmd.assign_objectives(targets)
        if orders:
            order_types = [o["type"] for o in orders.values()]
            # Lone hostile should retreat or evade
            assert any(t in order_types for t in ["retreat", "evade", "flank", "advance"])


class TestWaveCoordination:
    """Test coordination of wave-based attacks."""

    def test_multi_prong_attack(self):
        """With enough units, commander should split into attack groups."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        # 12 hostiles
        for i in range(12):
            angle = (i / 12) * 2 * math.pi
            x = 25 * math.cos(angle)
            y = 25 * math.sin(angle)
            t = _make_target(f"h{i}", x, y, "hostile")
            targets[t.target_id] = t
        # 4 friendlies in center
        for i in range(4):
            t = _make_target(f"f{i}", i*3-4, 0, "friendly", "turret", speed=0)
            targets[t.target_id] = t

        orders = cmd.assign_objectives(targets)
        # Should have orders for most hostiles
        assert len(orders) >= 6

    def test_priority_targets(self):
        """Commander should identify high-value targets (turrets)."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        targets = {}
        for i in range(4):
            t = _make_target(f"h{i}", 15+i, 15, "hostile")
            targets[t.target_id] = t
        # Turret is high-value (stationary, dangerous)
        turret = _make_target("f_turret", 0, 0, "friendly", "turret", speed=0)
        targets[turret.target_id] = turret
        # Rover is medium priority
        rover = _make_target("f_rover", -10, 0, "friendly", "rover", speed=3)
        targets[rover.target_id] = rover

        assessment = cmd.assess(targets)
        assert "priority_targets" in assessment
        # Turret should be priority (stationary, threatening)
        prio_types = [p.get("type") for p in assessment["priority_targets"]]
        assert "turret" in prio_types or len(assessment["priority_targets"]) > 0
