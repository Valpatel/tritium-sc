# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Camera discovery and NVR integration."""

from app.discovery.nvr import NVRClient, discover_cameras

__all__ = ["NVRClient", "discover_cameras"]
