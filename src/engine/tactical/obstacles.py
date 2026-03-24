# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Re-export from tritium-lib."""
from tritium_lib.tracking.obstacles import *  # noqa: F401,F403
from tritium_lib.tracking.obstacles import (  # noqa: F401 — explicit re-exports
    BuildingObstacles,
    _latlng_to_local,
    _segments_intersect,
)
