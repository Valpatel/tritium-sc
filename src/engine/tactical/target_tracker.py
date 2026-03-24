# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Re-export from tritium-lib. SC shim for backward compatibility."""
from tritium_lib.tracking.target_tracker import *  # noqa: F401,F403
from tritium_lib.tracking.target_tracker import (  # noqa: F401 — explicit re-exports
    TrackedTarget,
    TargetTracker,
    _decayed_confidence,
    _HALF_LIVES,
    _MIN_CONFIDENCE,
    _LN2,
    _MULTI_SOURCE_BOOST,
    _MAX_BOOSTED_CONFIDENCE,
    _MAX_PLAUSIBLE_SPEED_MPS,
    _TELEPORT_FLAG_COOLDOWN,
)
