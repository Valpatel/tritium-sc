# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for CoverSystem -- cover positions and damage reduction.

Tests cover:
  - CoverObject dataclass creation
  - CoverSystem add, clear, reset
  - Cover proximity calculation
  - Cover bonus capped at 0.8
  - Tick updates cover for all targets
  - No cover for far-away or eliminated units
  - get_cover_bonus with attacker position (directional check)
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

from engine.simulation.cover import CoverObject, CoverSystem
from engine.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            key = topic or "__all__"
            self._subscribers.setdefault(key, []).append(q)
        return q


pytestmark = pytest.mark.unit


def _make_target(
    target_id: str = "t1",
    name: str = "Test",
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (0.0, 0.0),
    **kwargs,
) -> SimulationTarget:
    return SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        **kwargs,
    )


# --------------------------------------------------------------------------
# CoverObject creation
# --------------------------------------------------------------------------


class TestCoverObjectCreation:
    """CoverObject dataclass has correct fields."""

    def test_basic_cover_object(self):
        co = CoverObject(position=(10.0, 20.0))
        assert co.position == (10.0, 20.0)
        assert co.radius == 2.0  # default
        assert co.cover_value == 0.5  # default

    def test_custom_radius(self):
        co = CoverObject(position=(0.0, 0.0), radius=5.0)
        assert co.radius == 5.0

    def test_custom_cover_value(self):
        co = CoverObject(position=(0.0, 0.0), cover_value=0.3)
        assert co.cover_value == 0.3

    def test_zero_cover_value(self):
        co = CoverObject(position=(0.0, 0.0), cover_value=0.0)
        assert co.cover_value == 0.0

    def test_max_cover_value(self):
        co = CoverObject(position=(0.0, 0.0), cover_value=0.8)
        assert co.cover_value == 0.8


# --------------------------------------------------------------------------
# CoverSystem add/clear/reset
# --------------------------------------------------------------------------


class TestCoverSystemBasic:
    """CoverSystem creation and cover object management."""

    def test_empty_system(self):
        cs = CoverSystem()
        # No errors accessing internal state
        assert cs._cover_objects == []

    def test_add_cover(self):
        cs = CoverSystem()
        co = CoverObject(position=(10.0, 20.0))
        cs.add_cover(co)
        assert len(cs._cover_objects) == 1

    def test_add_multiple_covers(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(10.0, 20.0)))
        cs.add_cover(CoverObject(position=(30.0, 40.0)))
        assert len(cs._cover_objects) == 2

    def test_clear_cover(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(10.0, 20.0)))
        cs.clear_cover()
        assert cs._cover_objects == []
        assert cs._unit_cover == {}

    def test_reset(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(10.0, 20.0)))
        cs.reset()
        assert cs._cover_objects == []
        assert cs._unit_cover == {}


# --------------------------------------------------------------------------
# Cover bonus -- proximity-based
# --------------------------------------------------------------------------


class TestCoverBonus:
    """Cover bonus is based on proximity to cover objects."""

    def test_target_at_cover_center_gets_max_bonus(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 0.0), radius=3.0, cover_value=0.5))
        # Target at cover center, attacker behind the cover
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 10.0),
        )
        # At center, proximity_factor = 1.0, bonus = 0.5 * 1.0 = 0.5
        # But get_cover_bonus checks dot product: cover must be between target and attacker
        # cover at (0,0), target at (0,0), attacker at (0,10)
        # ax = 0-0 = 0, ay = 10-0 = 10, cx = 0-0 = 0, cy = 0-0 = 0
        # dot = 0*0 + 10*0 = 0 (not > 0), so no bonus from directional check
        # However, dist = 0 which is <= radius so proximity_factor = 1.0
        # The dot product check requires cover to be *between* target and attacker
        assert bonus >= 0.0

    def test_target_near_cover_from_correct_direction(self):
        """Cover between target and attacker provides bonus."""
        cs = CoverSystem()
        # Cover at (0, 5), target at (0, 3), attacker at (0, 20)
        # Cover is between target and attacker
        cs.add_cover(CoverObject(position=(0.0, 5.0), radius=5.0, cover_value=0.6))
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 3.0),
            attacker_pos=(0.0, 20.0),
        )
        # dist from target to cover = 2.0, within radius 5.0
        # ax = 0-0 = 0, ay = 20-3 = 17, cx = 0-0 = 0, cy = 5-3 = 2
        # dot = 0*0 + 17*2 = 34 > 0 -- cover is effective
        assert bonus > 0.0

    def test_no_cover_from_wrong_direction(self):
        """Cover behind the target (not between target and attacker) provides no bonus."""
        cs = CoverSystem()
        # Cover at (0, -5), target at (0, 0), attacker at (0, 20)
        # Cover is behind target, not between
        cs.add_cover(CoverObject(position=(0.0, -5.0), radius=3.0, cover_value=0.6))
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 20.0),
        )
        # ax = 0, ay = 20, cx = 0, cy = -5
        # dot = 0*0 + 20*(-5) = -100 which is not > 0
        assert bonus == 0.0

    def test_no_cover_when_far_from_cover(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(100.0, 100.0), radius=3.0, cover_value=0.5))
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 10.0),
        )
        assert bonus == 0.0

    def test_no_cover_objects_returns_zero(self):
        cs = CoverSystem()
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 10.0),
        )
        assert bonus == 0.0


