# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BLE device threat classification — known vs unknown, alerting on new MACs.

Maintains a set of known BLE device MACs and classifies incoming sightings
as known, unknown, new, or suspicious.  Publishes alerts to EventBus when
new or suspicious devices appear.

Classification levels:
    - known:      MAC exists in the known_devices set
    - unknown:    MAC is not known but has been seen before
    - new:        MAC has never been seen before (first sighting)
    - suspicious: unknown device with strong signal (RSSI > threshold)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..comms.event_bus import EventBus

logger = logging.getLogger("ble-classifier")

# Lazy import to avoid circular deps — training_store is optional
_training_store_cache = None


def _get_training_store():
    """Lazily import and return the singleton TrainingStore (or None)."""
    global _training_store_cache
    if _training_store_cache is not None:
        return _training_store_cache
    try:
        from engine.intelligence.training_store import get_training_store
        _training_store_cache = get_training_store()
        return _training_store_cache
    except Exception:
        return None

# Classification levels
CLASSIFICATION_LEVELS = ["known", "unknown", "new", "suspicious"]

# Default RSSI threshold — signals stronger than this from unknown devices
# are classified as suspicious (closer to 0 = stronger signal).
DEFAULT_SUSPICIOUS_RSSI = -40


@dataclass
class BLEClassification:
    """Classification result for a single BLE device."""

    mac: str
    name: str
    rssi: int
    level: str  # known | unknown | new | suspicious
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    seen_count: int = 1


class BLEClassifier:
    """Classifies BLE devices as known, unknown, new, or suspicious.

    Parameters
    ----------
    event_bus:
        EventBus instance for publishing alerts.
    known_macs:
        Initial set of known MAC addresses (e.g. from config or DB).
    suspicious_rssi:
        RSSI threshold above which unknown devices are suspicious.
        Defaults to -40 (strong nearby signal).
    """

    def __init__(
        self,
        event_bus: EventBus,
        known_macs: set[str] | None = None,
        suspicious_rssi: int = DEFAULT_SUSPICIOUS_RSSI,
    ) -> None:
        self._event_bus = event_bus
        self._known_macs: set[str] = {m.upper() for m in (known_macs or set())}
        self._suspicious_rssi = suspicious_rssi
        self._lock = threading.Lock()
        # All classifications keyed by MAC (upper-case)
        self._classifications: dict[str, BLEClassification] = {}
        # Set of MACs we have ever seen (for new vs unknown distinction)
        self._seen_macs: set[str] = set()

    # -- Public API ------------------------------------------------------------

    def classify(self, mac: str, name: str = "", rssi: int = -100) -> BLEClassification:
        """Classify a BLE device sighting.

        Returns the BLEClassification and publishes alerts for new/suspicious.
        """
        mac_upper = mac.upper()
        now = time.time()

        with self._lock:
            is_known = mac_upper in self._known_macs
            is_first_time = mac_upper not in self._seen_macs

            # Determine classification level
            if is_known:
                level = "known"
            elif is_first_time:
                # Check if also suspicious (strong signal + new)
                if rssi > self._suspicious_rssi:
                    level = "suspicious"
                else:
                    level = "new"
            else:
                # Previously seen but not known
                if rssi > self._suspicious_rssi:
                    level = "suspicious"
                else:
                    level = "unknown"

            # Mark as seen
            self._seen_macs.add(mac_upper)

            # Update or create classification record
            existing = self._classifications.get(mac_upper)
            if existing is not None:
                existing.name = name or existing.name
                existing.rssi = rssi
                existing.level = level
                existing.last_seen = now
                existing.seen_count += 1
                classification = existing
            else:
                classification = BLEClassification(
                    mac=mac_upper,
                    name=name,
                    rssi=rssi,
                    level=level,
                    first_seen=now,
                    last_seen=now,
                    seen_count=1,
                )
                self._classifications[mac_upper] = classification

        # Publish alerts outside the lock
        if is_first_time and not is_known:
            self._publish_alert(classification, is_first_time=True)
        elif level == "suspicious" and not is_known:
            self._publish_alert(classification, is_first_time=False)

        # Log classification decision to training store for RL pipeline
        self._log_classification(classification)

        return classification

    def add_known(self, mac: str) -> None:
        """Add a MAC address to the known devices set."""
        mac_upper = mac.upper()
        with self._lock:
            self._known_macs.add(mac_upper)
            # Reclassify if we have an existing record
            if mac_upper in self._classifications:
                self._classifications[mac_upper].level = "known"

    def remove_known(self, mac: str) -> bool:
        """Remove a MAC from the known set. Returns True if it was present."""
        mac_upper = mac.upper()
        with self._lock:
            if mac_upper in self._known_macs:
                self._known_macs.discard(mac_upper)
                return True
            return False

    def get_known_macs(self) -> set[str]:
        """Return a copy of the known MACs set."""
        with self._lock:
            return set(self._known_macs)

    def get_classifications(self) -> dict[str, BLEClassification]:
        """Return a copy of all current classifications."""
        with self._lock:
            return dict(self._classifications)

    def get_classifications_by_level(self, level: str) -> list[BLEClassification]:
        """Return classifications filtered by level."""
        with self._lock:
            return [c for c in self._classifications.values() if c.level == level]

    def clear(self) -> None:
        """Reset all classification state (keeps known_macs)."""
        with self._lock:
            self._classifications.clear()
            self._seen_macs.clear()

    # -- Internal --------------------------------------------------------------

    def _log_classification(self, classification: BLEClassification) -> None:
        """Log a BLE classification decision to the training store."""
        store = _get_training_store()
        if store is None:
            return

        try:
            features = {
                "rssi": classification.rssi,
                "seen_count": classification.seen_count,
                "name_length": len(classification.name),
                "has_name": 1.0 if classification.name else 0.0,
            }
            # Map BLE classification level to a predicted alliance
            alliance_map = {
                "known": "friendly",
                "unknown": "unknown",
                "new": "unknown",
                "suspicious": "hostile",
            }
            store.log_classification(
                target_id=f"ble_{classification.mac}",
                features=features,
                predicted_type="ble_device",
                confidence=1.0 if classification.level == "known" else 0.5,
                predicted_alliance=alliance_map.get(classification.level, "unknown"),
                source="ble_classifier",
            )
        except Exception as exc:
            logger.debug("Training store log failed (non-fatal): %s", exc)

    def _publish_alert(self, classification: BLEClassification, is_first_time: bool) -> None:
        """Publish BLE alert to EventBus."""
        event_type = "ble:new_device" if is_first_time else "ble:suspicious_device"
        data = {
            "mac": classification.mac,
            "name": classification.name,
            "rssi": classification.rssi,
            "level": classification.level,
            "first_seen": classification.first_seen,
            "last_seen": classification.last_seen,
            "seen_count": classification.seen_count,
        }
        self._event_bus.publish(event_type, data)
        logger.info(
            "BLE alert [%s]: mac=%s name=%s rssi=%d level=%s",
            event_type, classification.mac, classification.name,
            classification.rssi, classification.level,
        )
