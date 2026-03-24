# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.correlation_strategies."""

from tritium_lib.tracking.correlation_strategies import *  # noqa: F401,F403
from tritium_lib.tracking.correlation_strategies import (  # noqa: F401 — explicit re-exports
    CorrelationStrategy,
    DossierStrategy,
    SignalPatternStrategy,
    SpatialStrategy,
    StrategyScore,
    TemporalStrategy,
    WiFiProbeStrategy,
)
