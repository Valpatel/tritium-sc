# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""System-wide real-time threat level calculator.

Computes an overall threat level for the operational area by aggregating
signals from multiple subsystems:
  - Hostile target count (from TargetTracker)
  - Geofence breaches (from GeofenceIntelligence / escalation records)
  - Active investigations (from InvestigationManager)
  - Threat feed matches (from ThreatFeedPlugin events)
  - Behavioral anomalies (from ThreatScorer)

The computed ThreatLevel (GREEN/YELLOW/ORANGE/RED/BLACK) is published
to the EventBus as ``system:threat_level`` for WebSocket broadcast to
the tactical banner in the Command Center UI.

Runs on a 2-second tick in a background thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Optional

logger = logging.getLogger("threat-level-calc")

# ThreatLevel thresholds — cumulative score ranges
# Score 0-9: GREEN, 10-29: YELLOW, 30-59: ORANGE, 60-89: RED, 90+: BLACK
LEVEL_THRESHOLDS = [
    (90, "black"),
    (60, "red"),
    (30, "orange"),
    (10, "yellow"),
    (0, "green"),
]

# Weight multipliers for each signal source
HOSTILE_TARGET_WEIGHT = 10.0     # per hostile target
GEOFENCE_BREACH_WEIGHT = 15.0   # per active geofence breach
INVESTIGATION_WEIGHT = 5.0      # per active investigation
THREAT_FEED_MATCH_WEIGHT = 20.0 # per recent threat feed match
BEHAVIORAL_ANOMALY_WEIGHT = 8.0 # per target with anomaly score > 0.5
SUSPICIOUS_TARGET_WEIGHT = 3.0  # per suspicious (not hostile) target


def score_to_level(score: float) -> str:
    """Convert a numeric threat score to a threat level string."""
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return "green"


