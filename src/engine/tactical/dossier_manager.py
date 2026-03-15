# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DossierManager — bridges TargetTracker (real-time) and DossierStore (persistent).

The DossierManager listens to EventBus for correlation, detection, and
enrichment events and translates them into persistent dossier records.
It provides a unified API surface over the real-time tracker and the
SQLite-backed DossierStore, so callers never need to juggle both.

Lifecycle:
  1. Subscribes to EventBus for:
       - correlation events (correlator fused two targets)
       - ble:new_device (new BLE device appeared)
       - detections (YOLO detection)
       - enrichment_complete (enrichment pipeline finished)
       - geofence:enter / geofence:exit (zone transition events)
  2. On each event, find-or-create a dossier and attach signals.
  3. Periodic flush (every 30s) persists dirty dossiers to the store.

Thread-safety: all public methods are safe to call from any thread.
"""

from __future__ import annotations

import logging
import math
import queue as queue_mod
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..comms.event_bus import EventBus
    from .target_tracker import TargetTracker

logger = logging.getLogger("dossier_manager")


class DossierManager:
    """Bridges TargetTracker (real-time) and DossierStore (persistent).

    Parameters
    ----------
    store:
        A ``DossierStore`` instance for persistence.
    tracker:
        The ``TargetTracker`` for real-time target state.
    event_bus:
        Optional ``EventBus`` to subscribe to for automatic dossier creation.
    flush_interval:
        Seconds between periodic flushes of dirty dossiers (default 30).
    """

    def __init__(
        self,
        store,
        tracker: TargetTracker | None = None,
        event_bus: EventBus | None = None,
        flush_interval: float = 30.0,
    ) -> None:
        self._store = store
        self._tracker = tracker
        self._event_bus = event_bus
        self._flush_interval = flush_interval

        # Map target_id -> dossier_id for fast lookup
        self._target_dossier_map: dict[str, str] = {}
        self._lock = threading.Lock()

        # Dirty dossier_ids that need flushing (updated via add_signal etc.)
        self._dirty: set[str] = set()

        # Background threads
        self._running = False
        self._listener_thread: threading.Thread | None = None
        self._flush_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background listener and flush threads."""
        if self._running:
            return
        self._running = True

        if self._event_bus is not None:
            self._listener_thread = threading.Thread(
                target=self._event_listener_loop,
                name="dossier-listener",
                daemon=True,
            )
            self._listener_thread.start()

        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="dossier-flush",
            daemon=True,
        )
        self._flush_thread.start()
        logger.info("DossierManager started (flush every %.0fs)", self._flush_interval)

    def stop(self) -> None:
        """Stop background threads and flush remaining dirty dossiers."""
        self._running = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=3.0)
            self._listener_thread = None
        if self._flush_thread is not None:
            self._flush_thread.join(timeout=3.0)
            self._flush_thread = None
        # Final flush
        self._flush_dirty()
        logger.info("DossierManager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_dossier_for_target(self, target_id: str) -> dict | None:
        """Get the full dossier linked to a tracked target.

        Returns a dossier dict (from DossierStore) or None.
        """
        with self._lock:
            dossier_id = self._target_dossier_map.get(target_id)
        if dossier_id is None:
            # Try to find by identifier (MAC-based lookup)
            if target_id.startswith("ble_"):
                raw = target_id[4:]
                if len(raw) == 12:
                    mac = ":".join(raw[i:i + 2] for i in range(0, 12, 2)).upper()
                    dossier = self._store.find_by_identifier("mac", mac)
                    if dossier:
                        with self._lock:
                            self._target_dossier_map[target_id] = dossier["dossier_id"]
                        return dossier
            return None
        return self._store.get_dossier(dossier_id)

    def get_all_active_dossiers(self, limit: int = 50, since: float | None = None) -> list[dict]:
        """Get recently active dossiers.

        Parameters
        ----------
        limit:
            Max dossiers to return.
        since:
            Only dossiers with last_seen >= since. Defaults to last 24h.
        """
        if since is None:
            since = time.time() - 86400  # last 24 hours
        return self._store.get_recent(limit=limit, since=since)

    def find_or_create_for_target(self, target_id: str, **kwargs) -> str:
        """Find existing dossier for target, or create a new one.

        Returns the dossier_id.
        """
        with self._lock:
            existing = self._target_dossier_map.get(target_id)
        if existing is not None:
            return existing

        # Try identifier lookup for BLE targets
        if target_id.startswith("ble_"):
            raw = target_id[4:]
            if len(raw) == 12:
                mac = ":".join(raw[i:i + 2] for i in range(0, 12, 2)).upper()
                dossier = self._store.find_by_identifier("mac", mac)
                if dossier:
                    dossier_id = dossier["dossier_id"]
                    with self._lock:
                        self._target_dossier_map[target_id] = dossier_id
                    return dossier_id

        # Create new dossier
        name = kwargs.get("name", target_id)
        entity_type = kwargs.get("entity_type", "unknown")
        identifiers = kwargs.get("identifiers", {})
        tags = kwargs.get("tags", [])

        dossier_id = self._store.create_dossier(
            name=name,
            entity_type=entity_type,
            identifiers=identifiers,
            tags=tags,
        )
        with self._lock:
            self._target_dossier_map[target_id] = dossier_id
        logger.info("Created dossier %s for target %s", dossier_id[:8], target_id)

        # Broadcast new dossier creation via EventBus -> WebSocket
        if self._event_bus is not None:
            self._event_bus.publish("dossier_created", data={
                "dossier_id": dossier_id,
                "target_id": target_id,
                "name": name,
                "entity_type": entity_type,
                "identifiers": identifiers,
                "tags": tags,
            })

        return dossier_id

    def add_signal_to_target(
        self,
        target_id: str,
        source: str,
        signal_type: str,
        data: dict | None = None,
        *,
        confidence: float = 0.5,
    ) -> str | None:
        """Add a signal to the dossier for a target.

        Returns signal_id or None if no dossier exists for this target.
        """
        with self._lock:
            dossier_id = self._target_dossier_map.get(target_id)
        if dossier_id is None:
            return None

        signal_id = self._store.add_signal(
            dossier_id=dossier_id,
            source=source,
            signal_type=signal_type,
            data=data,
            confidence=confidence,
        )
        with self._lock:
            self._dirty.add(dossier_id)
        return signal_id

    def add_enrichment_to_target(
        self,
        target_id: str,
        provider: str,
        enrichment_type: str,
        data: dict | None = None,
    ) -> int | None:
        """Add enrichment data to the dossier for a target.

        Returns enrichment row id or None if no dossier exists.
        """
        with self._lock:
            dossier_id = self._target_dossier_map.get(target_id)
        if dossier_id is None:
            return None

        eid = self._store.add_enrichment(
            dossier_id=dossier_id,
            provider=provider,
            enrichment_type=enrichment_type,
            data=data,
        )
        with self._lock:
            self._dirty.add(dossier_id)
        return eid

    def add_tag(self, dossier_id: str, tag: str) -> bool:
        """Add a tag to a dossier. Returns True if the dossier exists."""
        dossier = self._store.get_dossier(dossier_id)
        if dossier is None:
            return False

        tags = dossier.get("tags", [])
        if tag not in tags:
            tags.append(tag)
            self._store._update_json_field(dossier_id, "tags", tags)
        return True

    def add_note(self, dossier_id: str, note: str) -> bool:
        """Add a note to a dossier. Returns True if the dossier exists."""
        dossier = self._store.get_dossier(dossier_id)
        if dossier is None:
            return False

        notes = dossier.get("notes", [])
        notes.append(note)
        self._store._update_json_field(dossier_id, "notes", notes)
        return True

    def merge(self, primary_id: str, secondary_id: str) -> bool:
        """Merge secondary dossier into primary. Returns True on success."""
        result = self._store.merge_dossiers(primary_id, secondary_id)
        if result:
            # Update target->dossier mappings
            with self._lock:
                for tid, did in list(self._target_dossier_map.items()):
                    if did == secondary_id:
                        self._target_dossier_map[tid] = primary_id
            logger.info("Merged dossier %s into %s", secondary_id[:8], primary_id[:8])
        return result

    def search(self, query: str) -> list[dict]:
        """Full-text search across dossiers."""
        return self._store.search(query)

    def get_dossier(self, dossier_id: str) -> dict | None:
        """Get a full dossier by ID."""
        return self._store.get_dossier(dossier_id)

    def list_dossiers(
        self,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "last_seen",
        order: str = "desc",
    ) -> list[dict]:
        """List dossiers with pagination and sorting."""
        # The store's get_recent handles last_seen desc; for other sorts
        # we fetch more and sort in Python (SQLite store is simple).
        all_recent = self._store.get_recent(limit=limit + offset)
        if sort_by == "first_seen":
            all_recent.sort(key=lambda d: d.get("first_seen", 0), reverse=(order == "desc"))
        elif sort_by == "confidence":
            all_recent.sort(key=lambda d: d.get("confidence", 0), reverse=(order == "desc"))
        elif sort_by == "threat_level":
            _tl_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
            all_recent.sort(
                key=lambda d: _tl_order.get(d.get("threat_level", "none"), 0),
                reverse=(order == "desc"),
            )
        elif sort_by == "name":
            all_recent.sort(key=lambda d: d.get("name", ""), reverse=(order == "desc"))
        # Default: already sorted by last_seen desc

        return all_recent[offset:offset + limit]

    # ------------------------------------------------------------------
    # EventBus listener
    # ------------------------------------------------------------------

    def _event_listener_loop(self) -> None:
        """Background loop: listen to EventBus for dossier-relevant events."""
        bus_queue = self._event_bus.subscribe()
        try:
            while self._running:
                try:
                    msg = bus_queue.get(timeout=1.0)
                except queue_mod.Empty:
                    continue

                event_type = msg.get("type", "")
                data = msg.get("data", {})

                try:
                    if event_type == "correlation":
                        self._handle_correlation(data)
                    elif event_type == "ble:new_device":
                        self._handle_ble_device(data)
                    elif event_type in ("fleet.ble_presence", "edge:ble_update"):
                        self._handle_ble_presence(data)
                    elif event_type == "fleet.ble_sighting":
                        self._handle_ble_sighting(data)
                    elif event_type == "fleet.wifi_presence":
                        self._handle_wifi_presence(data)
                    elif event_type in ("detections", "detection:camera", "detection:camera:fusion"):
                        self._handle_detection(data)
                    elif event_type == "enrichment_complete":
                        self._handle_enrichment(data)
                    elif event_type in ("meshtastic:nodes_updated", "meshtastic:node_update"):
                        self._handle_meshtastic(data)
                    elif event_type in ("geofence:enter", "geofence:exit"):
                        self._handle_geofence_event(event_type, data)
                except Exception:
                    logger.warning("DossierManager event error", exc_info=True)
        finally:
            self._event_bus.unsubscribe(bus_queue)

    def _handle_correlation(self, data: dict) -> None:
        """Handle a correlation event: two targets were fused.

        When BLE + camera (or any two sources) are correlated, auto-enrich
        the merged dossier with combined intelligence from both sources.
        """
        primary_id = data.get("primary_id", "")
        secondary_id = data.get("secondary_id", "")
        if not primary_id or not secondary_id:
            return

        # Ensure both have dossiers
        p_dossier = self.find_or_create_for_target(
            primary_id,
            name=data.get("primary_name", primary_id),
        )
        s_dossier = self.find_or_create_for_target(
            secondary_id,
            name=data.get("secondary_name", secondary_id),
        )

        # Add correlation signal to primary
        self._store.add_signal(
            dossier_id=p_dossier,
            source="correlator",
            signal_type="correlation",
            data={
                "correlated_with": secondary_id,
                "confidence": data.get("confidence", 0.0),
                "reason": data.get("reason", ""),
            },
            confidence=data.get("confidence", 0.5),
        )

        # If they have different dossiers, merge them
        if p_dossier != s_dossier:
            self.merge(p_dossier, s_dossier)

        # Auto-enrich the merged dossier with correlation context
        self._auto_enrich_on_correlation(p_dossier, primary_id, secondary_id, data)

    def _handle_ble_presence(self, data: dict) -> None:
        """Handle fleet.ble_presence events (from demo generators and edge nodes).

        These contain a list of BLE devices under 'devices', each with
        'addr' (or 'mac'), 'name', 'rssi', and 'type'.
        """
        devices = data.get("devices", [])
        for dev in devices:
            mac = dev.get("addr", dev.get("mac", ""))
            if not mac:
                continue
            name = dev.get("name") or mac
            target_id = f"ble_{mac.replace(':', '').lower()}"

            identifiers = {"mac": mac.upper()}
            if dev.get("name"):
                identifiers["name"] = dev["name"]

            entity_type = "device"
            dev_type = dev.get("type", "")
            if dev_type in ("phone", "smartphone"):
                entity_type = "phone"
            elif dev_type in ("watch", "wearable"):
                entity_type = "wearable"

            self.find_or_create_for_target(
                target_id,
                name=name,
                entity_type=entity_type,
                identifiers=identifiers,
                tags=["ble", dev_type] if dev_type else ["ble"],
            )

            self.add_signal_to_target(
                target_id,
                source="ble",
                signal_type="presence",
                data={
                    "mac": mac,
                    "rssi": dev.get("rssi", -100),
                    "name": name,
                    "type": dev_type,
                    "node_id": data.get("node_id", ""),
                },
                confidence=max(0.0, min(1.0, (dev.get("rssi", -100) + 100) / 70)),
            )

    def _handle_ble_sighting(self, data: dict) -> None:
        """Handle fleet.ble_sighting events (from fusion scenario)."""
        sighting = data.get("sighting", data)
        mac = sighting.get("mac", "")
        if not mac:
            return
        target_id = f"ble_{mac.replace(':', '').lower()}"
        name = sighting.get("name") or mac

        identifiers = {"mac": mac.upper()}
        if sighting.get("name"):
            identifiers["name"] = sighting["name"]

        self.find_or_create_for_target(
            target_id,
            name=name,
            entity_type="device",
            identifiers=identifiers,
            tags=["ble"],
        )

        self.add_signal_to_target(
            target_id,
            source="ble",
            signal_type="sighting",
            data={
                "mac": mac,
                "rssi": sighting.get("rssi", -100),
                "manufacturer": sighting.get("manufacturer", ""),
                "device_class": sighting.get("device_class", ""),
            },
            confidence=max(0.0, min(1.0, (sighting.get("rssi", -100) + 100) / 70)),
        )

    def _handle_ble_device(self, data: dict) -> None:
        """Handle a new BLE device event."""
        mac = data.get("mac", "")
        if not mac:
            return
        target_id = f"ble_{mac.replace(':', '').lower()}"
        name = data.get("name") or mac

        identifiers = {"mac": mac.upper()}
        if data.get("name"):
            identifiers["name"] = data["name"]

        self.find_or_create_for_target(
            target_id,
            name=name,
            entity_type="device",
            identifiers=identifiers,
            tags=["ble"],
        )

        # Add the sighting as a signal
        self.add_signal_to_target(
            target_id,
            source="ble",
            signal_type="mac_sighting",
            data={
                "mac": mac,
                "rssi": data.get("rssi", -100),
                "name": name,
            },
            confidence=max(0.0, min(1.0, (data.get("rssi", -100) + 100) / 70)),
        )

    def _handle_wifi_presence(self, data: dict) -> None:
        """Handle fleet.wifi_presence events — enrich BLE dossiers with WiFi probe SSIDs.

        When an edge node reports WiFi networks (including probe requests),
        check if any existing BLE device dossiers were created from the same
        observer node. If so, add the probed SSIDs as enrichment data.

        This lets us say: "This device probes for HomeNet-5G — likely a
        home network user" in the dossier.
        """
        node_id = data.get("node_id", "")
        networks = data.get("networks", [])
        if not networks or not node_id:
            return

        # Extract probe SSIDs (networks that the device probed for, not APs)
        probe_ssids = []
        ap_ssids = []
        for net in networks:
            ssid = net.get("ssid", "")
            if not ssid:
                continue
            # If network has a 'probe' flag or is marked as probe request
            if net.get("probe", False) or net.get("type") == "probe":
                probe_ssids.append(ssid)
            else:
                ap_ssids.append(ssid)

        # If no explicit probe flag, treat all SSIDs as environmental WiFi data
        all_ssids = probe_ssids or ap_ssids
        if not all_ssids:
            return

        # Find BLE dossiers that share the same observer node
        enriched_count = 0
        with self._lock:
            for target_id, dossier_id in list(self._target_dossier_map.items()):
                if not target_id.startswith("ble_"):
                    continue

                # Check if this BLE target was reported by the same node
                dossier = self._store.get_dossier(dossier_id)
                if dossier is None:
                    continue

                # Look through signals for matching node_id
                signals = dossier.get("signals", [])
                same_node = any(
                    s.get("data", {}).get("node_id") == node_id
                    for s in signals
                    if isinstance(s.get("data"), dict)
                )

                if not same_node:
                    continue

                # Enrich dossier with WiFi probe SSIDs
                ssid_summary = ", ".join(all_ssids[:5])
                if len(all_ssids) > 5:
                    ssid_summary += f" (+{len(all_ssids) - 5} more)"

                note = (
                    f"WiFi probe enrichment from observer {node_id}: "
                    f"device probes for {ssid_summary} — "
                    f"{'likely a home/work network user' if len(all_ssids) <= 3 else 'probes multiple networks'}"
                )

                # Add as enrichment (not signal) for richer dossier context
                self._store.add_enrichment(
                    dossier_id=dossier_id,
                    provider="wifi_probe_enrichment",
                    enrichment_type="probed_ssids",
                    data={
                        "node_id": node_id,
                        "ssids": all_ssids[:20],  # cap at 20 SSIDs
                        "probe_ssids": probe_ssids[:20],
                        "ap_ssids": ap_ssids[:20],
                        "note": note,
                    },
                )
                self._dirty.add(dossier_id)
                enriched_count += 1

        if enriched_count:
            logger.info(
                "WiFi probe enriched %d BLE dossiers from node %s (%d SSIDs)",
                enriched_count, node_id, len(all_ssids),
            )

    def _handle_meshtastic(self, data: dict) -> None:
        """Handle meshtastic:nodes_updated events — create dossiers for mesh radio nodes."""
        nodes = data.get("nodes", [])
        for node in nodes:
            node_id = node.get("id", node.get("node_id", ""))
            if not node_id:
                continue
            target_id = f"mesh_{node_id}"
            name = node.get("long_name") or node.get("short_name") or node.get("name") or node_id

            identifiers = {"node_id": str(node_id)}
            if node.get("long_name"):
                identifiers["long_name"] = node["long_name"]

            self.find_or_create_for_target(
                target_id,
                name=name,
                entity_type="mesh_radio",
                identifiers=identifiers,
                tags=["meshtastic", "lora"],
            )

            signal_data = {
                "node_id": node_id,
                "name": name,
            }
            if node.get("lat") is not None:
                signal_data["lat"] = node["lat"]
                signal_data["lon"] = node.get("lon", node.get("lng", 0))
            if node.get("snr") is not None:
                signal_data["snr"] = node["snr"]
            if node.get("battery") is not None:
                signal_data["battery"] = node["battery"]

            self.add_signal_to_target(
                target_id,
                source="meshtastic",
                signal_type="node_telemetry",
                data=signal_data,
                confidence=0.9,
            )

    def _handle_detection(self, data: dict) -> None:
        """Handle a YOLO detection event."""
        detections = data.get("detections", [])
        if isinstance(data, list):
            detections = data

        for det in detections:
            # Generators may use 'label' instead of 'class_name'
            class_name = det.get("class_name") or det.get("label", "unknown")
            confidence = det.get("confidence", 0.0)
            if confidence < 0.4:
                continue

            # Build a target_id matching TargetTracker convention
            det_id = det.get("target_id") or det.get("id", f"det_{class_name}")

            entity_type = "person" if class_name == "person" else "unknown"
            if class_name in ("car", "motorcycle", "bicycle", "truck", "bus"):
                entity_type = "vehicle"

            dossier_id = self.find_or_create_for_target(
                det_id,
                name=f"{class_name.title()} Detection",
                entity_type=entity_type,
                tags=["yolo", class_name],
            )

            self._store.add_signal(
                dossier_id=dossier_id,
                source="yolo",
                signal_type="visual_detection",
                data={
                    "class_name": class_name,
                    "confidence": confidence,
                    "bbox": det.get("bbox"),
                },
                confidence=confidence,
            )

    def _handle_enrichment(self, data: dict) -> None:
        """Handle enrichment results arriving for a target."""
        target_id = data.get("target_id", "")
        results = data.get("results", [])
        if not target_id:
            return

        for result in results:
            self.add_enrichment_to_target(
                target_id,
                provider=result.get("provider", "unknown"),
                enrichment_type=result.get("enrichment_type", "unknown"),
                data=result.get("data", {}),
            )

    # ------------------------------------------------------------------
    # Auto-enrichment on correlation
    # ------------------------------------------------------------------

    def _auto_enrich_on_correlation(
        self,
        dossier_id: str,
        primary_id: str,
        secondary_id: str,
        data: dict,
    ) -> None:
        """Auto-populate dossier when a target is first correlated.

        When BLE + camera are fused, combine the intelligence:
        - BLE provides MAC, manufacturer, device type, RSSI history
        - Camera provides visual class, bounding box, appearance
        This creates a richer dossier than either source alone.
        """
        sources = set()
        if primary_id.startswith("ble_"):
            sources.add("ble")
        elif primary_id.startswith("det_"):
            sources.add("camera")
        elif primary_id.startswith("mesh_"):
            sources.add("mesh")
        elif primary_id.startswith("wifi_"):
            sources.add("wifi")

        if secondary_id.startswith("ble_"):
            sources.add("ble")
        elif secondary_id.startswith("det_"):
            sources.add("camera")
        elif secondary_id.startswith("mesh_"):
            sources.add("mesh")
        elif secondary_id.startswith("wifi_"):
            sources.add("wifi")

        # Build fusion summary
        fusion_type = "+".join(sorted(sources)) if sources else "unknown"
        confidence = data.get("confidence", 0.0)

        enrichment_data = {
            "fusion_type": fusion_type,
            "primary_id": primary_id,
            "secondary_id": secondary_id,
            "source_count": len(sources),
            "sources": sorted(sources),
            "confidence": confidence,
            "reason": data.get("reason", ""),
        }

        # Infer entity type upgrade from correlation
        if "ble" in sources and "camera" in sources:
            enrichment_data["inferred_entity"] = "person_with_device"
            enrichment_data["description"] = (
                f"BLE device {primary_id if primary_id.startswith('ble_') else secondary_id} "
                f"correlated with visual detection — confirmed as person carrying device"
            )
        elif "mesh" in sources and "camera" in sources:
            enrichment_data["inferred_entity"] = "person_with_radio"
            enrichment_data["description"] = (
                "Mesh radio correlated with visual detection — person carrying LoRa device"
            )
        else:
            enrichment_data["description"] = (
                f"Multi-sensor correlation: {fusion_type} (confidence={confidence:.2f})"
            )

        self._store.add_enrichment(
            dossier_id=dossier_id,
            provider="auto_correlation",
            enrichment_type="fusion_profile",
            data=enrichment_data,
        )

        with self._lock:
            self._dirty.add(dossier_id)

        logger.info(
            "Auto-enriched dossier %s on %s correlation (confidence=%.2f)",
            dossier_id[:8], fusion_type, confidence,
        )

    # ------------------------------------------------------------------
    # Geofence event handling
    # ------------------------------------------------------------------

    def _handle_geofence_event(self, event_type: str, data: dict) -> None:
        """Record geofence enter/exit events in the target's dossier history.

        When a dossier target enters or exits a geofence zone, add an event
        signal to their dossier for timeline display.
        """
        target_id = data.get("target_id", "")
        if not target_id:
            return

        zone_name = data.get("zone_name", "unknown")
        zone_type = data.get("zone_type", "monitored")
        zone_id = data.get("zone_id", "")
        position = data.get("position", [0.0, 0.0])
        timestamp = data.get("timestamp", time.time())

        transition = "entered" if event_type == "geofence:enter" else "exited"

        # Find or create dossier for this target
        with self._lock:
            dossier_id = self._target_dossier_map.get(target_id)
        if dossier_id is None:
            # Create dossier for any zone entry (not just restricted)
            if event_type == "geofence:enter":
                tags = ["geofence_alert"] if zone_type == "restricted" else []
                dossier_id = self.find_or_create_for_target(
                    target_id, name=target_id, tags=tags,
                )
            else:
                return

        # Add geofence signal to dossier
        pos_x = position[0] if len(position) > 0 else None
        pos_y = position[1] if len(position) > 1 else None

        self._store.add_signal(
            dossier_id=dossier_id,
            source="geofence",
            signal_type=f"zone_{transition}",
            data={
                "zone_id": zone_id,
                "zone_name": zone_name,
                "zone_type": zone_type,
                "transition": transition,
            },
            position_x=pos_x,
            position_y=pos_y,
            confidence=1.0,
            timestamp=timestamp,
        )

        with self._lock:
            self._dirty.add(dossier_id)

        logger.info(
            "Dossier %s: target %s %s zone '%s' (%s)",
            dossier_id[:8], target_id[:12], transition, zone_name, zone_type,
        )

    # ------------------------------------------------------------------
    # Signal history timeline
    # ------------------------------------------------------------------

    def get_signal_history(
        self,
        dossier_id: str,
        signal_type: str | None = None,
        source: str | None = None,
        limit: int = 200,
        since: float | None = None,
    ) -> list[dict]:
        """Get signal history timeline for a dossier.

        Returns chronologically ordered signals with RSSI values,
        timestamps, and positions for chart rendering.

        Parameters
        ----------
        dossier_id:
            The dossier to query.
        signal_type:
            Filter by signal type (e.g. 'presence', 'sighting').
        source:
            Filter by source (e.g. 'ble', 'yolo').
        limit:
            Max records to return.
        since:
            Only signals after this timestamp.
        """
        dossier = self._store.get_dossier(dossier_id)
        if dossier is None:
            return []

        signals = dossier.get("signals", [])

        # Filter
        if signal_type:
            signals = [s for s in signals if s.get("signal_type") == signal_type]
        if source:
            signals = [s for s in signals if s.get("source") == source]
        if since:
            signals = [s for s in signals if s.get("timestamp", 0) >= since]

        # Sort chronologically (oldest first for timeline)
        signals.sort(key=lambda s: s.get("timestamp", 0))

        # Extract timeline data points
        timeline = []
        for sig in signals[-limit:]:
            data = sig.get("data", {})
            point = {
                "timestamp": sig.get("timestamp", 0),
                "source": sig.get("source", ""),
                "signal_type": sig.get("signal_type", ""),
                "confidence": sig.get("confidence", 0),
            }
            # Include RSSI if available
            rssi = data.get("rssi")
            if rssi is not None:
                point["rssi"] = rssi
            # Include position if available
            if sig.get("position_x") is not None:
                point["position_x"] = sig["position_x"]
                point["position_y"] = sig.get("position_y")
            # Include geofence data if present
            if sig.get("signal_type", "").startswith("zone_"):
                point["zone_name"] = data.get("zone_name", "")
                point["zone_type"] = data.get("zone_type", "")
                point["transition"] = data.get("transition", "")
            timeline.append(point)

        return timeline

    # ------------------------------------------------------------------
    # Location history summary
    # ------------------------------------------------------------------

    def get_location_summary(self, dossier_id: str) -> dict:
        """Build a location history summary for a dossier.

        Computes zones visited, time spent per zone, and position history
        from geofence signals and tracker sync signals.

        Returns
        -------
        dict with:
            zones_visited: list of {zone_name, zone_type, first_seen, last_seen, duration_s, visit_count}
            position_count: number of position records
            positions: list of {x, y, timestamp} (last 50)
            total_distance: estimated total distance traveled
        """
        dossier = self._store.get_dossier(dossier_id)
        if dossier is None:
            return {"zones_visited": [], "position_count": 0, "positions": [], "total_distance": 0.0}

        signals = dossier.get("signals", [])
        signals.sort(key=lambda s: s.get("timestamp", 0))

        # Build zone visit timeline from geofence signals
        zone_visits: dict[str, dict] = {}  # zone_id -> aggregated visit data
        zone_entries: dict[str, float] = {}  # zone_id -> last entry timestamp

        for sig in signals:
            stype = sig.get("signal_type", "")
            data = sig.get("data", {})
            ts = sig.get("timestamp", 0)

            if stype == "zone_entered":
                zone_id = data.get("zone_id", "")
                if zone_id:
                    zone_entries[zone_id] = ts
                    if zone_id not in zone_visits:
                        zone_visits[zone_id] = {
                            "zone_name": data.get("zone_name", "unknown"),
                            "zone_type": data.get("zone_type", "monitored"),
                            "first_seen": ts,
                            "last_seen": ts,
                            "duration_s": 0.0,
                            "visit_count": 1,
                        }
                    else:
                        zone_visits[zone_id]["visit_count"] += 1
                        zone_visits[zone_id]["last_seen"] = ts

            elif stype == "zone_exited":
                zone_id = data.get("zone_id", "")
                if zone_id and zone_id in zone_entries:
                    entry_ts = zone_entries.pop(zone_id, ts)
                    duration = max(0, ts - entry_ts)
                    if zone_id in zone_visits:
                        zone_visits[zone_id]["duration_s"] += duration
                        zone_visits[zone_id]["last_seen"] = ts

        # Collect position history from tracker_sync and positioned signals
        positions = []
        for sig in signals:
            px = sig.get("position_x")
            py = sig.get("position_y")
            if px is not None and py is not None:
                positions.append({
                    "x": px,
                    "y": py,
                    "timestamp": sig.get("timestamp", 0),
                })

        # Calculate total distance
        total_distance = 0.0
        for i in range(1, len(positions)):
            dx = positions[i]["x"] - positions[i - 1]["x"]
            dy = positions[i]["y"] - positions[i - 1]["y"]
            total_distance += math.sqrt(dx * dx + dy * dy)

        return {
            "zones_visited": sorted(
                zone_visits.values(),
                key=lambda z: z["duration_s"],
                reverse=True,
            ),
            "position_count": len(positions),
            "positions": positions[-50:],  # last 50 positions
            "total_distance": round(total_distance, 2),
        }

    # ------------------------------------------------------------------
    # Behavioral profile
    # ------------------------------------------------------------------

    def get_behavioral_profile(self, dossier_id: str) -> dict:
        """Compute a behavioral profile from signal history.

        Analyzes movement patterns from position data, RSSI trends,
        and activity timestamps to classify behavior.

        Returns
        -------
        dict with:
            movement_pattern: 'stationary' | 'mobile' | 'patrol' | 'unknown'
            average_speed: float (units per second)
            max_speed: float
            activity_hours: list of ints (hours of day when active, 0-23)
            signal_count: int
            source_breakdown: dict[source, count]
            rssi_stats: {min, max, mean, trend}
            first_seen: float
            last_seen: float
            active_duration_s: float
        """
        dossier = self._store.get_dossier(dossier_id)
        if dossier is None:
            return {
                "movement_pattern": "unknown",
                "average_speed": 0.0,
                "max_speed": 0.0,
                "activity_hours": [],
                "signal_count": 0,
                "source_breakdown": {},
                "rssi_stats": {},
                "first_seen": 0,
                "last_seen": 0,
                "active_duration_s": 0,
            }

        signals = dossier.get("signals", [])
        signals.sort(key=lambda s: s.get("timestamp", 0))

        if not signals:
            return {
                "movement_pattern": "unknown",
                "average_speed": 0.0,
                "max_speed": 0.0,
                "activity_hours": [],
                "signal_count": 0,
                "source_breakdown": {},
                "rssi_stats": {},
                "first_seen": dossier.get("first_seen", 0),
                "last_seen": dossier.get("last_seen", 0),
                "active_duration_s": 0,
            }

        # Source breakdown
        source_breakdown: dict[str, int] = defaultdict(int)
        for sig in signals:
            source_breakdown[sig.get("source", "unknown")] += 1

        # RSSI stats from BLE signals
        rssi_values = []
        for sig in signals:
            data = sig.get("data", {})
            if isinstance(data, dict):
                rssi = data.get("rssi")
                if rssi is not None and isinstance(rssi, (int, float)):
                    rssi_values.append(rssi)

        rssi_stats: dict = {}
        if rssi_values:
            rssi_stats["min"] = min(rssi_values)
            rssi_stats["max"] = max(rssi_values)
            rssi_stats["mean"] = round(sum(rssi_values) / len(rssi_values), 1)
            # Simple trend: compare first half avg to second half avg
            mid = len(rssi_values) // 2
            if mid > 0:
                first_half = sum(rssi_values[:mid]) / mid
                second_half = sum(rssi_values[mid:]) / (len(rssi_values) - mid)
                diff = second_half - first_half
                if diff > 3:
                    rssi_stats["trend"] = "approaching"
                elif diff < -3:
                    rssi_stats["trend"] = "receding"
                else:
                    rssi_stats["trend"] = "stable"
            else:
                rssi_stats["trend"] = "insufficient_data"

        # Activity hours
        activity_hours_set: set[int] = set()
        for sig in signals:
            ts = sig.get("timestamp", 0)
            if ts > 0:
                import datetime as dt
                hour = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).hour
                activity_hours_set.add(hour)

        # Position-based movement analysis
        positions_with_time = []
        for sig in signals:
            px = sig.get("position_x")
            py = sig.get("position_y")
            ts = sig.get("timestamp", 0)
            if px is not None and py is not None and ts > 0:
                positions_with_time.append((px, py, ts))

        speeds = []
        total_distance = 0.0
        for i in range(1, len(positions_with_time)):
            x1, y1, t1 = positions_with_time[i - 1]
            x2, y2, t2 = positions_with_time[i]
            dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            dt_sec = t2 - t1
            if dt_sec > 0:
                speed = dist / dt_sec
                speeds.append(speed)
                total_distance += dist

        avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
        max_speed = max(speeds) if speeds else 0.0

        # Classify movement pattern
        if not positions_with_time or len(positions_with_time) < 2:
            movement_pattern = "stationary"
        elif total_distance < 2.0:
            movement_pattern = "stationary"
        elif avg_speed > 0.5:
            # Check for patrol pattern: does the target revisit areas?
            if len(positions_with_time) >= 6:
                # Simple heuristic: check if bounding box is much smaller
                # than total distance (indicates circling/patrol)
                xs = [p[0] for p in positions_with_time]
                ys = [p[1] for p in positions_with_time]
                bbox_diag = math.sqrt(
                    (max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2
                )
                if bbox_diag > 0 and total_distance / bbox_diag > 3.0:
                    movement_pattern = "patrol"
                else:
                    movement_pattern = "mobile"
            else:
                movement_pattern = "mobile"
        else:
            movement_pattern = "stationary"

        first_seen = dossier.get("first_seen", 0)
        last_seen = dossier.get("last_seen", 0)
        active_duration = last_seen - first_seen if last_seen > first_seen else 0

        return {
            "movement_pattern": movement_pattern,
            "average_speed": round(avg_speed, 3),
            "max_speed": round(max_speed, 3),
            "activity_hours": sorted(activity_hours_set),
            "signal_count": len(signals),
            "source_breakdown": dict(source_breakdown),
            "rssi_stats": rssi_stats,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "active_duration_s": round(active_duration, 1),
        }

    # ------------------------------------------------------------------
    # Periodic flush
    # ------------------------------------------------------------------

    def _sync_tracker_targets(self) -> None:
        """Create dossiers for any tracker targets that don't have one yet.

        This is the catch-all: regardless of which EventBus events were
        received, every target in the TargetTracker gets a persistent dossier.
        Runs periodically from the flush loop so demo-mode targets, real
        edge-device targets, and any other source all get dossiers.
        """
        if self._tracker is None:
            return

        try:
            all_targets = self._tracker.get_all()
        except Exception:
            logger.debug("Tracker sync skipped (get_all failed)", exc_info=True)
            return

        created = 0
        for target in all_targets:
            tid = target.target_id
            with self._lock:
                already_mapped = tid in self._target_dossier_map
            if already_mapped:
                continue

            # Determine entity type from target source/asset_type
            entity_type = "unknown"
            identifiers: dict[str, str] = {}
            tags: list[str] = []

            if tid.startswith("ble_"):
                entity_type = "device"
                raw = tid[4:]
                if len(raw) == 12:
                    mac = ":".join(raw[i:i + 2] for i in range(0, 12, 2)).upper()
                    identifiers["mac"] = mac
                tags.append("ble")
                if target.asset_type in ("phone", "smartphone"):
                    entity_type = "phone"
                elif target.asset_type in ("watch", "wearable"):
                    entity_type = "wearable"
            elif tid.startswith("det_"):
                if target.asset_type == "person":
                    entity_type = "person"
                elif target.asset_type == "vehicle":
                    entity_type = "vehicle"
                tags.extend(["yolo", target.classification or target.asset_type])
            elif tid.startswith("mesh_"):
                entity_type = "mesh_radio"
                identifiers["node_id"] = tid[5:]
                tags.extend(["meshtastic", "lora"])
            elif tid.startswith("wifi_"):
                entity_type = "wifi_device"
                tags.append("wifi")
            elif tid.startswith("rf_motion_"):
                entity_type = "motion_detected"
                tags.append("rf_motion")
            else:
                # Simulation targets, manual targets, etc.
                entity_type = target.asset_type or "unknown"
                tags.append(target.source)

            self.find_or_create_for_target(
                tid,
                name=target.name,
                entity_type=entity_type,
                identifiers=identifiers,
                tags=tags,
            )
            # Mark as dirty so the next flush writes position data
            with self._lock:
                dossier_id = self._target_dossier_map.get(tid)
                if dossier_id:
                    self._dirty.add(dossier_id)
            created += 1

        if created > 0:
            logger.info("Tracker sync: created %d new dossiers (%d total targets)",
                        created, len(all_targets))

    def _flush_loop(self) -> None:
        """Periodically flush dirty dossiers and sync tracker targets."""
        while self._running:
            time.sleep(self._flush_interval)
            self._sync_tracker_targets()
            self._flush_dirty()

    def _flush_dirty(self) -> None:
        """Flush dirty dossiers (sync tracker state -> store)."""
        with self._lock:
            dirty_ids = set(self._dirty)
            self._dirty.clear()

        if not dirty_ids:
            return

        # Update last_seen from tracker for any mapped targets
        if self._tracker is not None:
            for target_id, dossier_id in list(self._target_dossier_map.items()):
                if dossier_id in dirty_ids:
                    target = self._tracker.get_target(target_id)
                    if target is not None:
                        # last_seen on tracker is monotonic; convert to wall clock
                        self._store.add_signal(
                            dossier_id=dossier_id,
                            source=target.source,
                            signal_type="tracker_sync",
                            data={
                                "position_x": target.position[0],
                                "position_y": target.position[1],
                                "heading": target.heading,
                                "speed": target.speed,
                            },
                            position_x=target.position[0],
                            position_y=target.position[1],
                            confidence=target.position_confidence,
                        )

        logger.debug("Flushed %d dirty dossiers", len(dirty_ids))
