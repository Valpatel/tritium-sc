# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""behavior/ package -- modular per-unit-type combat AI.

Re-exports BehaviorCoordinator as the primary entry point.
"""

from .coordinator import BehaviorCoordinator

__all__ = ["BehaviorCoordinator"]
