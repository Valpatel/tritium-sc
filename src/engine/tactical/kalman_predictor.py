# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.kalman_predictor."""

from tritium_lib.tracking.kalman_predictor import *  # noqa: F401,F403
from tritium_lib.tracking.kalman_predictor import (  # noqa: F401 — explicit re-exports
    ACC_DECAY,
    KalmanState,
    Q_ACC,
    Q_POS,
    Q_VEL,
    R_POS,
    clear_kalman_state,
    get_kalman_state,
    kalman_update,
    predict_all_targets_kalman,
    predict_target_kalman,
)
