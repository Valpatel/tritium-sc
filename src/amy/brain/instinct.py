# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""InstinctLayer — Amy's L2 autonomous response layer.

Sits between the L1 reflex layer (immediate sensor reactions) and the
L3/L4 thinking layers (deliberate reasoning). The instinct layer monitors
EventBus events and triggers automatic responses that Amy would intuitively
make without needing to deliberate:

  1. High-threat dossier -> auto-create investigation
  2. Geofence restricted zone entry -> dispatch nearest camera/asset
  3. BLE suspicious classification -> add to watch list, increase surveillance
  4. Correlator target fusion -> narrate in inner monologue

These responses happen faster than the thinking cycle (8s) and ensure
Amy reacts to critical events within 1-2 seconds.

Thread-safe: runs as a daemon thread, subscribes to EventBus.
"""

from __future__ import annotations

import logging
import math
import queue as queue_mod
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..commander import Commander

logger = logging.getLogger("amy.instinct")


class InstinctLayer:
    """Amy's L2 instinct layer — automatic responses to tactical events.

    Subscribes to EventBus and reacts to:
      - threat_escalation (dossier threat_level -> high)
      - geofence:enter (restricted zone intrusion)
      - ble:suspicious_device (suspicious BLE classification)
      - correlation (target fusion events)

    Parameters
    ----------
    commander:
        Reference to the Commander instance for accessing subsystems.
    """

    # Cooldowns to prevent response flooding (seconds)
    INVESTIGATION_COOLDOWN = 30.0
    GEOFENCE_DISPATCH_COOLDOWN = 15.0
    BLE_WATCHLIST_COOLDOWN = 10.0
    CORRELATION_NARRATE_COOLDOWN = 5.0

    def __init__(self, commander: Commander) -> None:
        self._commander = commander
        self._running = False
        self._thread: threading.Thread | None = None
        self._sub: queue_mod.Queue | None = None

        # Cooldown tracking
        self._last_investigation: dict[str, float] = {}
        self._last_geofence_dispatch: dict[str, float] = {}
        self._last_ble_watchlist: dict[str, float] = {}
        self._last_correlation: float = 0.0

        # Watch list: set of MAC addresses under increased surveillance
        self._watch_list: set[str] = set()
        self._watch_list_lock = threading.Lock()

        # Metrics
        self._response_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the instinct layer background thread."""
        if self._running:
            return
        self._running = True
        self._sub = self._commander.event_bus.subscribe()
        self._thread = threading.Thread(
            target=self._instinct_loop,
            name="amy-instinct",
            daemon=True,
        )
        self._thread.start()
        logger.info("Instinct layer started")

    def stop(self) -> None:
        """Stop the instinct layer."""
        self._running = False
        if self._sub is not None:
            self._commander.event_bus.unsubscribe(self._sub)
            self._sub = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("Instinct layer stopped (responses: %d)", self._response_count)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def watch_list(self) -> set[str]:
        """Return a copy of the BLE watch list."""
        with self._watch_list_lock:
            return set(self._watch_list)

    @property
    def response_count(self) -> int:
        return self._response_count

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _instinct_loop(self) -> None:
        """Background loop: listen for events and trigger instinctive responses."""
        while self._running:
            try:
                msg = self._sub.get(timeout=1.0)
            except queue_mod.Empty:
                continue
            except Exception:
                continue

            event_type = msg.get("type", "")
            data = msg.get("data", {})

            try:
                if event_type == "threat_escalation":
                    self._on_threat_escalation(data)
                elif event_type == "geofence:enter":
                    self._on_geofence_enter(data)
                elif event_type in ("ble:suspicious_device", "ble:new_device"):
                    self._on_ble_alert(data)
                elif event_type == "correlation":
                    self._on_correlation(data)
            except Exception as e:
                logger.debug("Instinct handler error: %s", e)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_threat_escalation(self, data: dict) -> None:
        """When threat_level reaches high on a dossier, auto-create investigation.

        Also dispatches nearest asset to the threat position.
        Narrates a detailed threat assessment explaining WHY the target
        was escalated — signal strength, classification, zone, co-location.
        """
        target_id = data.get("target_id", "")
        new_level = data.get("new_level", "")

        if new_level not in ("hostile",):
            return

        now = time.monotonic()
        if now - self._last_investigation.get(target_id, 0) < self.INVESTIGATION_COOLDOWN:
            return
        self._last_investigation[target_id] = now

        commander = self._commander

        # Try to auto-create investigation via DossierManager + InvestigationEngine
        dossier_mgr = getattr(commander, "dossier_manager", None)
        inv_engine = getattr(commander, "investigation_engine", None)

        if dossier_mgr is not None and inv_engine is not None:
            dossier = dossier_mgr.get_dossier_for_target(target_id)
            if dossier is not None:
                dossier_id = dossier.get("dossier_id", "")
                dossier_name = dossier.get("name", target_id[:8])
                inv = inv_engine.auto_investigate_threat(
                    dossier_id, "high", dossier_name=dossier_name,
                )
                if inv is not None:
                    commander.sensorium.push(
                        "thought",
                        f"Threat escalation on {dossier_name} -- "
                        f"opening investigation {inv.inv_id[:8]}",
                        importance=0.8,
                    )
                    commander.event_bus.publish("investigation_created", {
                        "inv_id": inv.inv_id,
                        "target_id": target_id,
                        "threat_level": new_level,
                    })
                    self._response_count += 1

        # Build detailed threat assessment narration
        narration = self._build_threat_narration(target_id, new_level, data)
        commander.sensorium.push(
            "thought",
            narration,
            importance=0.8,
        )
        commander.event_bus.publish("threat_narration", {
            "target_id": target_id,
            "level": new_level,
            "narration": narration,
        })

    def _on_geofence_enter(self, data: dict) -> None:
        """When a target enters a restricted zone, dispatch nearest camera/asset.

        For restricted zones, this is an urgent response -- dispatch immediately.
        For monitored zones, just note it in the sensorium.
        """
        zone_type = data.get("zone_type", "")
        zone_name = data.get("zone_name", "unknown zone")
        target_id = data.get("target_id", "")
        position = data.get("position", [0, 0])

        if isinstance(position, dict):
            pos = (position.get("x", 0), position.get("y", 0))
        elif isinstance(position, (list, tuple)) and len(position) >= 2:
            pos = (float(position[0]), float(position[1]))
        else:
            pos = (0.0, 0.0)

        commander = self._commander

        if zone_type == "restricted":
            # Urgent: dispatch nearest asset
            now = time.monotonic()
            cooldown_key = f"{target_id}:{data.get('zone_id', '')}"
            if now - self._last_geofence_dispatch.get(cooldown_key, 0) < self.GEOFENCE_DISPATCH_COOLDOWN:
                return
            self._last_geofence_dispatch[cooldown_key] = now

            from ..actions.dispatch import find_nearest_asset, dispatch_to_investigate

            tracker = getattr(commander, "target_tracker", None)
            if tracker is not None:
                asset = find_nearest_asset(
                    tracker, pos,
                    asset_types={"drone", "rover", "camera"},
                    require_mobile=True,
                )
                if asset is not None:
                    dispatch_to_investigate(
                        asset.target_id,
                        pos,
                        event_bus=commander.event_bus,
                        mqtt_bridge=getattr(commander, "mqtt_bridge", None),
                        simulation_engine=getattr(commander, "simulation_engine", None),
                        reason=f"geofence_restricted:{zone_name}",
                    )
                    commander.sensorium.push(
                        "thought",
                        f"Restricted zone breach at {zone_name}! "
                        f"Dispatching {asset.name} to investigate.",
                        importance=0.9,
                    )
                    self._response_count += 1
                else:
                    commander.sensorium.push(
                        "thought",
                        f"Restricted zone breach at {zone_name} -- "
                        f"no available assets to dispatch!",
                        importance=0.9,
                    )
        else:
            # Monitored zone: just note it
            commander.sensorium.push(
                "thought",
                f"Target {target_id[:8]} entered {zone_name} ({zone_type} zone).",
                importance=0.4,
            )

        self._response_count += 1

    def _on_ble_alert(self, data: dict) -> None:
        """When BLE classifier marks a device as suspicious, add to watch list.

        Also pushes an observation into the sensorium for Amy's awareness.
        """
        mac = data.get("mac", "")
        level = data.get("level", "")
        name = data.get("name", mac)
        rssi = data.get("rssi", -100)

        if not mac:
            return

        now = time.monotonic()
        if now - self._last_ble_watchlist.get(mac, 0) < self.BLE_WATCHLIST_COOLDOWN:
            return
        self._last_ble_watchlist[mac] = now

        commander = self._commander

        if level == "suspicious":
            # Add to watch list
            with self._watch_list_lock:
                already_watching = mac in self._watch_list
                self._watch_list.add(mac)

            if not already_watching:
                commander.sensorium.push(
                    "thought",
                    f"Suspicious BLE device detected: {name} (MAC: {mac}, "
                    f"RSSI: {rssi}dBm). Adding to watch list. "
                    f"Strong signal suggests close proximity.",
                    importance=0.6,
                )
                commander.event_bus.publish("watchlist_add", {
                    "mac": mac,
                    "name": name,
                    "rssi": rssi,
                    "reason": "ble_suspicious",
                })
            else:
                commander.sensorium.push(
                    "thought",
                    f"Watch list device active: {name} (RSSI: {rssi}dBm). "
                    f"Maintaining surveillance.",
                    importance=0.4,
                )

            self._response_count += 1

        elif level == "new":
            # New device -- note it but don't add to watch list unless strong
            if rssi > -50:
                commander.sensorium.push(
                    "thought",
                    f"New BLE device nearby: {name} (RSSI: {rssi}dBm). "
                    f"Monitoring for patterns.",
                    importance=0.3,
                )
            self._response_count += 1

    def _on_correlation(self, data: dict) -> None:
        """When correlator fuses targets, narrate the fusion in inner monologue.

        Amy explains the intelligence connection she has identified.
        """
        now = time.monotonic()
        if now - self._last_correlation < self.CORRELATION_NARRATE_COOLDOWN:
            return
        self._last_correlation = now

        primary_id = data.get("primary_id", "")
        secondary_id = data.get("secondary_id", "")
        confidence = data.get("confidence", 0.0)
        reason = data.get("reason", "")
        primary_name = data.get("primary_name", primary_id[:8])
        secondary_name = data.get("secondary_name", secondary_id[:8])

        commander = self._commander

        # Build a natural-language narration of the fusion
        narration = self._build_correlation_narration(
            primary_name, secondary_name, confidence, reason, data,
        )

        commander.sensorium.push(
            "thought",
            narration,
            importance=0.6,
        )
        commander.event_bus.publish("correlation_narrated", {
            "primary_id": primary_id,
            "secondary_id": secondary_id,
            "narration": narration,
        })

        self._response_count += 1

    # ------------------------------------------------------------------
    # Threat narration
    # ------------------------------------------------------------------

    def _build_threat_narration(
        self,
        target_id: str,
        threat_level: str,
        data: dict,
    ) -> str:
        """Build a detailed threat assessment narration.

        Amy explains WHY a target was escalated, citing specific evidence:
        signal strength, device classification, zone entry, co-location
        with other devices, behavioral anomalies.

        This gives operators transparency into the AI's threat reasoning.
        """
        commander = self._commander
        reasons: list[str] = []

        # Get target info from tracker
        target_name = target_id[:8]
        target_source = ""
        target_rssi = None
        target_alliance = ""

        tracker = getattr(commander, "target_tracker", None)
        if tracker is not None:
            target = tracker.get_target(target_id)
            if target is not None:
                target_name = getattr(target, "name", target_id[:8])
                target_source = getattr(target, "source", "")
                target_alliance = getattr(target, "alliance", "")
                # Try to get RSSI from target metadata
                meta = getattr(target, "metadata", {}) or {}
                if isinstance(meta, dict):
                    target_rssi = meta.get("rssi")

        # Reason: signal strength
        rssi = data.get("rssi", target_rssi)
        if rssi is not None and isinstance(rssi, (int, float)):
            if rssi > -40:
                reasons.append(f"very strong signal ({rssi}dBm, within ~2m)")
            elif rssi > -60:
                reasons.append(f"strong signal ({rssi}dBm, within ~10m)")
            elif rssi > -80:
                reasons.append(f"moderate signal ({rssi}dBm)")

        # Reason: device classification
        classification = data.get("classification", "")
        if classification == "unknown":
            reasons.append("unknown device type (not in any known device list)")
        elif classification == "suspicious":
            reasons.append("device flagged as suspicious by BLE classifier")
        elif classification:
            reasons.append(f"classified as {classification}")
        elif target_source and "ble" in target_source:
            reasons.append("unclassified BLE device")

        # Reason: zone entry
        zone_name = data.get("zone_name", "")
        zone_type = data.get("zone_type", "")
        if zone_name:
            if zone_type == "restricted":
                reasons.append(f"entered restricted zone '{zone_name}'")
            elif zone_type:
                reasons.append(f"detected in {zone_type} zone '{zone_name}'")

        # Reason: co-location check
        co_located = data.get("co_located_devices", [])
        if co_located:
            known_count = sum(1 for d in co_located if d.get("known", False))
            unknown_count = len(co_located) - known_count
            if unknown_count > 0 and known_count == 0:
                reasons.append(f"co-located with {unknown_count} unknown device(s) and no known devices")
            elif unknown_count > 0:
                reasons.append(f"co-located with {unknown_count} unknown and {known_count} known device(s)")
        elif data.get("alone", False):
            reasons.append("no known devices co-located nearby")

        # Reason: behavioral anomaly
        anomaly = data.get("anomaly", "")
        if anomaly:
            reasons.append(f"behavioral anomaly: {anomaly}")

        # Reason: dwell time
        dwell_s = data.get("dwell_seconds")
        if dwell_s is not None and isinstance(dwell_s, (int, float)) and dwell_s > 0:
            if dwell_s > 3600:
                reasons.append(f"dwelling for {dwell_s / 3600:.1f} hours")
            elif dwell_s > 300:
                reasons.append(f"dwelling for {dwell_s / 60:.0f} minutes")

        # Reason: first seen (new device)
        if data.get("first_seen_recently", False):
            reasons.append("first detected recently (new to this area)")

        # Build the narration
        if not reasons:
            reasons.append("multiple indicators exceeded threat threshold")

        reasons_text = "; ".join(reasons)
        return (
            f"Target {target_name} is suspicious because: {reasons_text}. "
            f"Escalating threat level to {threat_level}. Heightening surveillance."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_correlation_narration(
        self,
        primary_name: str,
        secondary_name: str,
        confidence: float,
        reason: str,
        data: dict,
    ) -> str:
        """Build a natural-language narration of a target correlation.

        Amy narrates the fusion as part of her inner monologue, explaining
        what she has identified and why.
        """
        pct = int(confidence * 100)

        # Determine the source types for a richer narration
        primary_source = data.get("primary_source", "")
        secondary_source = data.get("secondary_source", "")

        if "ble" in secondary_source and "camera" in primary_source:
            return (
                f"I've identified that the BLE device '{secondary_name}' "
                f"belongs to the same entity tracked visually as "
                f"'{primary_name}'. {pct}% confidence via {reason}."
            )
        elif "camera" in secondary_source and "ble" in primary_source:
            return (
                f"The person near the camera matches the BLE device "
                f"'{primary_name}'. Fusing into a single track. "
                f"{pct}% confidence."
            )
        elif reason == "spatial":
            return (
                f"Spatial correlation: '{primary_name}' and "
                f"'{secondary_name}' are co-located. Fusing tracks at "
                f"{pct}% confidence."
            )
        elif reason == "temporal":
            return (
                f"Temporal pattern match: '{primary_name}' and "
                f"'{secondary_name}' move together. Fusing identities at "
                f"{pct}% confidence."
            )
        else:
            return (
                f"Correlated '{primary_name}' with '{secondary_name}' -- "
                f"these appear to be the same entity. {pct}% confidence"
                f"{f' via {reason}' if reason else ''}."
            )

    def add_to_watch_list(self, mac: str) -> None:
        """Manually add a MAC to the watch list."""
        with self._watch_list_lock:
            self._watch_list.add(mac.upper())

    def remove_from_watch_list(self, mac: str) -> None:
        """Remove a MAC from the watch list."""
        with self._watch_list_lock:
            self._watch_list.discard(mac.upper())

    def is_on_watch_list(self, mac: str) -> bool:
        """Check if a MAC is on the watch list."""
        with self._watch_list_lock:
            return mac.upper() in self._watch_list
