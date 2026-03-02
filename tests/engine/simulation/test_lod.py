# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the LOD (Level of Detail) simulation fidelity system."""

import pytest
from unittest.mock import MagicMock

from engine.simulation.lod import (
    LODSystem,
    LODTier,
    ViewportState,
    TIER_TICK_DIVISOR,
    TIER_IDLE_THRESHOLD,
    TIER_TELEMETRY_DIVISOR,
)


def _make_target(x=0.0, y=0.0, alliance="neutral", is_combatant=False, tid=None):
    """Create a mock target at position (x, y)."""
    t = MagicMock()
    t.target_id = tid or f"t-{x}-{y}"
    t.position = (x, y)
    t.alliance = alliance
    t.is_combatant = is_combatant
    return t


class TestViewportState:
    """ViewportState default values and structure."""

    def test_default_values(self):
        vs = ViewportState()
        assert vs.center_x == 0.0
        assert vs.center_y == 0.0
        assert vs.radius == 150.0
        assert vs.zoom == 16.0
        assert vs._set is False

    def test_custom_values(self):
        vs = ViewportState(center_x=10, center_y=20, radius=300, zoom=14)
        assert vs.center_x == 10
        assert vs.center_y == 20
        assert vs.radius == 300


class TestLODSystemInit:
    """LODSystem initialization and viewport management."""

    def test_default_no_viewport(self):
        lod = LODSystem()
        assert not lod.has_viewport

    def test_viewport_property_returns_snapshot(self):
        lod = LODSystem()
        vp = lod.viewport
        assert isinstance(vp, ViewportState)
        assert vp._set is False

    def test_update_viewport_sets_flag(self):
        lod = LODSystem()
        lod.update_viewport(10.0, 20.0, zoom=16.0)
        assert lod.has_viewport

    def test_update_viewport_center(self):
        lod = LODSystem()
        lod.update_viewport(50.0, -30.0, radius=200.0)
        vp = lod.viewport
        assert vp.center_x == 50.0
        assert vp.center_y == -30.0
        assert vp.radius == 200.0

    def test_update_viewport_zoom_estimates_radius(self):
        lod = LODSystem()
        # zoom 16 -> radius 300, zoom 17 -> radius 150, zoom 15 -> radius 600
        lod.update_viewport(0.0, 0.0, zoom=17.0)
        vp = lod.viewport
        assert abs(vp.radius - 150.0) < 1.0

    def test_update_viewport_zoom_14(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, zoom=14.0)
        vp = lod.viewport
        # 300 * 2^(16-14) = 300 * 4 = 1200
        assert abs(vp.radius - 1200.0) < 1.0

    def test_update_viewport_explicit_radius_overrides_zoom(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=99.0, zoom=14.0)
        vp = lod.viewport
        assert abs(vp.radius - 99.0) < 0.1

    def test_update_viewport_radius_min_10(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=1.0)
        vp = lod.viewport
        assert vp.radius >= 10.0


