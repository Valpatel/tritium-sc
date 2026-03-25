# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DispatchAction — asset selection and dispatch for Amy's autonomous responses.

Provides autonomous asset dispatch capabilities:
  - find_nearest_asset() — select closest friendly with required capability
  - dispatch_to_investigate() — send a unit to a target position via MQTT
  - DispatchAction — structured dispatch command with reason and priority
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.comms.mqtt_bridge import MQTTBridge
    from tritium_lib.tracking.target_tracker import TargetTracker, TrackedTarget

logger = logging.getLogger("amy.dispatch")

# Asset capabilities by type
ASSET_CAPABILITIES: dict[str, set[str]] = {
    "camera": {"observe", "record", "identify"},
    "drone": {"observe", "intercept", "patrol", "record"},
    "rover": {"observe", "intercept", "patrol"},
    "turret": {"engage", "overwatch"},
    "vehicle": {"intercept", "patrol", "transport"},
}

# Types that can physically move to a location
MOBILE_ASSET_TYPES = {"drone", "rover", "vehicle"}

# Minimum battery to dispatch (20%)
MIN_DISPATCH_BATTERY = 0.20


@dataclass
class DispatchAction:
    """A structured dispatch command from Amy's instinct layer."""

    asset_id: str
    asset_name: str
    asset_type: str
    target_position: tuple[float, float]
    reason: str
    priority: int = 3  # 1-5, 5=highest
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "target_position": {
                "x": self.target_position[0],
                "y": self.target_position[1],
            },
            "reason": self.reason,
            "priority": self.priority,
            "timestamp": self.timestamp,
        }


def find_nearest_asset(
    tracker: TargetTracker,
    position: tuple[float, float],
    asset_types: set[str] | None = None,
    *,
    exclude_ids: set[str] | None = None,
    min_battery: float = MIN_DISPATCH_BATTERY,
    require_mobile: bool = True,
) -> TrackedTarget | None:
    """Find the nearest available friendly asset matching criteria.

    Parameters
    ----------
    tracker:
        The TargetTracker containing all tracked entities.
    position:
        Target position (x, y) to find the nearest asset to.
    asset_types:
        Set of asset types to consider (e.g. {"camera", "drone"}).
        If None, considers all mobile types.
    exclude_ids:
        Set of target IDs to exclude (already dispatched, etc.).
    min_battery:
        Minimum battery level required (0.0-1.0).
    require_mobile:
        If True, only returns assets in MOBILE_ASSET_TYPES.

    Returns
    -------
    TrackedTarget or None:
        The nearest qualifying friendly, or None if none available.
    """
    if asset_types is None:
        asset_types = MOBILE_ASSET_TYPES if require_mobile else None

    exclude = exclude_ids or set()
    friendlies = tracker.get_friendlies()

    candidates = []
    for f in friendlies:
        if f.target_id in exclude:
            continue
        if f.battery < min_battery:
            continue
        if f.status not in ("active", "idle", "arrived"):
            continue
        if require_mobile and f.asset_type not in MOBILE_ASSET_TYPES:
            continue
        if asset_types is not None and f.asset_type not in asset_types:
            continue
        candidates.append(f)

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda f: math.hypot(
            f.position[0] - position[0],
            f.position[1] - position[1],
        ),
    )


def dispatch_to_investigate(
    asset_id: str,
    target_position: tuple[float, float],
    *,
    event_bus: EventBus | None = None,
    mqtt_bridge: MQTTBridge | None = None,
    simulation_engine=None,
    reason: str = "investigate",
) -> DispatchAction | None:
    """Dispatch an asset to investigate a target position.

    Sends the dispatch command through available channels:
      1. Simulation engine: sets waypoints for sim target
      2. MQTT bridge: publishes dispatch command for real robots
      3. EventBus: publishes amy_dispatch event for UI

    Parameters
    ----------
    asset_id:
        The ID of the friendly asset to dispatch.
    target_position:
        Position (x, y) to send the asset to.
    event_bus:
        EventBus for internal event publishing.
    mqtt_bridge:
        MQTTBridge for publishing to real robots.
    simulation_engine:
        SimulationEngine for moving simulated units.
    reason:
        Description of why the dispatch is happening.

    Returns
    -------
    DispatchAction or None:
        The created dispatch action, or None if asset not found.
    """
    asset_name = asset_id
    asset_type = "unknown"

    # Move sim target if we have the engine
    if simulation_engine is not None:
        sim_target = simulation_engine.get_target(asset_id)
        if sim_target is not None:
            asset_name = getattr(sim_target, "name", asset_id)
            asset_type = getattr(sim_target, "asset_type", "unknown")

            if hasattr(simulation_engine, "route_path"):
                sim_target.waypoints = simulation_engine.route_path(
                    sim_target.position, target_position,
                    sim_target.asset_type, sim_target.alliance,
                )
            else:
                sim_target.waypoints = [target_position]
            sim_target._waypoint_index = 0
            sim_target.loop_waypoints = False
            sim_target.status = "active"

    action = DispatchAction(
        asset_id=asset_id,
        asset_name=asset_name,
        asset_type=asset_type,
        target_position=target_position,
        reason=reason,
    )

    # Publish to EventBus
    if event_bus is not None:
        event_bus.publish("amy_dispatch", {
            "target_id": asset_id,
            "name": asset_name,
            "destination": {
                "x": target_position[0],
                "y": target_position[1],
            },
            "reason": reason,
        })

    # Publish to MQTT
    if mqtt_bridge is not None:
        mqtt_bridge.publish_dispatch(asset_id, target_position[0], target_position[1])

    logger.info(
        "Dispatch %s to (%.1f, %.1f): %s",
        asset_name, target_position[0], target_position[1], reason,
    )

    return action
