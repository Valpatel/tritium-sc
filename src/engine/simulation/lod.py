# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LODSystem — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.lod``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.world.lod import (  # noqa: F401
    LODSystem,
    LODTier,
    ViewportState,
    TIER_TICK_DIVISOR,
    TIER_IDLE_THRESHOLD,
    TIER_TELEMETRY_DIVISOR,
)

__all__ = [
    "LODSystem",
    "LODTier",
    "ViewportState",
    "TIER_TICK_DIVISOR",
    "TIER_IDLE_THRESHOLD",
    "TIER_TELEMETRY_DIVISOR",
]
