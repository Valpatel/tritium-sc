# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for HeatmapEngine — grid accumulation, time windows, pruning, layers."""

import time

import pytest

from tritium_lib.tracking.heatmap import (
    HeatmapEngine,
    HeatmapEvent,
    VALID_LAYERS,
)


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------

class TestHeatmapEngineInit:
    def test_default_construction(self):
        engine = HeatmapEngine()
        assert engine.event_count() == 0

    def test_custom_retention(self):
        engine = HeatmapEngine(retention_seconds=3600)
        assert engine._retention == 3600


# ------------------------------------------------------------------
# Recording events
# ------------------------------------------------------------------

class TestRecordEvent:
    def test_record_ble(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=10.0, y=20.0)
        assert engine.event_count("ble_activity") == 1
        assert engine.event_count("all") == 1

    def test_record_camera(self):
        engine = HeatmapEngine()
        engine.record_event("camera_activity", x=5.0, y=5.0)
        assert engine.event_count("camera_activity") == 1

    def test_record_motion(self):
        engine = HeatmapEngine()
        engine.record_event("motion_activity", x=0.0, y=0.0)
        assert engine.event_count("motion_activity") == 1

    def test_invalid_layer_raises(self):
        engine = HeatmapEngine()
        with pytest.raises(ValueError, match="Invalid layer"):
            engine.record_event("bogus_layer", x=0, y=0)

    def test_custom_weight(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=5.0, y=5.0, weight=3.0)
        result = engine.get_heatmap(resolution=5, layer="ble_activity")
        assert result["max_value"] == 3.0

    def test_custom_timestamp(self):
        engine = HeatmapEngine()
        ts = time.time() - 30
        engine.record_event("ble_activity", x=1.0, y=1.0, timestamp=ts)
        assert engine.event_count() == 1

    def test_multiple_layers(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1, y=1)
        engine.record_event("camera_activity", x=2, y=2)
        engine.record_event("motion_activity", x=3, y=3)
        assert engine.event_count("all") == 3
        assert engine.event_count("ble_activity") == 1
        assert engine.event_count("camera_activity") == 1
        assert engine.event_count("motion_activity") == 1


# ------------------------------------------------------------------
# get_heatmap
# ------------------------------------------------------------------

class TestGetHeatmap:
    def test_empty_grid(self):
        engine = HeatmapEngine()
        result = engine.get_heatmap(resolution=10)
        assert result["event_count"] == 0
        assert result["max_value"] == 0.0
        assert len(result["grid"]) == 10
        assert len(result["grid"][0]) == 10

    def test_single_event_grid(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=5.0, y=5.0)
        result = engine.get_heatmap(resolution=10, layer="ble_activity")
        assert result["event_count"] == 1
        assert result["max_value"] == 1.0

        # Exactly one cell should be non-zero
        nonzero = sum(
            1
            for row in result["grid"]
            for val in row
            if val > 0
        )
        assert nonzero == 1

    def test_multiple_events_same_cell(self):
        engine = HeatmapEngine()
        for _ in range(5):
            engine.record_event("ble_activity", x=10.0, y=10.0)
        result = engine.get_heatmap(resolution=10, layer="ble_activity")
        assert result["max_value"] == 5.0

    def test_all_layer_combines_sources(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=5.0, y=5.0)
        engine.record_event("camera_activity", x=5.0, y=5.0)
        result = engine.get_heatmap(resolution=10, layer="all")
        assert result["event_count"] == 2
        assert result["max_value"] == 2.0

    def test_time_window_filters_old(self):
        engine = HeatmapEngine()
        # Old event (2 hours ago)
        engine.record_event("ble_activity", x=1.0, y=1.0,
                            timestamp=time.time() - 7200)
        # Recent event
        engine.record_event("ble_activity", x=2.0, y=2.0)

        # 1-hour window should only see the recent one
        result = engine.get_heatmap(time_window_minutes=60)
        assert result["event_count"] == 1

    def test_resolution_parameter(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1.0, y=1.0)
        for res in [5, 20, 100]:
            result = engine.get_heatmap(resolution=res)
            assert result["resolution"] == res
            assert len(result["grid"]) == res
            assert len(result["grid"][0]) == res

    def test_bounds_reflect_data(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=-50.0, y=-30.0)
        engine.record_event("ble_activity", x=50.0, y=30.0)
        result = engine.get_heatmap(resolution=10)
        bounds = result["bounds"]
        assert bounds["min_x"] == -50.0
        assert bounds["max_x"] == 50.0
        assert bounds["min_y"] == -30.0
        assert bounds["max_y"] == 30.0

    def test_layer_filter(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1.0, y=1.0)
        engine.record_event("camera_activity", x=2.0, y=2.0)

        ble = engine.get_heatmap(layer="ble_activity")
        assert ble["event_count"] == 1
        assert ble["layer"] == "ble_activity"

        cam = engine.get_heatmap(layer="camera_activity")
        assert cam["event_count"] == 1
        assert cam["layer"] == "camera_activity"


# ------------------------------------------------------------------
# Pruning
# ------------------------------------------------------------------

class TestPrune:
    def test_prune_removes_old(self):
        engine = HeatmapEngine(retention_seconds=60)
        engine.record_event("ble_activity", x=1, y=1,
                            timestamp=time.time() - 120)
        engine.record_event("ble_activity", x=2, y=2)
        removed = engine.prune()
        assert removed == 1
        assert engine.event_count() == 1

    def test_prune_with_explicit_cutoff(self):
        engine = HeatmapEngine()
        t1 = time.time() - 100
        t2 = time.time() - 50
        engine.record_event("ble_activity", x=1, y=1, timestamp=t1)
        engine.record_event("ble_activity", x=2, y=2, timestamp=t2)
        removed = engine.prune(before=time.time() - 75)
        assert removed == 1
        assert engine.event_count() == 1

    def test_prune_nothing_to_remove(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1, y=1)
        removed = engine.prune()
        assert removed == 0

    def test_clear_all(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1, y=1)
        engine.record_event("camera_activity", x=2, y=2)
        engine.clear()
        assert engine.event_count() == 0

    def test_clear_single_layer(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=1, y=1)
        engine.record_event("camera_activity", x=2, y=2)
        engine.clear("ble_activity")
        assert engine.event_count("ble_activity") == 0
        assert engine.event_count("camera_activity") == 1


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_single_point_grid(self):
        """Single event should not crash on degenerate bounds."""
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=100.0, y=100.0)
        result = engine.get_heatmap(resolution=10)
        assert result["event_count"] == 1
        assert result["max_value"] == 1.0

    def test_negative_coordinates(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=-100.0, y=-200.0)
        engine.record_event("ble_activity", x=-50.0, y=-150.0)
        result = engine.get_heatmap(resolution=10)
        assert result["event_count"] == 2

    def test_zero_coordinates(self):
        engine = HeatmapEngine()
        engine.record_event("ble_activity", x=0.0, y=0.0)
        result = engine.get_heatmap(resolution=5)
        assert result["event_count"] == 1

    def test_large_event_count(self):
        engine = HeatmapEngine()
        for i in range(1000):
            engine.record_event("ble_activity", x=float(i % 100), y=float(i // 10))
        result = engine.get_heatmap(resolution=50)
        assert result["event_count"] == 1000

    def test_valid_layers_tuple(self):
        assert "ble_activity" in VALID_LAYERS
        assert "camera_activity" in VALID_LAYERS
        assert "motion_activity" in VALID_LAYERS

    def test_event_count_unknown_layer(self):
        engine = HeatmapEngine()
        assert engine.event_count("nonexistent") == 0
