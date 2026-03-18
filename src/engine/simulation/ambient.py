# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AmbientSpawner — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.game.ambient``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.game.ambient import (  # noqa: F401
    AmbientSpawner,
    _generate_street_grid,
    _snap_to_nearest_street,
    _street_path,
    _hour_activity,
    _DEFAULT_MAP_BOUNDS,
    _STREET_JITTER,
    _STREET_SPACING,
    _NEIGHBOR_NAMES,
    _CAR_NAMES,
    _DOG_NAMES,
    _CAT_NAMES,
    _DELIVERY_NAMES,
)

__all__ = [
    "AmbientSpawner",
    "_generate_street_grid",
    "_hour_activity",
]
