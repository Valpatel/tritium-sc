# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.target_prediction."""

from tritium_lib.tracking.target_prediction import *  # noqa: F401,F403
from tritium_lib.tracking.target_prediction import (  # noqa: F401 — explicit re-exports
    BASE_CONFIDENCE,
    CONE_GROWTH_RATE,
    CONE_SCALE_HIGH_CONF,
    CONE_SCALE_LOW_CONF,
    DEFAULT_HORIZONS,
    MIN_SAMPLES,
    MIN_SPEED_THRESHOLD,
    VELOCITY_WINDOW_S,
    PredictedPosition,
    predict_all_targets,
    predict_target,
)
