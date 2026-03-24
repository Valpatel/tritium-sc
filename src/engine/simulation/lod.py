# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Level of Detail (LOD) system for simulation fidelity scaling.

Architecture
------------
The LOD system reduces simulation fidelity for entities that are far from
the player's current viewport.  This allows the world to be densely
populated across a large area (400m+ radius) without wasting CPU on
full-fidelity ticks for entities the player cannot see.

Three LOD tiers:

  FULL (tier 0)   — within the viewport.  Tick every frame (10Hz), full
                     behavior AI, full combat, full telemetry.
  MEDIUM (tier 1) — nearby but offscreen (within 2x viewport radius).
                     Tick every 3rd frame (~3.3Hz), simplified behaviors,
                     combat still active.
  LOW (tier 2)    — far away (beyond 2x viewport radius).  Tick every
                     10th frame (1Hz), movement only (waypoint following),
                     no AI decisions, minimal telemetry.

The viewport is reported by the frontend via WebSocket messages.  When no
viewport has been reported, all targets default to FULL fidelity (backward
compatible -- no performance regression if the frontend doesn't send
viewport updates).

Distance calculation uses the local coordinate system (meters from map
center), NOT lat/lng.  The frontend converts its MapLibre viewport center
to local coords before sending.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tritium_lib.sim_engine.core.entity import SimulationTarget


class LODTier(IntEnum):
    """Fidelity tiers for simulation targets."""
    FULL = 0    # Within viewport -- 10Hz, full AI
    MEDIUM = 1  # Nearby offscreen -- ~3Hz, simplified AI
    LOW = 2     # Far away -- 1Hz, movement only


# Tick divisors: at 10Hz base rate, how often each tier ticks
# FULL ticks every frame, MEDIUM every 3rd, LOW every 10th
TIER_TICK_DIVISOR: dict[LODTier, int] = {
    LODTier.FULL: 1,
    LODTier.MEDIUM: 3,
    LODTier.LOW: 10,
}

# Telemetry throttle: idle tick threshold before throttling
# FULL uses the existing 5-tick idle threshold.
# MEDIUM and LOW throttle more aggressively.
TIER_IDLE_THRESHOLD: dict[LODTier, int] = {
    LODTier.FULL: 5,
    LODTier.MEDIUM: 2,
    LODTier.LOW: 1,
}

# Telemetry publish divisor: how often to publish even for idle units
TIER_TELEMETRY_DIVISOR: dict[LODTier, int] = {
    LODTier.FULL: 5,    # Idle FULL units publish at 2Hz
    LODTier.MEDIUM: 10,  # Idle MEDIUM units publish at 1Hz
    LODTier.LOW: 30,     # Idle LOW units publish at ~0.33Hz
}


@dataclass
class ViewportState:
    """Current viewport as reported by the frontend.

    center_x, center_y: local coordinates (meters from map origin).
    radius: approximate visible radius in meters.  Computed from zoom
            level and screen size, but a reasonable default (150m) is
            used until the frontend reports.
    """
    center_x: float = 0.0
    center_y: float = 0.0
    radius: float = 150.0  # Default: show ~300m diameter at zoom 16
    zoom: float = 16.0
    _set: bool = False      # True once frontend has sent at least one update