class ThreatLevelCalculator:
    """Computes and publishes system-wide threat level in real time.

    Polls all available data sources every ``tick_interval`` seconds and
    aggregates their signals into a single threat score, then maps that
    score to a ThreatLevel enum value.

    Attributes:
        current_level: The most recently computed threat level string.
        current_score: The most recently computed numeric score.
    """

    TICK_INTERVAL = 2.0  # seconds

    def __init__(
        self,
        event_bus: Any,
        target_tracker: Any = None,
        escalation: Any = None,
        tick_interval: float | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._escalation = escalation
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State
        self.current_level: str = "green"
        self.current_score: float = 0.0
        self._last_published_level: str = ""
        self._threat_feed_matches: int = 0
        self._threat_feed_match_time: float = 0.0
        self._active_investigations: int = 0

        # History — store (timestamp, level, score) tuples for up to 24h
        # At 2s tick interval, 24h = 43200 entries (~1.5MB)
        self._history: deque[tuple[float, str, float]] = deque(maxlen=43200)

        if tick_interval is not None:
            self.TICK_INTERVAL = tick_interval

        # Subscribe to threat feed match events
        if self._event_bus is not None:
            self._sub = self._event_bus.subscribe()
            self._event_thread: Optional[threading.Thread] = None
        else:
            self._sub = None
            self._event_thread = None

    def start(self) -> None:
        """Start the background calculation loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._calc_loop, name="threat-level-calc", daemon=True
        )
        self._thread.start()

        # Event listener for threat feed matches and investigation updates
        if self._sub is not None:
            self._event_thread = threading.Thread(
                target=self._event_loop, name="threat-level-events", daemon=True
            )
            self._event_thread.start()

        logger.info("Threat level calculator started (%.1fs tick)", self.TICK_INTERVAL)

    def stop(self) -> None:
        """Stop the background calculation loop."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._event_thread is not None:
            self._event_thread = None

    def _event_loop(self) -> None:
        """Listen for relevant EventBus events."""
        while self._running:
            try:
                msg = self._sub.get(timeout=1.0)
                event_type = msg.get("type", "")
                if event_type == "threat:indicator_match":
                    with self._lock:
                        self._threat_feed_matches += 1
                        self._threat_feed_match_time = time.monotonic()
                elif event_type in ("investigation:opened", "investigation:created"):
                    with self._lock:
                        self._active_investigations += 1
                elif event_type in ("investigation:closed", "investigation:resolved"):
                    with self._lock:
                        self._active_investigations = max(0, self._active_investigations - 1)
            except Exception:
                pass

    def _calc_loop(self) -> None:
        """Main calculation loop — runs every TICK_INTERVAL seconds."""
        while self._running:
            try:
                self._calculate()
            except Exception as e:
                logger.debug("Threat level calculation error: %s", e)
            time.sleep(self.TICK_INTERVAL)

    def _calculate(self) -> None:
        """Compute system-wide threat score and level."""
        score = 0.0

        # 1. Count hostile and suspicious targets
        hostile_count = 0
        suspicious_count = 0
        if self._tracker is not None:
            try:
                all_targets = self._tracker.all_targets()
                for t in all_targets:
                    alliance = getattr(t, "alliance", "unknown")
                    if alliance == "hostile":
                        hostile_count += 1
                    threat_level = getattr(t, "threat_level", "none")
                    if threat_level == "suspicious":
                        suspicious_count += 1
            except Exception:
                pass

        score += hostile_count * HOSTILE_TARGET_WEIGHT
        score += suspicious_count * SUSPICIOUS_TARGET_WEIGHT

        # 2. Count geofence breaches / active threat escalations
        geofence_breaches = 0
        if self._escalation is not None:
            try:
                records = self._escalation.get_active_threats()
                geofence_breaches = len(records)
            except Exception:
                pass

        score += geofence_breaches * GEOFENCE_BREACH_WEIGHT

        # 3. Active investigations
        with self._lock:
            inv_count = self._active_investigations
        score += inv_count * INVESTIGATION_WEIGHT

        # 4. Threat feed matches (decay after 5 minutes)
        with self._lock:
            feed_matches = self._threat_feed_matches
            if feed_matches > 0:
                elapsed = time.monotonic() - self._threat_feed_match_time
                if elapsed > 300:  # 5 min decay
                    self._threat_feed_matches = max(0, self._threat_feed_matches - 1)
                    feed_matches = self._threat_feed_matches

        score += feed_matches * THREAT_FEED_MATCH_WEIGHT

        # 5. Behavioral anomalies (targets with threat_score > 0.5)
        anomaly_count = 0
        if self._tracker is not None:
            try:
                all_targets = self._tracker.all_targets()
                for t in all_targets:
                    ts = getattr(t, "threat_score", 0.0)
                    if ts > 0.5:
                        anomaly_count += 1
            except Exception:
                pass

        score += anomaly_count * BEHAVIORAL_ANOMALY_WEIGHT

        # Clamp to [0, 100]
        score = min(100.0, max(0.0, score))

        level = score_to_level(score)

        self.current_score = score
        self.current_level = level

        # Record history entry
        self._history.append((time.time(), level, round(score, 1)))

        # Publish on level change
        if level != self._last_published_level:
            self._last_published_level = level
            if self._event_bus is not None:
                self._event_bus.publish("system:threat_level", {
                    "level": level,
                    "score": round(score, 1),
                    "hostile_count": hostile_count,
                    "suspicious_count": suspicious_count,
                    "geofence_breaches": geofence_breaches,
                    "active_investigations": inv_count,
                    "threat_feed_matches": feed_matches,
                    "behavioral_anomalies": anomaly_count,
                })
                logger.info(
                    "Threat level changed: %s -> %s (score=%.1f)",
                    self._last_published_level or "none",
                    level,
                    score,
                )

    def get_status(self) -> dict:
        """Return current threat level status for API consumption."""
        return {
            "level": self.current_level,
            "score": round(self.current_score, 1),
        }

    def get_history(self, hours: float = 24.0) -> list[dict]:
        """Return threat level history for the requested time window.

        Args:
            hours: Number of hours of history to return (max 24).

        Returns:
            List of dicts with timestamp, level, and score keys.
        """
        cutoff = time.time() - (min(hours, 24.0) * 3600)
        result = []
        for ts, level, score in self._history:
            if ts >= cutoff:
                result.append({
                    "timestamp": round(ts, 1),
                    "level": level,
                    "score": score,
                })
        return result

    def set_tracker(self, tracker: Any) -> None:
        """Update the target tracker reference."""
        self._tracker = tracker

    def set_escalation(self, escalation: Any) -> None:
        """Update the escalation engine reference."""
        self._escalation = escalation
