# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""UnitComms — re-export from tritium-lib.

The canonical implementation now lives in
``tritium_lib.sim_engine.world.comms``.  This wrapper preserves the
original import paths so existing SC code continues to work unchanged.
"""

from tritium_lib.sim_engine.world.comms import (  # noqa: F401
    Signal,
    Message,
    UnitComms,
    SIGNAL_DISTRESS,
    SIGNAL_CONTACT,
    SIGNAL_REGROUP,
    SIGNAL_INSTIGATOR_MARKED,
    SIGNAL_EMP_JAMMING,
    _DEFAULT_RANGE,
    _DEFAULT_TTL,
)

__all__ = [
    "Signal",
    "Message",
    "UnitComms",
    "SIGNAL_DISTRESS",
    "SIGNAL_CONTACT",
    "SIGNAL_REGROUP",
    "SIGNAL_INSTIGATOR_MARKED",
    "SIGNAL_EMP_JAMMING",
]
