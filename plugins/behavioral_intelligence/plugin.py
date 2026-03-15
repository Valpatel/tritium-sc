# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BehavioralIntelligencePlugin — pattern learning, relationship inference, anomaly alerting.

Analyzes target movement history to detect daily routines, regular commuters,
co-presence relationships, and anomalous behavior. Fires alerts when
established patterns are broken.

Provides REST API at /api/patterns/ for pattern, relationship, and anomaly queries.
"""

from __future__ import annotations

import json
import logging
import os
import queue as queue_mod
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .pattern_detector import PatternDetector

log = logging.getLogger("behavioral-intelligence")

_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "behavioral_intelligence"


class BehavioralIntelligencePlugin(PluginInterface):
    """Behavioral intelligence: pattern detection, relationship inference, anomaly alerts."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._ctx: Optional[PluginContext] = None

        self._detector = PatternDetector()
        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None
        self._analysis_thread: Optional[threading.Thread] = None

        # Stats
        self._events_processed: int = 0
        self._patterns_detected: int = 0
        self._anomalies_detected: int = 0
        self._alerts_fired: int = 0

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.behavioral-intelligence"

    @property
    def name(self) -> str:
        return "Behavioral Intelligence"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"routes", "background", "intelligence"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._ctx = ctx
        self._logger = ctx.logger or log

        # Load persisted alerts
        self._load_alerts()

        # Register HTTP routes
        self._register_routes()
        self._logger.info(
            "Behavioral Intelligence plugin configured (%d alerts)",
            len(self._detector.list_alerts()),
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Subscribe to EventBus for target sighting events
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="behavior-events",
            )
            self._event_thread.start()

        # Background analysis thread
        self._analysis_thread = threading.Thread(
            target=self._analysis_loop,
            daemon=True,
            name="behavior-analysis",
        )
        self._analysis_thread.start()

        self._logger.info("Behavioral Intelligence plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._analysis_thread and self._analysis_thread.is_alive():
            self._analysis_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._save_alerts()
        self._logger.info("Behavioral Intelligence plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API --------------------------------------------------------

    @property
    def detector(self) -> PatternDetector:
        """Expose the pattern detector for direct access."""
        return self._detector

    def get_stats(self) -> dict:
        """Return plugin statistics."""
        stats = self._detector.get_stats()
        stats.update({
            "events_processed": self._events_processed,
            "patterns_detected": self._patterns_detected,
            "anomalies_detected": self._anomalies_detected,
            "alerts_fired": self._alerts_fired,
        })
        return stats

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Drain EventBus queue and record sightings for pattern analysis."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._events_processed += 1
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Behavioral intelligence event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process a single EventBus event."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type in ("edge:ble_update", "fleet.ble_presence"):
            self._on_ble_update(data)
        elif event_type in ("edge:wifi_update", "fleet.wifi_presence"):
            self._on_wifi_update(data)
        elif event_type == "fleet.heartbeat":
            self._on_heartbeat(data)
        elif event_type == "meshtastic:node_update":
            self._on_mesh_update(data)

    def _on_ble_update(self, data: dict) -> None:
        """Record BLE device sightings."""
        devices = data.get("devices", [])
        now = time.time()
        for dev in devices:
            mac = dev.get("mac", "")
            if not mac:
                continue
            target_id = f"ble_{mac.replace(':', '').lower()}"
            pos = dev.get("position", {})
            self._detector.record_sighting(
                target_id=target_id,
                timestamp=dev.get("timestamp", now),
                lat=pos.get("lat", 0.0) if isinstance(pos, dict) else 0.0,
                lng=pos.get("lng", pos.get("lon", 0.0)) if isinstance(pos, dict) else 0.0,
                node_id=dev.get("node_id", ""),
                rssi=dev.get("rssi", -100),
            )

    def _on_wifi_update(self, data: dict) -> None:
        """Record WiFi network sightings."""
        networks = data.get("networks", [])
        now = time.time()
        for net in networks:
            bssid = net.get("bssid", "")
            if not bssid:
                continue
            target_id = f"wifi_{bssid.replace(':', '').lower()}"
            self._detector.record_sighting(
                target_id=target_id,
                timestamp=net.get("timestamp", now),
                node_id=net.get("node_id", ""),
                rssi=net.get("rssi", -100),
            )

    def _on_heartbeat(self, data: dict) -> None:
        """Extract BLE/WiFi from heartbeat payloads."""
        ble_data = data.get("ble", data.get("ble_devices", []))
        if ble_data:
            self._on_ble_update({"devices": ble_data})
        wifi_data = data.get("wifi", data.get("wifi_networks", []))
        if wifi_data:
            self._on_wifi_update({"networks": wifi_data})

    def _on_mesh_update(self, data: dict) -> None:
        """Record Meshtastic node sighting."""
        node_id = data.get("node_id", "")
        if not node_id:
            return
        target_id = f"mesh_{node_id}"
        pos = data.get("position", {})
        self._detector.record_sighting(
            target_id=target_id,
            timestamp=data.get("timestamp", time.time()),
            lat=pos.get("lat", 0.0) if isinstance(pos, dict) else 0.0,
            lng=pos.get("lng", pos.get("lon", 0.0)) if isinstance(pos, dict) else 0.0,
        )

    # -- Background analysis -----------------------------------------------

    def _analysis_loop(self) -> None:
        """Periodic background analysis for patterns and anomalies."""
        while self._running:
            try:
                self._run_analysis()
            except Exception as exc:
                log.error("Behavioral analysis error: %s", exc)
            # Run every 30 seconds
            for _ in range(60):
                if not self._running:
                    return
                time.sleep(0.5)

    def _run_analysis(self) -> None:
        """Execute one analysis cycle."""
        # Analyze each target for patterns
        for target_id in list(self._detector._sightings.keys()):
            new_patterns = self._detector.analyze_target(target_id)
            self._patterns_detected += len(new_patterns)

            for pattern in new_patterns:
                if self._event_bus:
                    self._event_bus.publish(
                        "behavior:pattern_detected",
                        data={
                            "pattern_id": pattern.pattern_id,
                            "target_id": pattern.target_id,
                            "type": pattern.pattern_type.value
                            if hasattr(pattern.pattern_type, "value")
                            else str(pattern.pattern_type),
                            "confidence": pattern.confidence,
                            "status": pattern.status.value
                            if hasattr(pattern.status, "value")
                            else str(pattern.status),
                        },
                    )

        # Analyze co-presence relationships
        new_rels = self._detector.analyze_co_presence()
        for rel in new_rels:
            if rel.graph_edge_created:
                continue
            if self._event_bus:
                self._event_bus.publish(
                    "behavior:relationship_inferred",
                    data={
                        "target_a": rel.target_a,
                        "target_b": rel.target_b,
                        "relationship_type": rel.relationship_type,
                        "confidence": rel.confidence,
                        "temporal_correlation": rel.temporal_correlation,
                    },
                )
            rel.graph_edge_created = True

        # Check for pattern violations
        anomalies = self._detector.check_pattern_violations()
        self._anomalies_detected += len(anomalies)

        for anomaly in anomalies:
            if self._event_bus:
                self._event_bus.publish(
                    "behavior:anomaly_detected",
                    data={
                        "anomaly_id": anomaly.anomaly_id,
                        "target_id": anomaly.target_id,
                        "pattern_id": anomaly.pattern_id,
                        "deviation_type": anomaly.deviation_type.value
                        if hasattr(anomaly.deviation_type, "value")
                        else str(anomaly.deviation_type),
                        "deviation_score": anomaly.deviation_score,
                        "expected": anomaly.expected_behavior,
                        "actual": anomaly.actual_behavior,
                    },
                )

        # Check pattern alerts
        fired = self._detector.check_alerts(anomalies)
        self._alerts_fired += len(fired)

        for alert_data in fired:
            if self._event_bus:
                self._event_bus.publish("behavior:alert_fired", data=alert_data)

        # Run behavioral clustering
        clusters = self._detector.cluster_by_behavior()
        if clusters and self._event_bus:
            self._event_bus.publish(
                "behavior:clusters_updated",
                data={
                    "cluster_count": len(clusters),
                    "targets_clustered": sum(c.target_count for c in clusters),
                },
            )

    # -- Persistence -------------------------------------------------------

    def _load_alerts(self) -> None:
        """Load persisted alert rules."""
        try:
            from tritium_lib.models.pattern import PatternAlert
        except ImportError:
            return

        alerts_file = _DATA_DIR / "alerts.json"
        if not alerts_file.exists():
            return

        try:
            with open(alerts_file) as f:
                data = json.load(f)
            for ad in data:
                alert = PatternAlert(**ad)
                self._detector.add_alert(alert)
            self._logger.info("Loaded %d pattern alerts from %s", len(data), alerts_file)
        except Exception as exc:
            self._logger.warning("Failed to load pattern alerts: %s", exc)

    def _save_alerts(self) -> None:
        """Persist alert rules to JSON file."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            alerts_file = _DATA_DIR / "alerts.json"
            alerts = self._detector.list_alerts()
            data = [a.model_dump() for a in alerts]
            with open(alerts_file, "w") as f:
                json.dump(data, f, indent=2)
            self._logger.debug("Saved %d alerts to %s", len(data), alerts_file)
        except Exception as exc:
            self._logger.warning("Failed to save alerts: %s", exc)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
