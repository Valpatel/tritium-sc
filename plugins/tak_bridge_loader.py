# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Loader shim for PluginManager auto-discovery.

PluginManager scans plugins/ for top-level *.py files. This file
re-exports TAKBridgePlugin so it's discoverable without modifying
the plugin manager's scan logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the plugins/ directory is on sys.path so the tak_bridge
# package can be imported.
_plugins_dir = str(Path(__file__).resolve().parent)
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from tak_bridge.plugin import TAKBridgePlugin  # noqa: E402, F401

__all__ = ["TAKBridgePlugin"]
