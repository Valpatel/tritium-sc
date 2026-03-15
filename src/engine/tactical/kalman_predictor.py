# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Kalman filter predictor — replaces linear extrapolation with a proper
state estimator that accounts for velocity changes and turning.

State vector: [x, y, vx, vy, ax, ay] (position, velocity, acceleration)
Measurement: [x, y] (observed position)

The filter smooths noisy position data and produces better predictions for
targets that accelerate, decelerate, or turn (e.g., vehicles stopping at
intersections, then proceeding).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .target_history import TargetHistory
from .target_prediction import (
    PredictedPosition,
    DEFAULT_HORIZONS,
    MIN_SPEED_THRESHOLD,
    BASE_CONFIDENCE,
    CONE_GROWTH_RATE,
    MIN_SAMPLES,
    _get_rl_cone_scale,
)


@dataclass(slots=True)
class KalmanState:
    """Internal Kalman filter state for a single target."""

    # State vector: [x, y, vx, vy, ax, ay]
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    ax: float = 0.0
    ay: float = 0.0

    # Diagonal of the 6x6 covariance matrix (simplified)
    p_x: float = 100.0
    p_y: float = 100.0
    p_vx: float = 10.0
    p_vy: float = 10.0
    p_ax: float = 1.0
    p_ay: float = 1.0

    last_update: float = 0.0
    initialized: bool = False


# Process noise (how much we expect state to change per second)
Q_POS = 0.1       # Position process noise
Q_VEL = 1.0       # Velocity process noise
Q_ACC = 5.0       # Acceleration process noise (high: allows quick turns)

# Measurement noise (how noisy position observations are)
R_POS = 2.0       # Position measurement noise (meters)

# Acceleration damping factor — pulls acceleration toward zero over time
# Prevents runaway acceleration predictions
ACC_DECAY = 0.9   # per-second decay (0.9 = 10% decay per second)

# Cache of Kalman states per target
_kalman_states: dict[str, KalmanState] = {}


def _get_or_create_state(target_id: str) -> KalmanState:
    if target_id not in _kalman_states:
        _kalman_states[target_id] = KalmanState()
    return _kalman_states[target_id]


def kalman_update(
    target_id: str,
    x: float,
    y: float,
    timestamp: float | None = None,
) -> KalmanState:
    """Feed a new position measurement into the Kalman filter.

    Call this every time a target position is observed. The filter will
    smooth the measurement and update velocity/acceleration estimates.

    Args:
        target_id: Target being tracked.
        x: Observed x position (meters).
        y: Observed y position (meters).
        timestamp: Observation time (monotonic seconds). Defaults to time.monotonic().

    Returns:
        Updated KalmanState.
    """
    if timestamp is None:
        timestamp = time.monotonic()

    state = _get_or_create_state(target_id)

    if not state.initialized:
        state.x = x
        state.y = y
        state.vx = 0.0
        state.vy = 0.0
        state.ax = 0.0
        state.ay = 0.0
        state.last_update = timestamp
        state.initialized = True
        return state

    dt = timestamp - state.last_update
    if dt <= 0:
        return state
    if dt > 60.0:
        # Too long since last update — reinitialize
        state.x = x
        state.y = y
        state.vx = 0.0
        state.vy = 0.0
        state.ax = 0.0
        state.ay = 0.0
        state.last_update = timestamp
        return state

    # --- Predict step ---
    # State transition: x' = x + vx*dt + 0.5*ax*dt^2, etc.
    dt2 = 0.5 * dt * dt
    pred_x = state.x + state.vx * dt + state.ax * dt2
    pred_y = state.y + state.vy * dt + state.ay * dt2
    pred_vx = state.vx + state.ax * dt
    pred_vy = state.vy + state.ay * dt
    # Decay acceleration toward zero
    decay = ACC_DECAY ** dt
    pred_ax = state.ax * decay
    pred_ay = state.ay * decay

    # Predicted covariance (simplified diagonal, no cross-terms)
    pp_x = state.p_x + state.p_vx * dt * dt + Q_POS * dt
    pp_y = state.p_y + state.p_vy * dt * dt + Q_POS * dt
    pp_vx = state.p_vx + Q_VEL * dt
    pp_vy = state.p_vy + Q_VEL * dt
    pp_ax = state.p_ax + Q_ACC * dt
    pp_ay = state.p_ay + Q_ACC * dt

    # --- Update step ---
    # Innovation: difference between measurement and prediction
    innov_x = x - pred_x
    innov_y = y - pred_y

    # Innovation covariance
    s_x = pp_x + R_POS
    s_y = pp_y + R_POS

    # Kalman gains — position gain directly, velocity/accel inferred
    k_x = pp_x / s_x
    k_y = pp_y / s_y

    # Velocity gain: innovation / dt gives velocity correction
    # Use a moderate gain to avoid oscillation
    alpha_v = 0.3  # velocity learning rate
    alpha_a = 0.1  # acceleration learning rate

    # State update
    state.x = pred_x + k_x * innov_x
    state.y = pred_y + k_y * innov_y

    # Velocity correction from position innovation
    if dt > 0.01:
        state.vx = pred_vx + alpha_v * innov_x / dt
        state.vy = pred_vy + alpha_v * innov_y / dt
        # Acceleration estimated from velocity change
        dv_x = state.vx - (state.x - pred_x) / dt if dt > 0.1 else 0.0
        state.ax = pred_ax + alpha_a * innov_x / (dt * dt)
        state.ay = pred_ay + alpha_a * innov_y / (dt * dt)
    else:
        state.vx = pred_vx
        state.vy = pred_vy
        state.ax = pred_ax
        state.ay = pred_ay

    # Clamp acceleration to reasonable bounds (10 m/s^2 ~ 1g)
    max_acc = 10.0
    state.ax = max(-max_acc, min(max_acc, state.ax))
    state.ay = max(-max_acc, min(max_acc, state.ay))

    # Covariance update (simplified)
    state.p_x = (1.0 - k_x) * pp_x
    state.p_y = (1.0 - k_y) * pp_y
    state.p_vx = pp_vx * 0.95  # slow convergence
    state.p_vy = pp_vy * 0.95
    state.p_ax = pp_ax * 0.98
    state.p_ay = pp_ay * 0.98

    state.last_update = timestamp
    return state


