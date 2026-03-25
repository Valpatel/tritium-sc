# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target capacity benchmark — measures TargetTracker performance at scale.

Tests update throughput, get_all latency, and correlator scan time
at 100, 1K, 5K, and 10K target counts. Asserts all stay under
reasonable thresholds for real-time operation.
"""
import math
import time

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from engine.tactical.target_tracker import TargetTracker, TrackedTarget


def _populate_tracker(tracker: TargetTracker, count: int) -> None:
    """Insert `count` BLE targets into the tracker."""
    for i in range(count):
        mac = f"{i:012x}"
        formatted_mac = ":".join(mac[j : j + 2] for j in range(0, 12, 2))
        x = math.cos(i * 0.01) * 100.0
        y = math.sin(i * 0.01) * 100.0
        tracker.update_from_ble({
            "mac": formatted_mac,
            "name": f"device-{i}",
            "rssi": -50 - (i % 40),
            "position": {"x": x, "y": y},
        })


class TestTargetCapacity:
    """Benchmark TargetTracker at various target counts."""

    @pytest.mark.parametrize("count", [100, 1000, 5000, 10000])
    def test_update_throughput(self, count: int) -> None:
        """Measure target update throughput (updates/second)."""
        tracker = TargetTracker()

        start = time.perf_counter()
        _populate_tracker(tracker, count)
        elapsed = time.perf_counter() - start

        throughput = count / elapsed if elapsed > 0 else float("inf")

        # Threshold: at least 5000 updates/sec even at 10K targets
        assert throughput > 5000, (
            f"Update throughput too low: {throughput:.0f} updates/sec "
            f"for {count} targets (threshold: 5000)"
        )
        print(f"  [{count:>5} targets] update throughput: {throughput:,.0f} ops/sec ({elapsed:.3f}s)")

    @pytest.mark.parametrize("count", [100, 1000, 5000, 10000])
    def test_get_all_latency(self, count: int) -> None:
        """Measure get_all() latency at various target counts."""
        tracker = TargetTracker()
        # Increase stale timeouts so targets survive the benchmark
        tracker.BLE_STALE_TIMEOUT = 999999.0
        _populate_tracker(tracker, count)

        # Warm up
        tracker.get_all()

        # Measure 10 iterations
        times = []
        for _ in range(10):
            start = time.perf_counter()
            targets = tracker.get_all()
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert len(targets) == count

        avg_ms = (sum(times) / len(times)) * 1000
        max_ms = max(times) * 1000

        # Threshold: get_all under 50ms even at 10K targets
        assert avg_ms < 50.0, (
            f"get_all too slow: {avg_ms:.1f}ms avg for {count} targets (threshold: 50ms)"
        )
        print(f"  [{count:>5} targets] get_all: avg={avg_ms:.2f}ms, max={max_ms:.2f}ms")

    @pytest.mark.parametrize("count", [100, 500])
    def test_correlator_scan_time(self, count: int) -> None:
        """Measure correlator single-pass scan time at various scales.

        Inserts half BLE and half YOLO targets to give the correlator
        cross-source pairs to evaluate. Uses small counts because the
        correlator does O(n^2) pair evaluation with multiple strategies
        and TrainingStore writes per pair.
        """
        tracker = TargetTracker()
        tracker.BLE_STALE_TIMEOUT = 999999.0
        tracker.STALE_TIMEOUT = 999999.0

        # Insert half BLE, half YOLO for cross-source correlation
        half = count // 2
        for i in range(half):
            mac = f"{i:012x}"
            formatted_mac = ":".join(mac[j : j + 2] for j in range(0, 12, 2))
            x = math.cos(i * 0.01) * 50.0
            y = math.sin(i * 0.01) * 50.0
            tracker.update_from_ble({
                "mac": formatted_mac,
                "name": f"ble-{i}",
                "rssi": -50 - (i % 40),
                "position": {"x": x, "y": y},
            })

        for i in range(half):
            tracker.update_from_detection({
                "class_name": "person",
                "confidence": 0.8,
                "center_x": math.cos(i * 0.01) * 50.0 + 0.01,
                "center_y": math.sin(i * 0.01) * 50.0 + 0.01,
            })

        try:
            from engine.tactical.correlator import TargetCorrelator
            from tritium_lib.tracking.dossier import DossierStore

            correlator = TargetCorrelator(
                tracker,
                radius=5.0,
                max_age=999999.0,
                interval=999.0,
                dossier_store=DossierStore(),
            )

            start = time.perf_counter()
            correlator.correlate()
            elapsed = time.perf_counter() - start
            elapsed_ms = elapsed * 1000

            # The correlator is O(n^2) with 5+ strategies + SQLite writes.
            # At 100 targets: ~5K pairs * 5 strategies = ~25K evaluations.
            # At 500 targets: ~125K pairs. Allow generous thresholds.
            threshold_ms = 120000.0 if count >= 500 else 30000.0
            assert elapsed_ms < threshold_ms, (
                f"Correlator scan too slow: {elapsed_ms:.0f}ms "
                f"for {count} targets (threshold: {threshold_ms:.0f}ms)"
            )
            print(f"  [{count:>5} targets] correlator scan: {elapsed_ms:.1f}ms")

        except ImportError as exc:
            pytest.skip(f"Correlator import failed: {exc}")

    @pytest.mark.parametrize("count", [100, 1000, 5000, 10000])
    def test_summary_performance(self, count: int) -> None:
        """Measure TargetTracker.summary() performance at scale."""
        tracker = TargetTracker()
        tracker.BLE_STALE_TIMEOUT = 999999.0

        # Mix of alliances for realistic summary
        for i in range(count):
            mac = f"{i:012x}"
            formatted_mac = ":".join(mac[j : j + 2] for j in range(0, 12, 2))
            tracker.update_from_ble({
                "mac": formatted_mac,
                "name": f"device-{i}",
                "rssi": -50,
                "position": {"x": float(i % 100), "y": float(i // 100)},
            })

        # Change some alliances
        with tracker._lock:
            for i, (tid, t) in enumerate(tracker._targets.items()):
                if i % 3 == 0:
                    t.alliance = "friendly"
                elif i % 3 == 1:
                    t.alliance = "hostile"

        start = time.perf_counter()
        summary = tracker.summary()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(summary) > 0
        # Threshold: summary under 100ms at 10K targets
        assert elapsed_ms < 100.0, (
            f"Summary too slow: {elapsed_ms:.1f}ms for {count} targets (threshold: 100ms)"
        )
        print(f"  [{count:>5} targets] summary: {elapsed_ms:.2f}ms, len={len(summary)}")

    def test_to_dict_batch(self) -> None:
        """Measure to_dict serialization for 1000 targets."""
        tracker = TargetTracker()
        tracker.BLE_STALE_TIMEOUT = 999999.0
        _populate_tracker(tracker, 1000)

        targets = tracker.get_all()
        assert len(targets) == 1000

        start = time.perf_counter()
        dicts = [t.to_dict(history=tracker.history) for t in targets]
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(dicts) == 1000
        # Each dict should have required keys
        assert "target_id" in dicts[0]
        assert "lat" in dicts[0]

        # Threshold: 1000 to_dict under 200ms
        assert elapsed_ms < 200.0, (
            f"to_dict batch too slow: {elapsed_ms:.1f}ms for 1000 targets"
        )
        print(f"  [1000 targets] to_dict batch: {elapsed_ms:.2f}ms")
