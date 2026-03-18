# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MoraleSystem — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.morale``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.morale import (  # noqa: F401
    MoraleSystem,
    DEFAULT_MORALE,
    BROKEN_THRESHOLD,
    SUPPRESSED_THRESHOLD,
    EMBOLDENED_THRESHOLD,
)

__all__ = [
    "MoraleSystem",
    "DEFAULT_MORALE",
    "BROKEN_THRESHOLD",
    "SUPPRESSED_THRESHOLD",
    "EMBOLDENED_THRESHOLD",
]
