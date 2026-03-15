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
  2. On each event, find-or-create a dossier and attach signals.
  3. Periodic flush (every 30s) persists dirty dossiers to the store.

Thread-safety: all public methods are safe to call from any thread.
"""

from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
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
                    elif event_type in ("detections", "detection:camera", "detection:camera:fusion"):
                        self._handle_detection(data)
                    elif event_type == "enrichment_complete":
                        self._handle_enrichment(data)
                except Exception:
                    logger.warning("DossierManager event error", exc_info=True)
        finally:
            self._event_bus.unsubscribe(bus_queue)

    def _handle_correlation(self, data: dict) -> None:
        """Handle a correlation event: two targets were fused."""
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

    def _handle_detection(self, data: dict) -> None:
        """Handle a YOLO detection event."""
        detections = data.get("detections", [])
        if isinstance(data, list):
            detections = data

        for det in detections:
            class_name = det.get("class_name", "unknown")
            confidence = det.get("confidence", 0.0)
            if confidence < 0.4:
                continue

            # Build a target_id matching TargetTracker convention
            det_id = det.get("target_id", f"det_{class_name}")

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
    # Periodic flush
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        """Periodically flush dirty dossiers."""
        while self._running:
            time.sleep(self._flush_interval)
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
