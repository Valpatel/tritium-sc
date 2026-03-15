# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Loader shim for Amy Commander plugin auto-discovery.

PluginManager scans plugins/ for top-level *.py files. This file
re-exports AmyCommanderPlugin so it's discoverable without modifying
the plugin manager's scan logic.

Uses importlib to load from the plugins/amy/ subdirectory directly,
avoiding namespace collision with src/amy/ (the Amy commander source).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_plugin_path = Path(__file__).resolve().parent / "amy" / "plugin.py"
_spec = importlib.util.spec_from_file_location("plugins_amy_plugin", str(_plugin_path))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AmyCommanderPlugin = _mod.AmyCommanderPlugin

__all__ = ["AmyCommanderPlugin"]
