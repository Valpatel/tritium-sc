# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.convoy_detector."""

from tritium_lib.tracking.convoy_detector import *  # noqa: F401,F403
from tritium_lib.tracking.convoy_detector import (  # noqa: F401 — explicit re-exports
    ANALYSIS_INTERVAL_S,
    CONVOY_TIMEOUT_S,
    HEADING_TOLERANCE_DEG,
    MAX_CONVOY_SPREAD_M,
    MIN_CONVOY_MEMBERS,
    MIN_SPEED_MPS,
    SPEED_TOLERANCE_MPS,
    ConvoyDetector,
    TargetMotion,
)
