# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""PursuitSystem — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.pursuit``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.world.pursuit import (  # noqa: F401
    PursuitSystem,
)

__all__ = [
    "PursuitSystem",
]
