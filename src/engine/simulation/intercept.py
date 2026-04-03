# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Intercept prediction — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.intercept``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.world.intercept import (  # noqa: F401
    predict_intercept,
    lead_target,
    time_to_intercept,
    target_velocity,
    _UNCATCHABLE_TIME,
    _solve_intercept_time,
)

__all__ = [
    "predict_intercept",
    "lead_target",
    "time_to_intercept",
    "target_velocity",
]
