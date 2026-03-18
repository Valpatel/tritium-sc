# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GameMode — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.game_mode``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.game_mode import (  # noqa: F401
    GameMode,
    InfiniteWaveMode,
    InstigatorDetector,
    WaveConfig,
    WAVE_CONFIGS,
    _SPAWN_STAGGER,
    _WAVE_ADVANCE_DELAY,
    _COUNTDOWN_DURATION,
    _STALEMATE_TIMEOUT,
)

__all__ = [
    "GameMode",
    "InfiniteWaveMode",
    "InstigatorDetector",
    "WaveConfig",
    "WAVE_CONFIGS",
]
