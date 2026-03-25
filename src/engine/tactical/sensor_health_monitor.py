# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SensorHealthMonitor — shim that re-exports from tritium-lib.

The canonical implementation now lives in tritium_lib.tracking.sensor_health_monitor.
This module exists for backwards compatibility with existing SC imports.
"""

from tritium_lib.tracking.sensor_health_monitor import SensorHealthMonitor  # noqa: F401
