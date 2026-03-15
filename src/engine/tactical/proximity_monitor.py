# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ProximityMonitor — entity-to-entity proximity alerting engine.

Runs a periodic scan of all tracked targets and fires alerts when
two targets of different alliances come within a configurable distance.

Example: "Hostile target approaching friendly asset" when a hostile
BLE detection is within 10m of a friendly drone.

Uses ProximityRule and ProximityAlert from tritium-lib.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("proximity_monitor")

# Import from tritium-lib if available
try:
    from tritium_lib.models.proximity import (
        ProximityAlert,
        ProximityRule,
        AlliancePair,
        classify_proximity_severity,
        DEFAULT_PROXIMITY_RULES,
    )
except ImportError:
    # Inline fallback — same dataclass shapes for standalone use
    from dataclasses import dataclass, field
    import uuid

    @dataclass
    class ProximityAlert:  # type: ignore[no-redef]
        alert_id: str = ""
        target_a_id: str = ""
        target_b_id: str = ""
        target_a_alliance: str = ""
        target_b_alliance: str = ""
        distance_m: float = 0.0
        threshold_m: float = 10.0
        alert_type: str = "breach"
        severity: str = "medium"
        timestamp: float = field(default_factory=time.time)
        position_a: tuple = (0.0, 0.0)
        position_b: tuple = (0.0, 0.0)
        rule_id: str = ""
        acknowledged: bool = False

        def to_dict(self):
            return vars(self)

    @dataclass
    class ProximityRule:  # type: ignore[no-redef]
        rule_id: str = ""
        name: str = "Proximity Alert"
        alliance_pair: str = "hostile_friendly"
        threshold_m: float = 10.0
        cooldown_s: float = 60.0
        enabled: bool = True
        notify_on_approach: bool = False
        approach_factor: float = 1.5

        def matches_alliance(self, a, b):
            if self.alliance_pair == "any_different":
                return a != b
            combo = f"{a}_{b}"
            rev = f"{b}_{a}"
            return self.alliance_pair in (combo, rev)

        def to_dict(self):
            return vars(self)

        @classmethod
        def from_dict(cls, d):
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def classify_proximity_severity(distance_m, threshold_m):
        if threshold_m <= 0:
            return "critical"
        ratio = distance_m / threshold_m
        if ratio < 0.25:
            return "critical"
        elif ratio < 0.50:
            return "high"
        elif ratio < 0.75:
            return "medium"
        return "low"

    DEFAULT_PROXIMITY_RULES = [
        ProximityRule(
            rule_id="default_hostile_friendly",
            name="Hostile approaching friendly asset",
            alliance_pair="hostile_friendly",
            threshold_m=10.0,
            cooldown_s=60.0,
        ),
    ]


_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "proximity"


