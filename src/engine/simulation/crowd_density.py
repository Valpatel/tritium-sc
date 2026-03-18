# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CrowdDensityTracker — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.crowd_density``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.crowd_density import (  # noqa: F401
    CrowdDensityTracker,
    _classify,
    _SPARSE_MAX,
    _MODERATE_MAX,
    _DENSE_MAX,
    _SPARSE,
    _MODERATE,
    _DENSE,
    _CRITICAL,
    _PUBLISH_INTERVAL,
)

__all__ = [
    "CrowdDensityTracker",
]
