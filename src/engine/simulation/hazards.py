# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HazardManager — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.hazards``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.world.hazards import (  # noqa: F401
    Hazard,
    HazardManager,
    HAZARD_TYPES,
)

__all__ = [
    "Hazard",
    "HazardManager",
    "HAZARD_TYPES",
]
