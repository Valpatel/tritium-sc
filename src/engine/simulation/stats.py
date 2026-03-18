# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""StatsTracker — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.stats``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.stats import (  # noqa: F401
    StatsTracker,
    UnitStats,
    WaveStats,
)

__all__ = [
    "StatsTracker",
    "UnitStats",
    "WaveStats",
]
