# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetPrediction — predict future target positions from movement history.

Uses the TargetHistory ring buffer to fit a linear velocity model and
extrapolate position at 1, 5, and 15 minute horizons.  Returns predicted
positions with confidence cones that widen over time.

The prediction is intentionally simple (linear extrapolation from recent
velocity) to keep compute low enough for real-time use.  Future enhancements
could add Kalman filtering or trajectory clustering.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .target_history import TargetHistory


@dataclass(slots=True)
class PredictedPosition:
    """A single predicted future position with uncertainty cone."""

    x: float
    y: float
    horizon_minutes: int       # 1, 5, or 15
    confidence: float          # 0.0 to 1.0 (decays with horizon)
    cone_radius_m: float       # uncertainty radius in meters
    heading_deg: float = 0.0   # predicted heading (compass, 0=north)
    speed_mps: float = 0.0     # predicted speed in m/s

    def to_dict(self) -> dict:
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "horizon_minutes": self.horizon_minutes,
            "confidence": round(self.confidence, 3),
            "cone_radius_m": round(self.cone_radius_m, 1),
            "heading_deg": round(self.heading_deg, 1),
            "speed_mps": round(self.speed_mps, 2),
        }


# Default prediction horizons in minutes
DEFAULT_HORIZONS = [1, 5, 15]

# Minimum speed (m/s) to consider a target "moving" for prediction
MIN_SPEED_THRESHOLD = 0.3

# Base confidence for a 1-minute prediction (decays with horizon)
BASE_CONFIDENCE = 0.85

# Cone radius growth rate per minute (meters)
CONE_GROWTH_RATE = 10.0

# Cone radius scaling based on RL model confidence:
#   high model confidence (>0.7) -> tighter cones (0.6x)
#   low model confidence (<0.3) -> wider cones (1.8x)
CONE_SCALE_HIGH_CONF = 0.6
CONE_SCALE_LOW_CONF = 1.8

# Minimum number of history samples needed for prediction
MIN_SAMPLES = 3

# Time window for velocity estimation (seconds)
VELOCITY_WINDOW_S = 60.0


def _get_rl_cone_scale(target_id: str) -> float:
    """Get prediction cone scale factor from the RL correlation model.

    Higher model confidence in a target's correlation = tighter cones,
    because the system is more certain of the target's identity and
    thus its movement pattern. Lower confidence = wider uncertainty.

    Returns:
        Scale factor for cone_radius_m (0.6 to 1.8).
    """
    try:
        from engine.intelligence.correlation_learner import get_correlation_learner
        learner = get_correlation_learner()
        if not learner.is_trained:
            return 1.0

        # Use model accuracy as a proxy for overall system confidence
        # High accuracy = model is reliable = tighter cones
        accuracy = learner.accuracy
        if accuracy >= 0.7:
            # High confidence: scale down cones
            # 0.7 accuracy -> 1.0x, 1.0 accuracy -> 0.6x
            t = (accuracy - 0.7) / 0.3
            return CONE_SCALE_HIGH_CONF + (1.0 - CONE_SCALE_HIGH_CONF) * (1.0 - t)
        elif accuracy < 0.3:
            # Low confidence: scale up cones
            # 0.3 accuracy -> 1.0x, 0.0 accuracy -> 1.8x
            t = (0.3 - accuracy) / 0.3
            return 1.0 + (CONE_SCALE_LOW_CONF - 1.0) * t
        else:
            return 1.0
    except Exception:
        return 1.0