class TestComputeTier:
    """LOD tier computation based on distance from viewport."""

    def test_no_viewport_returns_full(self):
        lod = LODSystem()
        t = _make_target(1000, 1000)
        assert lod.compute_tier(t) == LODTier.FULL

    def test_within_viewport_returns_full(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        t = _make_target(50, 50)  # ~70m from center, within 1.2*100=120
        assert lod.compute_tier(t) == LODTier.FULL

    def test_nearby_offscreen_returns_medium(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        # 200m from center: outside 1.2*100=120 but within 3*100=300
        t = _make_target(200, 0)
        assert lod.compute_tier(t) == LODTier.MEDIUM

    def test_far_away_neutral_returns_low(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        # 400m from center: outside 3*100=300
        t = _make_target(400, 0, alliance="neutral", is_combatant=False)
        assert lod.compute_tier(t) == LODTier.LOW

    def test_far_away_combatant_capped_at_medium(self):
        """Combatants are never lower than MEDIUM to keep combat responsive."""
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        # 400m away
        t = _make_target(400, 0, alliance="hostile", is_combatant=True)
        assert lod.compute_tier(t) == LODTier.MEDIUM

    def test_far_away_friendly_combatant_capped_at_medium(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        t = _make_target(400, 0, alliance="friendly", is_combatant=True)
        assert lod.compute_tier(t) == LODTier.MEDIUM

    def test_neutral_combatant_not_capped(self):
        """Neutral combatants (shouldn't normally exist) are NOT capped."""
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        t = _make_target(400, 0, alliance="neutral", is_combatant=True)
        assert lod.compute_tier(t) == LODTier.LOW

    def test_on_viewport_edge_returns_full(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        # Exactly at 1.2*100=120m edge
        t = _make_target(120, 0)
        assert lod.compute_tier(t) == LODTier.FULL

    def test_just_outside_viewport_returns_medium(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        t = _make_target(121, 0)
        assert lod.compute_tier(t) == LODTier.MEDIUM


class TestComputeTiers:
    """Batch tier computation for all targets."""

    def test_batch_compute(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        targets = {
            "a": _make_target(0, 0, tid="a"),    # FULL
            "b": _make_target(200, 0, tid="b"),   # MEDIUM
            "c": _make_target(400, 0, tid="c"),   # LOW (neutral non-combatant)
        }
        tiers = lod.compute_tiers(targets)
        assert tiers["a"] == LODTier.FULL
        assert tiers["b"] == LODTier.MEDIUM
        assert tiers["c"] == LODTier.LOW

    def test_get_tier_returns_cached(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        targets = {"x": _make_target(0, 0, tid="x")}
        lod.compute_tiers(targets)
        assert lod.get_tier("x") == LODTier.FULL

    def test_get_tier_unknown_returns_full(self):
        lod = LODSystem()
        assert lod.get_tier("nonexistent") == LODTier.FULL

    def test_get_stats(self):
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        targets = {
            "a": _make_target(0, 0, tid="a"),
            "b": _make_target(200, 0, tid="b"),
            "c": _make_target(400, 0, tid="c"),
        }
        lod.compute_tiers(targets)
        stats = lod.get_stats()
        assert stats["FULL"] == 1
        assert stats["MEDIUM"] == 1
        assert stats["LOW"] == 1


class TestShouldTick:
    """LOD-gated tick scheduling."""

    def test_full_tier_ticks_every_frame(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.FULL}
        for i in range(10):
            assert lod.should_tick("a", i) is True

    def test_medium_tier_ticks_every_3rd(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.MEDIUM}
        results = [lod.should_tick("a", i) for i in range(9)]
        # Every 3rd: 0, 3, 6 -> True; others False
        assert results == [True, False, False, True, False, False, True, False, False]

    def test_low_tier_ticks_every_10th(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.LOW}
        results = [lod.should_tick("a", i) for i in range(20)]
        # True at 0 and 10
        assert results[0] is True
        assert results[10] is True
        assert sum(results) == 2


class TestShouldRunBehaviors:
    """LOD-gated behavior AI scheduling."""

    def test_full_behaviors_every_frame(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.FULL}
        for i in range(10):
            assert lod.should_run_behaviors("a", i) is True

    def test_medium_behaviors_every_3rd(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.MEDIUM}
        assert lod.should_run_behaviors("a", 0) is True
        assert lod.should_run_behaviors("a", 1) is False
        assert lod.should_run_behaviors("a", 3) is True

    def test_low_no_behaviors(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.LOW}
        for i in range(30):
            assert lod.should_run_behaviors("a", i) is False


class TestShouldPublishTelemetry:
    """LOD-aware telemetry throttling."""

    def test_active_full_publishes_every_tick(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.FULL}
        for i in range(10):
            assert lod.should_publish_telemetry("a", i, idle_ticks=0) is True

    def test_idle_full_throttled_to_2hz(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.FULL}
        results = [lod.should_publish_telemetry("a", i, idle_ticks=10) for i in range(10)]
        # Publishes at tick 0 and 5 (every 5th)
        assert results[0] is True
        assert results[5] is True
        assert sum(results) == 2

    def test_idle_medium_throttled_more(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.MEDIUM}
        results = [lod.should_publish_telemetry("a", i, idle_ticks=10) for i in range(30)]
        # Publishes every 10th: 0, 10, 20
        assert results[0] is True
        assert results[10] is True
        assert results[20] is True
        assert sum(results) == 3

    def test_idle_low_rarely_publishes(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.LOW}
        results = [lod.should_publish_telemetry("a", i, idle_ticks=10) for i in range(60)]
        # Publishes every 30th: 0, 30
        assert results[0] is True
        assert results[30] is True
        assert sum(results) == 2

    def test_active_medium_publishes_every_3rd(self):
        lod = LODSystem()
        lod._tiers = {"a": LODTier.MEDIUM}
        results = [lod.should_publish_telemetry("a", i, idle_ticks=0) for i in range(9)]
        assert results == [True, False, False, True, False, False, True, False, False]


class TestTierConstants:
    """Validate tier configuration constants."""

    def test_divisors_ascending(self):
        assert TIER_TICK_DIVISOR[LODTier.FULL] < TIER_TICK_DIVISOR[LODTier.MEDIUM]
        assert TIER_TICK_DIVISOR[LODTier.MEDIUM] < TIER_TICK_DIVISOR[LODTier.LOW]

    def test_telemetry_divisors_ascending(self):
        assert TIER_TELEMETRY_DIVISOR[LODTier.FULL] < TIER_TELEMETRY_DIVISOR[LODTier.MEDIUM]
        assert TIER_TELEMETRY_DIVISOR[LODTier.MEDIUM] < TIER_TELEMETRY_DIVISOR[LODTier.LOW]

    def test_all_tiers_have_divisors(self):
        for tier in LODTier:
            assert tier in TIER_TICK_DIVISOR
            assert tier in TIER_IDLE_THRESHOLD
            assert tier in TIER_TELEMETRY_DIVISOR


class TestLODViewportUpdate:
    """Viewport update thread safety and edge cases."""

    def test_viewport_updated_multiple_times(self):
        lod = LODSystem()
        lod.update_viewport(10.0, 20.0, radius=50.0)
        lod.update_viewport(100.0, -50.0, radius=200.0)
        vp = lod.viewport
        assert vp.center_x == 100.0
        assert vp.center_y == -50.0
        assert vp.radius == 200.0

    def test_viewport_only_zoom_no_radius(self):
        lod = LODSystem()
        lod.update_viewport(0, 0, zoom=18.0)
        vp = lod.viewport
        # 300 * 2^(16-18) = 300 * 0.25 = 75
        assert abs(vp.radius - 75.0) < 1.0

    def test_tier_changes_when_viewport_moves(self):
        """When the player pans the map, tier assignments change."""
        lod = LODSystem()
        lod.update_viewport(0.0, 0.0, radius=100.0)
        t = _make_target(200, 0, tid="t1")
        assert lod.compute_tier(t) == LODTier.MEDIUM

        # Pan viewport to the target's location
        lod.update_viewport(200.0, 0.0, radius=100.0)
        assert lod.compute_tier(t) == LODTier.FULL
