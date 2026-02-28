# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for SpatialGrid — grid-based spatial partitioning."""

from __future__ import annotations

import time

import pytest

from engine.simulation.spatial import SpatialGrid
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


def _make_target(tid: str, x: float, y: float) -> SimulationTarget:
    """Helper to create a minimal target at (x, y)."""
    return SimulationTarget(
        target_id=tid,
        name=f"T-{tid}",
        alliance="hostile",
        asset_type="person",
        position=(x, y),
        speed=0.0,
        is_combatant=False,
    )


class TestSpatialGridBasic:
    """Core functionality tests."""

    def test_empty_grid_returns_nothing(self):
        grid = SpatialGrid(cell_size=50.0)
        result = grid.query_radius((0.0, 0.0), 100.0)
        assert result == []

    def test_single_target_in_range(self):
        grid = SpatialGrid(cell_size=50.0)
        t = _make_target("a", 10.0, 10.0)
        grid.rebuild([t])
        result = grid.query_radius((0.0, 0.0), 20.0)
        assert len(result) == 1
        assert result[0].target_id == "a"

    def test_single_target_out_of_range(self):
        grid = SpatialGrid(cell_size=50.0)
        t = _make_target("a", 100.0, 100.0)
        grid.rebuild([t])
        result = grid.query_radius((0.0, 0.0), 20.0)
        assert result == []

    def test_multiple_targets_mixed_range(self):
        grid = SpatialGrid(cell_size=50.0)
        t_near = _make_target("near", 5.0, 5.0)
        t_far = _make_target("far", 200.0, 200.0)
        grid.rebuild([t_near, t_far])
        result = grid.query_radius((0.0, 0.0), 20.0)
        assert len(result) == 1
        assert result[0].target_id == "near"

    def test_rebuild_clears_old_data(self):
        grid = SpatialGrid(cell_size=50.0)
        t1 = _make_target("old", 5.0, 5.0)
        grid.rebuild([t1])
        assert len(grid.query_radius((0.0, 0.0), 20.0)) == 1

        # Rebuild with different target
        t2 = _make_target("new", 200.0, 200.0)
        grid.rebuild([t2])
        assert len(grid.query_radius((0.0, 0.0), 20.0)) == 0
        assert len(grid.query_radius((200.0, 200.0), 20.0)) == 1

    def test_query_rect(self):
        grid = SpatialGrid(cell_size=50.0)
        t_in = _make_target("in", 25.0, 25.0)
        t_out = _make_target("out", 200.0, 200.0)
        grid.rebuild([t_in, t_out])
        result = grid.query_rect((0.0, 0.0), (50.0, 50.0))
        assert len(result) == 1
        assert result[0].target_id == "in"

    def test_negative_coordinates(self):
        grid = SpatialGrid(cell_size=50.0)
        t = _make_target("neg", -30.0, -40.0)
        grid.rebuild([t])
        result = grid.query_radius((-30.0, -40.0), 5.0)
        assert len(result) == 1
        assert result[0].target_id == "neg"

    def test_cell_boundaries(self):
        """Target exactly on cell boundary should be found by queries on either side."""
        grid = SpatialGrid(cell_size=50.0)
        # Place target exactly at cell boundary (50, 0)
        t = _make_target("boundary", 50.0, 0.0)
        grid.rebuild([t])
        # Query from cell (0,0) side — radius must reach 50.0
        result = grid.query_radius((0.0, 0.0), 51.0)
        assert len(result) == 1
        # Query from cell (1,0) side
        result2 = grid.query_radius((60.0, 0.0), 15.0)
        assert len(result2) == 1

    def test_zero_radius_query(self):
        grid = SpatialGrid(cell_size=50.0)
        t = _make_target("a", 0.0, 0.0)
        grid.rebuild([t])
        result = grid.query_radius((0.0, 0.0), 0.0)
        assert len(result) == 1  # exact match at distance 0

    def test_large_radius_returns_all(self):
        grid = SpatialGrid(cell_size=50.0)
        targets = [_make_target(str(i), float(i * 10), float(i * 10)) for i in range(20)]
        grid.rebuild(targets)
        result = grid.query_radius((100.0, 100.0), 10000.0)
        assert len(result) == 20


class TestSpatialGridPerformance:
    """Performance-critical tests."""

    def test_many_targets_performance(self):
        """500 targets, 500 queries should complete in < 100ms."""
        import random
        random.seed(42)

        grid = SpatialGrid(cell_size=50.0)
        targets = [
            _make_target(str(i), random.uniform(-500, 500), random.uniform(-500, 500))
            for i in range(500)
        ]
        grid.rebuild(targets)

        start = time.perf_counter()
        for _ in range(500):
            x = random.uniform(-500, 500)
            y = random.uniform(-500, 500)
            grid.query_radius((x, y), 50.0)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"500 queries over 500 targets took {elapsed:.3f}s (> 100ms)"

    def test_rebuild_performance_1000_targets(self):
        """Rebuilding grid with 1000 targets should be fast."""
        import random
        random.seed(99)

        grid = SpatialGrid(cell_size=50.0)
        targets = [
            _make_target(str(i), random.uniform(-1000, 1000), random.uniform(-1000, 1000))
            for i in range(1000)
        ]

        start = time.perf_counter()
        for _ in range(100):
            grid.rebuild(targets)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"100 rebuilds of 1000 targets took {elapsed:.3f}s (> 500ms)"


class TestSpatialGridQueryRect:
    """Tests for query_rect specifically."""

    def test_rect_empty_grid(self):
        grid = SpatialGrid(cell_size=50.0)
        result = grid.query_rect((-100.0, -100.0), (100.0, 100.0))
        assert result == []

    def test_rect_all_inside(self):
        grid = SpatialGrid(cell_size=50.0)
        targets = [_make_target(str(i), float(i), float(i)) for i in range(5)]
        grid.rebuild(targets)
        result = grid.query_rect((-10.0, -10.0), (50.0, 50.0))
        assert len(result) == 5

    def test_rect_none_inside(self):
        grid = SpatialGrid(cell_size=50.0)
        t = _make_target("far", 200.0, 200.0)
        grid.rebuild([t])
        result = grid.query_rect((0.0, 0.0), (50.0, 50.0))
        assert result == []

    def test_rect_partial(self):
        grid = SpatialGrid(cell_size=50.0)
        t1 = _make_target("in", 25.0, 25.0)
        t2 = _make_target("out", 75.0, 75.0)
        grid.rebuild([t1, t2])
        result = grid.query_rect((0.0, 0.0), (50.0, 50.0))
        ids = {t.target_id for t in result}
        assert "in" in ids
        assert "out" not in ids