class ProximityMonitor:
    """Monitors target-to-target distances and fires alerts.

    Parameters
    ----------
    target_tracker:
        The TargetTracker instance to scan for target positions.
    event_bus:
        EventBus for publishing proximity alerts.
    scan_interval_s:
        How often to scan for proximity violations (default 2.0s).
    """

    def __init__(
        self,
        target_tracker: Any = None,
        event_bus: Any = None,
        scan_interval_s: float = 2.0,
    ) -> None:
        self._tracker = target_tracker
        self._event_bus = event_bus
        self._scan_interval = scan_interval_s
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._rules: list[ProximityRule] = []
        self._lock = threading.Lock()

        # Cooldown tracking: "target_a:target_b:rule_id" -> last_alert_time
        self._cooldowns: dict[str, float] = {}

        # Recent alerts ring buffer
        self._recent_alerts: list[ProximityAlert] = []
        self._max_alerts = 500

        # Active breaches: pair_key -> ProximityAlert (currently within threshold)
        self._active_breaches: dict[str, ProximityAlert] = {}

        # Stats
        self._scans_completed = 0
        self._alerts_fired = 0

        # Load persisted rules or use defaults
        self._load_rules()

    def _load_rules(self) -> None:
        """Load rules from disk, or seed with defaults."""
        rules_file = _DATA_DIR / "rules.json"
        if rules_file.exists():
            try:
                with open(rules_file) as f:
                    data = json.load(f)
                self._rules = [ProximityRule.from_dict(r) for r in data]
                logger.info("Loaded %d proximity rules", len(self._rules))
                return
            except Exception as exc:
                logger.warning("Failed to load proximity rules: %s", exc)

        self._rules = list(DEFAULT_PROXIMITY_RULES)
        self._save_rules()
        logger.info("Seeded %d default proximity rules", len(self._rules))

    def _save_rules(self) -> None:
        """Persist rules to disk."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            rules_file = _DATA_DIR / "rules.json"
            data = [r.to_dict() for r in self._rules]
            with open(rules_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save proximity rules: %s", exc)

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: ProximityRule) -> None:
        """Add a proximity rule."""
        with self._lock:
            self._rules.append(rule)
            self._save_rules()

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a proximity rule by ID."""
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.rule_id != rule_id]
            if len(self._rules) < before:
                self._save_rules()
                return True
            return False

    def list_rules(self) -> list[ProximityRule]:
        """Return a copy of all rules."""
        return list(self._rules)

    def update_rule(self, rule_id: str, updates: dict) -> bool:
        """Update a rule's fields."""
        with self._lock:
            for rule in self._rules:
                if rule.rule_id == rule_id:
                    for key, val in updates.items():
                        if hasattr(rule, key):
                            setattr(rule, key, val)
                    self._save_rules()
                    return True
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background proximity scanning thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name="proximity-monitor",
        )
        self._thread.start()
        logger.info("Proximity monitor started (interval=%.1fs)", self._scan_interval)

    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Proximity monitor stopped")

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan_loop(self) -> None:
        """Background loop: periodically scan all target pairs."""
        while self._running:
            try:
                self._scan()
            except Exception as exc:
                logger.error("Proximity scan error: %s", exc)
            time.sleep(self._scan_interval)

    def _scan(self) -> None:
        """Scan all target pairs against all enabled rules."""
        if self._tracker is None:
            return

        targets = self._tracker.get_all()
        if len(targets) < 2:
            return

        now = time.time()
        enabled_rules = [r for r in self._rules if r.enabled]
        if not enabled_rules:
            return

        # Check every unique pair
        target_list = list(targets.values())
        new_breaches: set[str] = set()

        for i in range(len(target_list)):
            for j in range(i + 1, len(target_list)):
                a = target_list[i]
                b = target_list[j]

                # Skip same alliance pairs quickly
                if a.alliance == b.alliance:
                    continue

                # Compute distance
                dx = a.position[0] - b.position[0]
                dy = a.position[1] - b.position[1]
                dist = math.sqrt(dx * dx + dy * dy)

                for rule in enabled_rules:
                    if not rule.matches_alliance(a.alliance, b.alliance):
                        continue

                    pair_key = self._pair_key(a.target_id, b.target_id, rule.rule_id)

                    if dist <= rule.threshold_m:
                        new_breaches.add(pair_key)

                        # Check cooldown
                        last_alert = self._cooldowns.get(pair_key, 0.0)
                        if (now - last_alert) < rule.cooldown_s:
                            continue

                        # Fire alert
                        severity = classify_proximity_severity(dist, rule.threshold_m)
                        alert = ProximityAlert(
                            target_a_id=a.target_id,
                            target_b_id=b.target_id,
                            target_a_alliance=a.alliance,
                            target_b_alliance=b.alliance,
                            distance_m=dist,
                            threshold_m=rule.threshold_m,
                            alert_type="breach",
                            severity=severity,
                            timestamp=now,
                            position_a=a.position,
                            position_b=b.position,
                            rule_id=rule.rule_id,
                        )

                        self._fire_alert(alert)
                        self._cooldowns[pair_key] = now
                        self._active_breaches[pair_key] = alert

        # Check for departures (was breaching, no longer)
        departed = set(self._active_breaches.keys()) - new_breaches
        for pair_key in departed:
            old_alert = self._active_breaches.pop(pair_key, None)
            if old_alert:
                departure = ProximityAlert(
                    target_a_id=old_alert.target_a_id,
                    target_b_id=old_alert.target_b_id,
                    target_a_alliance=old_alert.target_a_alliance,
                    target_b_alliance=old_alert.target_b_alliance,
                    distance_m=0.0,  # unknown current distance
                    threshold_m=old_alert.threshold_m,
                    alert_type="departure",
                    severity="low",
                    timestamp=now,
                    rule_id=old_alert.rule_id,
                )
                self._fire_alert(departure)

        self._scans_completed += 1

    def _fire_alert(self, alert: ProximityAlert) -> None:
        """Publish an alert to the event bus and store it."""
        self._recent_alerts.append(alert)
        if len(self._recent_alerts) > self._max_alerts:
            self._recent_alerts = self._recent_alerts[-self._max_alerts:]
        self._alerts_fired += 1

        if self._event_bus:
            self._event_bus.publish("proximity:alert", data=alert.to_dict())

        logger.info(
            "Proximity %s: %s (%s) <-> %s (%s) at %.1fm (threshold %.1fm, severity %s)",
            alert.alert_type,
            alert.target_a_id,
            alert.target_a_alliance,
            alert.target_b_id,
            alert.target_b_alliance,
            alert.distance_m,
            alert.threshold_m,
            alert.severity,
        )

    @staticmethod
    def _pair_key(a_id: str, b_id: str, rule_id: str) -> str:
        """Create a canonical key for a target pair + rule."""
        ids = sorted([a_id, b_id])
        return f"{ids[0]}:{ids[1]}:{rule_id}"

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_recent_alerts(self, limit: int = 50) -> list[dict]:
        """Return recent proximity alerts."""
        return [a.to_dict() for a in self._recent_alerts[-limit:]]

    def get_active_breaches(self) -> list[dict]:
        """Return currently active proximity breaches."""
        return [a.to_dict() for a in self._active_breaches.values()]

    def get_stats(self) -> dict:
        """Return monitor statistics."""
        return {
            "running": self._running,
            "scans_completed": self._scans_completed,
            "alerts_fired": self._alerts_fired,
            "active_breaches": len(self._active_breaches),
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules if r.enabled),
            "scan_interval_s": self._scan_interval,
        }

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Mark an alert as acknowledged."""
        for alert in self._recent_alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False
