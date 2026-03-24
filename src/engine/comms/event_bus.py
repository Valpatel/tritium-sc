# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""EventBus shim — delegates to tritium-lib's QueueEventBus.

All 37+ SC files import ``from engine.comms.event_bus import EventBus``.
This module re-exports ``QueueEventBus`` under the name ``EventBus``
so that every existing import continues to work unchanged.
"""

from tritium_lib.events.bus import QueueEventBus as EventBus

__all__ = ["EventBus"]
