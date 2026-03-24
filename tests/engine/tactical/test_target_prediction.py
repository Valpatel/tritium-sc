# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TargetPrediction — movement-based position prediction."""

import math
import time

import pytest

from tritium_lib.tracking.target_history import TargetHistory
from tritium_lib.tracking.target_prediction import (
    MIN_SAMPLES,
    MIN_SPEED_THRESHOLD,
    PredictedPosition,
    predict_all_targets,
    predict_target,
)


class TestPredictedPosition:
    """Tests for the PredictedPosition dataclass."""

    def test_to_dict(self):
        pp = PredictedPosition(
            x=100.5, y=200.3,
            horizon_minutes=5,
            confidence=0.7,
            cone_radius_m=50.0,
            heading_deg=45.0,
            speed_mps=2.5,
        )
        d = pp.to_dict()
        assert d["x"] == 100.5
        assert d["y"] == 200.3
        assert d["horizon_minutes"] == 5
        assert d["confidence"] == 0.7
        assert d["cone_radius_m"] == 50.0


class TestPredictTarget:
    """Tests for the predict_target function."""

    def _make_moving_target(self, history, tid="t1", speed_x=2.0, speed_y=1.0, n=10):
        """Create a target moving at constant velocity."""
        base_t = time.monotonic() - n
        for i in range(n):
            history.record(tid, (i * speed_x, i * speed_y), timestamp=base_t + i)

    def test_moving_target_produces_predictions(self):
        h = TargetHistory()
        self._make_moving_target(h)
        preds = predict_target("t1", h)
        assert len(preds) == 3  # 1, 5, 15 min
        assert preds[0].horizon_minutes == 1
        assert preds[1].horizon_minutes == 5
        assert preds[2].horizon_minutes == 15

    def test_stationary_target_no_predictions(self):
        h = TargetHistory()
        base_t = time.monotonic() - 10
        for i in range(10):
            h.record("static", (100.0, 200.0), timestamp=base_t + i)
        preds = predict_target("static", h)
        assert len(preds) == 0  # stationary

    def test_insufficient_history(self):
        h = TargetHistory()
        h.record("short", (0.0, 0.0), timestamp=time.monotonic())
        preds = predict_target("short", h)
        assert len(preds) == 0

    def test_no_history(self):
        h = TargetHistory()
        preds = predict_target("missing", h)
        assert len(preds) == 0

    def test_prediction_direction_matches_movement(self):
        h = TargetHistory()
        self._make_moving_target(h, speed_x=3.0, speed_y=0.0)
        preds = predict_target("t1", h)
        # Moving in +X direction, predicted X should be greater than current
        current_x = 9 * 3.0  # last recorded x
        assert preds[0].x > current_x

    def test_confidence_decreases_with_horizon(self):
        h = TargetHistory()
        self._make_moving_target(h)
        preds = predict_target("t1", h)
        assert preds[0].confidence > preds[1].confidence
        assert preds[1].confidence > preds[2].confidence

    def test_cone_radius_increases_with_horizon(self):
        h = TargetHistory()
        self._make_moving_target(h)
        preds = predict_target("t1", h)
        assert preds[0].cone_radius_m < preds[1].cone_radius_m
        assert preds[1].cone_radius_m < preds[2].cone_radius_m

    def test_custom_horizons(self):
        h = TargetHistory()
        self._make_moving_target(h)
        preds = predict_target("t1", h, horizons=[2, 10])
        assert len(preds) == 2
        assert preds[0].horizon_minutes == 2
        assert preds[1].horizon_minutes == 10

    def test_speed_reported(self):
        h = TargetHistory()
        self._make_moving_target(h, speed_x=5.0, speed_y=0.0)
        preds = predict_target("t1", h)
        assert preds[0].speed_mps > MIN_SPEED_THRESHOLD


class TestPredictAllTargets:
    """Tests for the predict_all_targets function."""

    def test_multiple_targets(self):
        h = TargetHistory()
        base_t = time.monotonic() - 10
        # Moving target
        for i in range(10):
            h.record("mover", (i * 2.0, i * 1.0), timestamp=base_t + i)
        # Stationary target
        for i in range(10):
            h.record("sitter", (50.0, 50.0), timestamp=base_t + i)

        results = predict_all_targets(["mover", "sitter"], h)
        assert "mover" in results
        assert "sitter" not in results  # stationary, no predictions

    def test_empty_target_list(self):
        h = TargetHistory()
        results = predict_all_targets([], h)
        assert results == {}