class LODSystem:
    """Computes and caches LOD tiers for simulation targets.

    Thread-safe: viewport updates come from the async WS handler while
    tier lookups happen on the sim-tick thread.
    """

    # Tier distance thresholds (multiplied by viewport radius)
    FULL_RADIUS_MULT = 1.2   # Within 1.2x viewport radius = FULL
    MEDIUM_RADIUS_MULT = 3.0  # Within 3x viewport radius = MEDIUM
    # Beyond 3x = LOW

    def __init__(self) -> None:
        self._viewport = ViewportState()
        self._lock = threading.Lock()
        # Cache: target_id -> LODTier (rebuilt each tick)
        self._tiers: dict[str, LODTier] = {}

    @property
    def viewport(self) -> ViewportState:
        """Current viewport state (read-only snapshot)."""
        with self._lock:
            return ViewportState(
                center_x=self._viewport.center_x,
                center_y=self._viewport.center_y,
                radius=self._viewport.radius,
                zoom=self._viewport.zoom,
                _set=self._viewport._set,
            )

    @property
    def has_viewport(self) -> bool:
        """True if the frontend has sent at least one viewport update."""
        with self._lock:
            return self._viewport._set

    def update_viewport(
        self,
        center_x: float,
        center_y: float,
        radius: float | None = None,
        zoom: float | None = None,
    ) -> None:
        """Update viewport from frontend.

        Args:
            center_x: X in local coords (meters from map origin).
            center_y: Y in local coords.
            radius: Visible radius in meters.  If None, estimated from zoom.
            zoom: MapLibre zoom level (used to estimate radius if not given).
        """
        with self._lock:
            self._viewport.center_x = center_x
            self._viewport.center_y = center_y
            self._viewport._set = True
            if zoom is not None:
                self._viewport.zoom = zoom
            if radius is not None:
                self._viewport.radius = max(10.0, radius)
            elif zoom is not None:
                # Estimate visible radius from zoom level.
                # At zoom 16, ~300m visible on a typical screen.
                # Each zoom level halves the visible area.
                self._viewport.radius = max(10.0, 300.0 * (2.0 ** (16.0 - zoom)))

    def compute_tier(self, target: SimulationTarget) -> LODTier:
        """Compute LOD tier for a single target based on viewport distance.

        If no viewport has been set, returns FULL (backward compatible).
        Combatants (friendly or hostile) in active game are always at least
        MEDIUM to keep combat responsive even offscreen.
        """
        with self._lock:
            if not self._viewport._set:
                return LODTier.FULL
            cx = self._viewport.center_x
            cy = self._viewport.center_y
            vr = self._viewport.radius

        dx = target.position[0] - cx
        dy = target.position[1] - cy
        dist = math.sqrt(dx * dx + dy * dy)

        full_dist = vr * self.FULL_RADIUS_MULT
        medium_dist = vr * self.MEDIUM_RADIUS_MULT

        if dist <= full_dist:
            return LODTier.FULL
        elif dist <= medium_dist:
            return LODTier.MEDIUM
        else:
            # Combatants are never lower than MEDIUM -- keeps combat
            # responsive even when offscreen (explosions, kills still
            # happen on time).
            if target.is_combatant and target.alliance != "neutral":
                return LODTier.MEDIUM
            return LODTier.LOW

    def compute_tiers(
        self, targets: dict[str, SimulationTarget]
    ) -> dict[str, LODTier]:
        """Compute LOD tiers for all targets. Caches result.

        Returns dict of target_id -> LODTier.
        """
        tiers: dict[str, LODTier] = {}
        for tid, t in targets.items():
            tiers[tid] = self.compute_tier(t)
        self._tiers = tiers
        return tiers

    def get_tier(self, target_id: str) -> LODTier:
        """Get cached tier for a target. Returns FULL if not computed yet."""
        return self._tiers.get(target_id, LODTier.FULL)

    def should_tick(self, target_id: str, tick_counter: int) -> bool:
        """Return True if this target should be ticked this frame.

        Uses the cached tier and tick_counter modulo the tier's divisor.
        """
        tier = self.get_tier(target_id)
        divisor = TIER_TICK_DIVISOR[tier]
        return (tick_counter % divisor) == 0

    def should_run_behaviors(self, target_id: str, tick_counter: int) -> bool:
        """Return True if behavior AI should run for this target this frame.

        FULL: every tick.
        MEDIUM: every 3rd tick.
        LOW: never (movement only).
        """
        tier = self.get_tier(target_id)
        if tier == LODTier.LOW:
            return False
        divisor = TIER_TICK_DIVISOR[tier]
        return (tick_counter % divisor) == 0

    def should_publish_telemetry(
        self, target_id: str, tick_counter: int, idle_ticks: int
    ) -> bool:
        """Return True if telemetry should be published for this target.

        Combines LOD tier throttling with idle-unit throttling.
        Active (non-idle) targets always publish on their tier's tick.
        Idle targets use the tier's telemetry divisor.
        """
        tier = self.get_tier(target_id)
        threshold = TIER_IDLE_THRESHOLD[tier]

        if idle_ticks < threshold:
            # Not idle yet -- publish on every tier tick
            divisor = TIER_TICK_DIVISOR[tier]
            return (tick_counter % divisor) == 0
        else:
            # Idle -- use telemetry-specific divisor
            telemetry_div = TIER_TELEMETRY_DIVISOR[tier]
            return (tick_counter % telemetry_div) == 0

    def remove_unit(self, target_id: str) -> None:
        """Remove LOD tier for a single unit."""
        self._tiers.pop(target_id, None)

    def reset(self) -> None:
        """Clear all LOD tiers."""
        self._tiers.clear()

    def get_stats(self) -> dict[str, int]:
        """Return count of targets in each LOD tier."""
        counts = {tier.name: 0 for tier in LODTier}
        for tier in self._tiers.values():
            counts[tier.name] += 1
        return counts
