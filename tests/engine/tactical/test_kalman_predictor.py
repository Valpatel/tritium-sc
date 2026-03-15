# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Kalman filter target prediction."""

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from engine.tactical.target_history import TargetHistory
from engine.tactical.kalman_predictor import (
    kalman_update,
    predict_target_kalman,
    predict_all_targets_kalman,
    clear_kalman_state,
    get_kalman_state,
    KalmanState,
)


@pytest.fixture(autouse=True)
def clean_kalman():
    """Clear Kalman state before each test."""
    clear_kalman_state()
    yield
    clear_kalman_state()


class TestKalmanUpdate:
    def test_first_update_initializes(self):
        state = kalman_update("t1", 10.0, 20.0, 0.0)
        assert state.initialized
        assert state.x == 10.0
        assert state.y == 20.0
        assert state.vx == 0.0
        assert state.vy == 0.0

    def test_velocity_estimation(self):
        """After feeding constant-velocity positions, filter should estimate velocity."""
        # Move at 1 m/s in x direction
        for i in range(10):
            kalman_update("t1", float(i), 0.0, float(i))
        state = get_kalman_state("t1")
        assert state is not None
        # Velocity should be close to 1.0 m/s in x
        assert abs(state.vx - 1.0) < 0.5
        assert abs(state.vy) < 0.5

    def test_reinitialize_after_long_gap(self):
        """If dt > 60s, filter should reinitialize."""
        kalman_update("t1", 0.0, 0.0, 0.0)
        state = kalman_update("t1", 100.0, 100.0, 100.0)
        # Should have reset position
        assert state.x == 100.0
        assert state.y == 100.0
        assert state.vx == 0.0


class TestPredictTargetKalman:
    def test_insufficient_history(self):
        history = TargetHistory()
        history.record("t1", (0.0, 0.0), 0.0)
        preds = predict_target_kalman("t1", history)
        assert preds == []

    def test_stationary_target_no_prediction(self):
        """Stationary targets should return empty predictions."""
        history = TargetHistory()
        for i in range(5):
            history.record("t1", (0.0, 0.0), float(i))
        preds = predict_target_kalman("t1", history)
        assert preds == []

    def test_moving_target_produces_predictions(self):
        """Moving target should produce predictions at each horizon."""
        history = TargetHistory()
        for i in range(10):
            history.record("t1", (float(i * 2), float(i)), float(i))
        preds = predict_target_kalman("t1", history, horizons=[1, 5])
        assert len(preds) == 2
        assert preds[0].horizon_minutes == 1
        assert preds[1].horizon_minutes == 5
        # Further prediction should be farther away
        assert abs(preds[1].x) > abs(preds[0].x)

    def test_prediction_has_confidence(self):
        history = TargetHistory()
        for i in range(10):
            history.record("t1", (float(i), 0.0), float(i))
        preds = predict_target_kalman("t1", history, horizons=[1, 5, 15])
        # Confidence should decrease with horizon
        assert preds[0].confidence > preds[1].confidence
        assert preds[1].confidence > preds[2].confidence

    def test_prediction_has_speed(self):
        history = TargetHistory()
        for i in range(10):
            history.record("t1", (float(i), 0.0), float(i))
        preds = predict_target_kalman("t1", history, horizons=[1])
        assert preds[0].speed_mps > 0

    def test_acceleration_tracking(self):
        """Accelerating target should produce farther predictions than linear."""
        history = TargetHistory()
        # Accelerating: position = 0.5 * a * t^2, with a=0.5
        for i in range(20):
            t = float(i)
            x = 0.25 * t * t  # 0.5 * 0.5 * t^2
            history.record("t_accel", (x, 0.0), t)
        preds = predict_target_kalman("t_accel", history, horizons=[1])
        assert len(preds) == 1
        # Prediction should exist and be forward
        assert preds[0].x > 0


class TestPredictAllTargetsKalman:
    def test_multiple_targets(self):
        history = TargetHistory()
        for i in range(10):
            history.record("t1", (float(i), 0.0), float(i))
            history.record("t2", (0.0, float(i)), float(i))
        results = predict_all_targets_kalman(["t1", "t2"], history)
        assert "t1" in results
        assert "t2" in results


class TestClearKalmanState:
    def test_clear_specific(self):
        kalman_update("t1", 0.0, 0.0, 0.0)
        kalman_update("t2", 0.0, 0.0, 0.0)
        clear_kalman_state("t1")
        assert get_kalman_state("t1") is None
        assert get_kalman_state("t2") is not None

    def test_clear_all(self):
        kalman_update("t1", 0.0, 0.0, 0.0)
        kalman_update("t2", 0.0, 0.0, 0.0)
        clear_kalman_state()
        assert get_kalman_state("t1") is None
        assert get_kalman_state("t2") is None
