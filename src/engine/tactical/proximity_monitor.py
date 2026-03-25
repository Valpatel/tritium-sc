# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ProximityMonitor — shim that re-exports from tritium-lib.

The canonical implementation now lives in tritium_lib.tracking.proximity_monitor.
This module exists for backwards compatibility with existing SC imports.
"""

import os
from pathlib import Path

from tritium_lib.tracking.proximity_monitor import ProximityMonitor  # noqa: F401

# Also re-export the model types that SC code imports from here
try:
    from tritium_lib.models.proximity import (  # noqa: F401
        ProximityAlert,
        ProximityRule,
        classify_proximity_severity,
        DEFAULT_PROXIMITY_RULES,
    )
except ImportError:
    # Fallback: get them from the lib tracking module's own fallbacks
    from tritium_lib.tracking.proximity_monitor import (  # type: ignore[attr-defined]  # noqa: F401
        ProximityAlert,
        ProximityRule,
        classify_proximity_severity,
        DEFAULT_PROXIMITY_RULES,
    )

# Backwards-compatible module-level _DATA_DIR used by existing SC tests
_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "proximity"
