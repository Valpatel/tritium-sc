# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DifficultyScaler — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.difficulty``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.difficulty import (  # noqa: F401
    DifficultyScaler,
    WaveRecord,
    _MIN_MULTIPLIER,
    _MAX_MULTIPLIER,
    _ADJUSTMENT_STEP,
    _WEIGHT_ELIMINATION,
    _WEIGHT_TIME,
    _WEIGHT_DAMAGE,
    _WEIGHT_ESCAPES,
    _FAST_WAVE_TIME,
    _HARDENED_THRESHOLD,
    _EASY_THRESHOLD,
)

__all__ = [
    "DifficultyScaler",
    "WaveRecord",
]
