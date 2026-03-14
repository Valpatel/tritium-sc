# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Conftest for plugin tests — add plugins/ to sys.path."""

import sys
from pathlib import Path

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)