def predict_target(
    target_id: str,
    history: TargetHistory,
    horizons: list[int] | None = None,
    sample_count: int = 10,
    rl_weighted: bool = True,
) -> list[PredictedPosition]:
    """Predict future positions for a target based on movement history.

    Uses the most recent ``sample_count`` position records to estimate
    velocity, then extrapolates linearly for each horizon.

    When ``rl_weighted`` is True (default), cone sizes are scaled by the
    RL correlation model's confidence. High model accuracy = tighter
    prediction cones. Low accuracy = wider uncertainty cones.

    Args:
        target_id: The target to predict.
        history: TargetHistory instance with recorded positions.
        horizons: List of prediction horizons in minutes (default [1, 5, 15]).
        sample_count: Number of recent samples to use for velocity estimation.
        rl_weighted: Apply RL model confidence to cone sizing.

    Returns:
        List of PredictedPosition for each horizon, or empty if the
        target has insufficient history or is stationary.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    trail = history.get_trail(target_id, max_points=sample_count)
    if len(trail) < MIN_SAMPLES:
        return []

    # Extract positions and timestamps
    positions = [(x, y, t) for x, y, t in trail]

    # Use only recent positions within the velocity window
    now = positions[-1][2]
    cutoff = now - VELOCITY_WINDOW_S
    recent = [(x, y, t) for x, y, t in positions if t >= cutoff]
    if len(recent) < 2:
        recent = positions[-2:]  # fallback to last 2

    # Compute velocity from recent positions
    x0, y0, t0 = recent[0]
    x1, y1, t1 = recent[-1]
    dt = t1 - t0
    if dt <= 0:
        return []

    vx = (x1 - x0) / dt  # m/s in x
    vy = (y1 - y0) / dt  # m/s in y
    speed = math.hypot(vx, vy)

    if speed < MIN_SPEED_THRESHOLD:
        return []

    # Compute heading (0=north/+Y, clockwise)
    heading = math.degrees(math.atan2(vx, vy)) % 360

    # Current position (latest)
    cx, cy = x1, y1

    # Get RL model confidence scale factor for cone sizing
    rl_scale = _get_rl_cone_scale(target_id) if rl_weighted else 1.0

    # Generate predictions for each horizon
    predictions = []
    for h_min in horizons:
        dt_s = h_min * 60.0
        pred_x = cx + vx * dt_s
        pred_y = cy + vy * dt_s

        # Confidence decays with horizon
        confidence = BASE_CONFIDENCE * math.exp(-0.1 * h_min)
        confidence = max(0.05, confidence)

        # Cone radius grows with horizon, scaled by RL confidence
        cone_radius = CONE_GROWTH_RATE * h_min * rl_scale

        # Additional uncertainty from velocity noise
        # (use variance in recent velocity samples as proxy)
        if len(recent) >= 3:
            vx_samples = []
            for i in range(1, len(recent)):
                dt_i = recent[i][2] - recent[i - 1][2]
                if dt_i > 0:
                    vx_samples.append(
                        math.hypot(
                            recent[i][0] - recent[i - 1][0],
                            recent[i][1] - recent[i - 1][1],
                        ) / dt_i
                    )
            if vx_samples:
                mean_v = sum(vx_samples) / len(vx_samples)
                variance = sum((v - mean_v) ** 2 for v in vx_samples) / len(vx_samples)
                std_dev = math.sqrt(variance)
                cone_radius += std_dev * dt_s * 0.5

        predictions.append(PredictedPosition(
            x=pred_x,
            y=pred_y,
            horizon_minutes=h_min,
            confidence=confidence,
            cone_radius_m=cone_radius,
            heading_deg=heading,
            speed_mps=speed,
        ))

    return predictions


def predict_all_targets(
    target_ids: list[str],
    history: TargetHistory,
    horizons: list[int] | None = None,
) -> dict[str, list[PredictedPosition]]:
    """Predict future positions for multiple targets.

    Args:
        target_ids: List of target IDs to predict.
        history: TargetHistory instance.
        horizons: Prediction horizons in minutes.

    Returns:
        Dict mapping target_id -> list of PredictedPosition.
        Only includes targets with valid predictions (moving targets).
    """
    results: dict[str, list[PredictedPosition]] = {}
    for tid in target_ids:
        preds = predict_target(tid, history, horizons=horizons)
        if preds:
            results[tid] = preds
    return results
