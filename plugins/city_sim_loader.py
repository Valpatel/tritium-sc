# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Loader shim for PluginManager auto-discovery."""
from __future__ import annotations

import sys
from pathlib import Path

_plugins_dir = str(Path(__file__).resolve().parent)
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from city_sim.plugin import CitySimPlugin  # noqa: E402, F401

__all__ = ["CitySimPlugin"]
