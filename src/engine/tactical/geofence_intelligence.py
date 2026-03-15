# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Geofence intelligence — auto-investigate targets entering zones with high threat scores.

When a target enters a geofenced zone and its threat_score > 0.5, this module
automatically starts an investigation seeded with that target and adds nearby
targets as related entities.  Listens on EventBus for ``geofence:enter`` events.

Integrates:
  - GeofenceEngine for zone enter events
  - ThreatScorer for threat_score checks
  - InvestigationEngine for auto-investigation creation
  - TargetTracker for nearby target discovery
"""

from __future__ import annotations

import logging
import math
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..comms.event_bus import EventBus
    from .investigation import InvestigationEngine
    from .target_tracker import TargetTracker
    from .threat_scoring import ThreatScorer

logger = logging.getLogger("geofence-intelligence")

# Maximum radius (meters) for discovering nearby related targets
NEARBY_RADIUS = 25.0

# Minimum threat score to trigger auto-investigation on geofence enter
THREAT_THRESHOLD = 0.5


class GeofenceIntelligence:
    """Bridges geofence events to the investigation engine.

    Subscribes to ``geofence:enter`` on the EventBus.  When a target enters
    a zone and its threat score exceeds ``THREAT_THRESHOLD``, an investigation
    is created (if one doesn't already exist for that target) and nearby
    targets are added as related entities.

    Parameters
    ----------
    event_bus:
        The shared EventBus instance.
    investigation_engine:
        The InvestigationEngine for creating/managing investigations.
    threat_scorer:
        The ThreatScorer for looking up threat scores.
    target_tracker:
        The TargetTracker for discovering nearby targets.
    threat_threshold:
        Minimum threat_score to trigger auto-investigation (default 0.5).
    nearby_radius:
        Radius in meters for nearby target discovery (default 25.0).
    """

    def __init__(
        self,
        event_bus: EventBus,
        investigation_engine: InvestigationEngine,
        threat_scorer: ThreatScorer,
        target_tracker: TargetTracker,
        threat_threshold: float = THREAT_THRESHOLD,
        nearby_radius: float = NEARBY_RADIUS,
    ) -> None:
        self._event_bus = event_bus
        self._inv_engine = investigation_engine
        self._threat_scorer = threat_scorer
        self._tracker = target_tracker
        self._threat_threshold = threat_threshold
        self._nearby_radius = nearby_radius
        self._lock = threading.Lock()
        self._active = False
        # Stats
        self._investigations_created = 0
        self._events_processed = 0
        self._nearby_added = 0

    def start(self) -> None:
        """Subscribe to geofence:enter events."""
        if self._active:
            return
        self._active = True
        self._event_bus.subscribe("geofence:enter", self._on_geofence_enter)
        logger.info(
            "GeofenceIntelligence active (threshold=%.2f, radius=%.0fm)",
            self._threat_threshold, self._nearby_radius,
        )

    def stop(self) -> None:
        """Unsubscribe from events."""
        self._active = False
        try:
            self._event_bus.unsubscribe("geofence:enter", self._on_geofence_enter)
        except Exception:
            pass

    def _on_geofence_enter(self, data: dict[str, Any]) -> None:
        """Handle a geofence:enter event.

        If the entering target's threat_score > threshold, create an
        investigation and add nearby targets.
        """
        with self._lock:
            self._events_processed += 1

        target_id = data.get("target_id", "")
        zone_name = data.get("zone_name", "unknown")
        zone_type = data.get("zone_type", "monitored")
        position = data.get("position", [0.0, 0.0])

        if not target_id:
            return

        # Check threat score
        score = self._threat_scorer.get_score(target_id)
        if score < self._threat_threshold:
            logger.debug(
                "Target %s entered zone %s but threat_score=%.2f < %.2f",
                target_id[:12], zone_name, score, self._threat_threshold,
            )
            return

        # Check if already under investigation
        existing = self._inv_engine.list_investigations(status="open")
        for inv in existing:
            if target_id in inv.all_entity_ids():
                logger.debug(
                    "Target %s already in investigation %s",
                    target_id[:12], inv.inv_id[:8],
                )
                # Still add nearby targets to the existing investigation
                self._add_nearby(inv.inv_id, target_id, position)
                return

        # Create investigation
        title = (
            f"Geofence alert: {target_id[:12]} in {zone_name} "
            f"(threat={score:.2f})"
        )
        description = (
            f"Auto-created when target {target_id} entered {zone_type} "
            f"zone '{zone_name}' with threat_score {score:.2f}."
        )

        inv = self._inv_engine.create(
            title=title,
            seed_entity_ids=[target_id],
            description=description,
        )

        with self._lock:
            self._investigations_created += 1

        logger.info(
            "Geofence auto-investigation %s for target %s (score=%.2f, zone=%s)",
            inv.inv_id[:8], target_id[:12], score, zone_name,
        )

        # Add annotation
        self._inv_engine.annotate(
            inv.inv_id,
            target_id,
            f"Target entered {zone_type} zone '{zone_name}' with "
            f"threat_score={score:.2f}",
            analyst="geofence_intelligence",
        )

        # Discover and add nearby targets
        self._add_nearby(inv.inv_id, target_id, position)

        # Publish event for dashboards
        self._event_bus.publish("investigation:auto_created", {
            "inv_id": inv.inv_id,
            "target_id": target_id,
            "zone_name": zone_name,
            "threat_score": score,
            "trigger": "geofence_enter",
        })

    def _add_nearby(
        self,
        inv_id: str,
        source_target_id: str,
        position: list | tuple,
    ) -> None:
        """Find nearby targets and add them to the investigation."""
        if not position or len(position) < 2:
            return

        px, py = float(position[0]), float(position[1])
        all_targets = self._tracker.get_all()

        inv = self._inv_engine.get(inv_id)
        if inv is None:
            return

        known_ids = inv.all_entity_ids()
        added_count = 0

        for target in all_targets:
            if target.target_id == source_target_id:
                continue
            if target.target_id in known_ids:
                continue

            # Distance check
            tx, ty = target.position
            dist = math.sqrt((tx - px) ** 2 + (ty - py) ** 2)
            if dist <= self._nearby_radius:
                inv.discovered_entities.add(target.target_id)
                added_count += 1

                self._inv_engine.annotate(
                    inv_id,
                    target.target_id,
                    f"Nearby target ({dist:.1f}m from trigger, "
                    f"source={target.source})",
                    analyst="geofence_intelligence",
                )

        if added_count > 0:
            # Save updated investigation
            self._inv_engine._save_investigation(inv)
            with self._lock:
                self._nearby_added += added_count

            logger.info(
                "Added %d nearby targets to investigation %s",
                added_count, inv_id[:8],
            )

    def get_status(self) -> dict[str, Any]:
        """Return status for API/dashboard."""
        with self._lock:
            return {
                "active": self._active,
                "threat_threshold": self._threat_threshold,
                "nearby_radius": self._nearby_radius,
                "investigations_created": self._investigations_created,
                "events_processed": self._events_processed,
                "nearby_targets_added": self._nearby_added,
            }