def predict_target_kalman(
    target_id: str,
    history: TargetHistory,
    horizons: list[int] | None = None,
    sample_count: int = 20,
    rl_weighted: bool = True,
) -> list[PredictedPosition]:
    """Predict future positions using Kalman filter state estimation.

    This replaces the simple linear extrapolation with a filter that tracks
    velocity AND acceleration, producing better predictions for targets that
    stop at intersections, turn, or change speed.

    Args:
        target_id: Target to predict.
        history: TargetHistory with position records.
        horizons: Prediction horizons in minutes (default [1, 5, 15]).
        sample_count: Number of recent samples to feed the filter.
        rl_weighted: Scale cones by RL model confidence.

    Returns:
        List of PredictedPosition for each horizon, or empty if insufficient data.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    trail = history.get_trail(target_id, max_points=sample_count)
    if len(trail) < MIN_SAMPLES:
        return []

    # Feed all trail positions into the Kalman filter
    state = _get_or_create_state(target_id)
    if not state.initialized:
        # Bootstrap from all history
        for x, y, t in trail:
            kalman_update(target_id, x, y, t)
    else:
        # Only feed the most recent position if filter is already running
        x, y, t = trail[-1]
        kalman_update(target_id, x, y, t)

    state = _kalman_states[target_id]

    # Check speed
    speed = math.hypot(state.vx, state.vy)
    if speed < MIN_SPEED_THRESHOLD:
        return []

    # Heading from velocity (0=north/+Y, clockwise)
    heading = math.degrees(math.atan2(state.vx, state.vy)) % 360

    # Get RL confidence scale
    rl_scale = _get_rl_cone_scale(target_id) if rl_weighted else 1.0

    # Generate predictions using Kalman state (with acceleration)
    predictions = []
    for h_min in horizons:
        dt_s = h_min * 60.0
        dt2 = 0.5 * dt_s * dt_s

        # Predict with acceleration (but decay it over time)
        # Acceleration contribution is damped: integral of a*decay^t
        if abs(1.0 - ACC_DECAY) > 1e-9:
            ln_decay = math.log(ACC_DECAY)
            # integral of decay^t from 0 to dt_s = (decay^dt_s - 1) / ln(decay)
            decay_integral = (ACC_DECAY ** dt_s - 1.0) / ln_decay
            # double integral = (decay^dt_s - 1 - ln_decay * dt_s) / ln_decay^2
            decay_double_integral = (
                (ACC_DECAY ** dt_s - 1.0) / ln_decay - dt_s
            ) / ln_decay
        else:
            decay_integral = dt_s
            decay_double_integral = dt2

        pred_x = state.x + state.vx * dt_s + state.ax * decay_double_integral
        pred_y = state.y + state.vy * dt_s + state.ay * decay_double_integral

        # Predicted velocity at horizon
        decay_at_t = ACC_DECAY ** dt_s
        pred_vx = state.vx + state.ax * decay_integral
        pred_vy = state.vy + state.ay * decay_integral
        pred_speed = math.hypot(pred_vx, pred_vy)

        # Confidence decays with horizon, but slower than linear model
        # because Kalman filter accounts for dynamics
        confidence = BASE_CONFIDENCE * math.exp(-0.08 * h_min)
        confidence = max(0.05, confidence)

        # Cone radius: base growth + covariance contribution
        # Kalman covariance tells us actual uncertainty
        cov_scale = math.sqrt(state.p_x + state.p_y) * dt_s * 0.1
        cone_radius = (CONE_GROWTH_RATE * 0.7 * h_min + cov_scale) * rl_scale

        predictions.append(PredictedPosition(
            x=pred_x,
            y=pred_y,
            horizon_minutes=h_min,
            confidence=confidence,
            cone_radius_m=cone_radius,
            heading_deg=heading,
            speed_mps=pred_speed,
        ))

    return predictions


def predict_all_targets_kalman(
    target_ids: list[str],
    history: TargetHistory,
    horizons: list[int] | None = None,
) -> dict[str, list[PredictedPosition]]:
    """Predict future positions for multiple targets using Kalman filter.

    Args:
        target_ids: List of target IDs.
        history: TargetHistory instance.
        horizons: Prediction horizons in minutes.

    Returns:
        Dict mapping target_id -> list of PredictedPosition.
    """
    results: dict[str, list[PredictedPosition]] = {}
    for tid in target_ids:
        preds = predict_target_kalman(tid, history, horizons=horizons)
        if preds:
            results[tid] = preds
    return results


def clear_kalman_state(target_id: str | None = None) -> None:
    """Clear Kalman filter state for a target or all targets."""
    if target_id is None:
        _kalman_states.clear()
    else:
        _kalman_states.pop(target_id, None)


def get_kalman_state(target_id: str) -> KalmanState | None:
    """Get the current Kalman state for a target (for debugging/display)."""
    return _kalman_states.get(target_id)
