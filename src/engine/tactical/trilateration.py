# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.trilateration."""

from tritium_lib.tracking.trilateration import *  # noqa: F401,F403
from tritium_lib.tracking.trilateration import (  # noqa: F401 — explicit re-exports
    DEFAULT_MIN_ANCHORS,
    DEFAULT_STALE_THRESHOLD,
    DEFAULT_WINDOW,
    PositionResult,
    Sighting,
    TrilaterationEngine,
)
