# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetTracker performance benchmark — verifies get_all() stays fast at scale."""

import time
import pytest

from engine.tactical.target_tracker import TargetTracker


@pytest.mark.unit
class TestTargetTrackerPerformance:
    """Verify TargetTracker can handle 10,000 targets with acceptable latency."""

    def _populate(self, tracker: TargetTracker, count: int) -> None:
        """Add *count* simulation targets to the tracker."""
        for i in range(count):
            tracker.update_from_simulation({
                "target_id": f"perf_target_{i}",
                "name": f"Target {i}",
                "alliance": "hostile" if i % 3 == 0 else "friendly",
                "asset_type": "person" if i % 2 == 0 else "drone",
                "position": {"x": float(i % 100), "y": float(i // 100)},
                "heading": 0.0,
                "speed": 1.0,
                "battery": 0.8,
                "status": "active",
            })

    def test_get_all_10k_under_100ms(self):
        """get_all() with 10,000 targets must complete in < 100ms."""
        tracker = TargetTracker()
        self._populate(tracker, 10_000)

        # Warm up
        tracker.get_all()

        # Benchmark
        iterations = 10
        start = time.perf_counter()
        for _ in range(iterations):
            targets = tracker.get_all()
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert len(targets) == 10_000, f"Expected 10000 targets, got {len(targets)}"
        assert avg_ms < 100, f"get_all() took {avg_ms:.1f}ms avg (limit 100ms)"

    def test_get_hostiles_10k_under_50ms(self):
        """get_hostiles() with 10,000 targets must complete in < 50ms."""
        tracker = TargetTracker()
        self._populate(tracker, 10_000)

        iterations = 10
        start = time.perf_counter()
        for _ in range(iterations):
            hostiles = tracker.get_hostiles()
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        # ~3333 hostiles (every 3rd)
        assert len(hostiles) > 3000
        assert avg_ms < 50, f"get_hostiles() took {avg_ms:.1f}ms avg (limit 50ms)"

    def test_update_throughput(self):
        """Measure update throughput — should handle 10k updates in < 500ms."""
        tracker = TargetTracker()
        data_batch = [
            {
                "target_id": f"throughput_{i}",
                "name": f"T{i}",
                "alliance": "hostile",
                "asset_type": "person",
                "position": {"x": float(i), "y": 0.0},
                "heading": 0.0,
                "speed": 1.0,
                "battery": 1.0,
                "status": "active",
            }
            for i in range(10_000)
        ]

        start = time.perf_counter()
        for d in data_batch:
            tracker.update_from_simulation(d)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(tracker.get_all()) == 10_000
        assert elapsed_ms < 500, f"10k updates took {elapsed_ms:.1f}ms (limit 500ms)"

    def test_summary_10k_under_200ms(self):
        """summary() with 10,000 targets must complete in < 200ms."""
        tracker = TargetTracker()
        self._populate(tracker, 10_000)

        start = time.perf_counter()
        summary = tracker.summary()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert "BATTLESPACE" in summary
        assert elapsed_ms < 200, f"summary() took {elapsed_ms:.1f}ms (limit 200ms)"
