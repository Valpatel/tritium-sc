# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Engine — system infrastructure for TRITIUM-SC.

This package contains the simulation engine, communication primitives,
tactical systems, sensor nodes, unit registry, audio, inference routing,
perception pipeline, action dispatch, scenarios, and synthetic media.

Commanders (Amy, Bob, etc.) are plugins that implement CommanderProtocol
and use engine subsystems to operate.
"""

__version__ = "0.1.0"
