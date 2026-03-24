# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.correlator."""

from tritium_lib.tracking.correlator import *  # noqa: F401,F403
from tritium_lib.tracking.correlator import (  # noqa: F401 — explicit re-exports
    CorrelationRecord,
    DEFAULT_WEIGHTS,
    TargetCorrelator,
    _ASSET_TYPE_TO_NODE,
    _node_type_for,
    start_correlator,
    stop_correlator,
)