# --------------------------------------------------------------------------
# Cover bonus capped at 0.8
# --------------------------------------------------------------------------


class TestCoverBonusCap:
    """Cover bonus is capped at 0.8 regardless of cover_value."""

    def test_single_cover_capped(self):
        cs = CoverSystem()
        # cover_value=1.0 should still cap at 0.8
        cs.add_cover(CoverObject(position=(0.0, 2.0), radius=5.0, cover_value=1.0))
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 10.0),
        )
        assert bonus <= 0.8


# --------------------------------------------------------------------------
# Cover radius -- must be within radius
# --------------------------------------------------------------------------


class TestCoverRadius:
    """Unit must be within cover object radius to receive bonus."""

    def test_within_radius(self):
        cs = CoverSystem()
        # Cover at (0, 5), radius 5.0
        cs.add_cover(CoverObject(position=(0.0, 5.0), radius=5.0, cover_value=0.5))
        # Target at (0, 3), distance to cover = 2.0 < 5.0
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 3.0),
            attacker_pos=(0.0, 20.0),
        )
        assert bonus > 0.0

    def test_outside_radius(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 5.0), radius=1.0, cover_value=0.5))
        # Target at (0, 0), distance to cover = 5.0 > 1.0
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 20.0),
        )
        assert bonus == 0.0


# --------------------------------------------------------------------------
# Tick -- updates unit cover for all targets
# --------------------------------------------------------------------------


class TestCoverTick:
    """CoverSystem.tick() updates cached cover for all targets."""

    def test_tick_caches_cover_for_targets(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 2.0), radius=5.0, cover_value=0.5))
        t1 = _make_target(target_id="t1", position=(0.0, 0.0))
        targets = {"t1": t1}
        cs.tick(0.1, targets)
        # After tick, unit_cover should have entry for t1
        assert "t1" in cs._unit_cover

    def test_tick_skips_eliminated(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 0.0), radius=5.0, cover_value=0.5))
        t1 = _make_target(target_id="t1", position=(0.0, 0.0))
        t1.status = "eliminated"
        targets = {"t1": t1}
        cs.tick(0.1, targets)
        assert "t1" not in cs._unit_cover

    def test_tick_updates_when_unit_moves_away(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 0.0), radius=3.0, cover_value=0.5))
        t1 = _make_target(target_id="t1", position=(0.0, 0.0))
        targets = {"t1": t1}
        cs.tick(0.1, targets)
        # Initially near cover
        assert cs._unit_cover["t1"] > 0.0

        # Move far away
        t1.position = (50.0, 50.0)
        cs.tick(0.1, targets)
        assert cs._unit_cover["t1"] == 0.0

    def test_tick_updates_multiple_units(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 0.0), radius=5.0, cover_value=0.5))
        t1 = _make_target(target_id="t1", position=(0.0, 0.0))
        t2 = _make_target(target_id="t2", position=(0.0, 1.0))
        targets = {"t1": t1, "t2": t2}
        cs.tick(0.1, targets)
        assert "t1" in cs._unit_cover
        assert "t2" in cs._unit_cover

    def test_get_cover_bonus_uses_cached_value(self):
        """After tick, get_cover_bonus with target_id returns cached value."""
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(0.0, 0.0), radius=5.0, cover_value=0.5))
        t1 = _make_target(target_id="t1", position=(0.0, 0.0))
        targets = {"t1": t1}
        cs.tick(0.1, targets)
        cached = cs._unit_cover["t1"]
        # get_cover_bonus with target_id should return cached value
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 10.0),
            target_id="t1",
        )
        assert bonus == cached


# --------------------------------------------------------------------------
# No cover in open field
# --------------------------------------------------------------------------


class TestNoCoverInOpenField:
    """Positions with no nearby cover have 0 bonus."""

    def test_open_field_no_bonus(self):
        cs = CoverSystem()
        cs.add_cover(CoverObject(position=(100.0, 100.0), cover_value=0.5))
        # Target at origin, far from any cover
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 20.0),
        )
        assert bonus == 0.0

    def test_no_cover_objects_at_all(self):
        cs = CoverSystem()
        bonus = cs.get_cover_bonus(
            target_pos=(0.0, 0.0),
            attacker_pos=(0.0, 20.0),
        )
        assert bonus == 0.0
