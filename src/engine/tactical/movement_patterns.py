# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.movement_patterns."""

from tritium_lib.tracking.movement_patterns import *  # noqa: F401,F403
from tritium_lib.tracking.movement_patterns import (  # noqa: F401 — explicit re-exports
    DEVIATION_SIGMA,
    LOITER_MIN_DURATION,
    LOITER_RADIUS,
    SPEED_THRESHOLD,
    MovementPattern,
    MovementPatternAnalyzer,
)
