# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Dossier environment enrichment — auto-enrich BLE target dossiers with
Meshtastic environmental sensor data.

When a Meshtastic node reports environment metrics (temperature, humidity,
barometric pressure), this service finds all BLE targets recently seen by
nearby edge nodes and adds environment context to their dossiers.

Example enrichment note: "Detected in area reporting 72F, 45% humidity,
  pressure 1013 hPa (sensor: Node-Alpha, 2026-03-14 10:30:00)"

Architecture:
  - Subscribes to EventBus for ``meshtastic:environment`` events
  - Looks up active BLE devices from the TargetTracker
  - Adds enrichment signals to each nearby target's dossier via DossierStore
"""

from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("dossier-env-enrichment")


class DossierEnvEnrichment:
    """Auto-enriches BLE target dossiers with Meshtastic environment data.

    Listens for ``meshtastic:environment`` events on the EventBus and
    enriches all active BLE targets in the TargetTracker with environment
    context from the nearest Meshtastic sensor node.

    Parameters
    ----------
    event_bus:
        EventBus instance for subscribing to meshtastic events.
    target_tracker:
        TargetTracker for looking up active BLE targets.
    dossier_store:
        DossierStore for persisting enrichments (optional, gracefully degrades).
    max_target_age_s:
        Maximum age in seconds for a BLE target to be considered "nearby"
        and eligible for environment enrichment.
    cooldown_s:
        Minimum seconds between enrichments for the same target (prevents spam).
    """

    def __init__(
        self,
        event_bus: Any,
        target_tracker: Any,
        dossier_store: Any = None,
        max_target_age_s: float = 120.0,
        cooldown_s: float = 300.0,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._dossier_store = dossier_store
        self._max_target_age = max_target_age_s
        self._cooldown = cooldown_s

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[queue_mod.Queue] = None

        # Track last enrichment time per target_id to enforce cooldown
        self._last_enrichment: dict[str, float] = {}

        # Latest environment snapshot per source_id (mesh node)
        self._env_cache: dict[str, dict] = {}

    def start(self) -> None:
        """Start listening for meshtastic environment events."""
        if self._running or self._event_bus is None:
            return
        self._running = True
        self._queue = self._event_bus.subscribe()
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="dossier-env-enrichment",
        )
        self._thread.start()
        logger.info("Dossier environment enrichment started")

    def stop(self) -> None:
        """Stop the listener."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._event_bus and self._queue:
            self._event_bus.unsubscribe(self._queue)
        logger.info("Dossier environment enrichment stopped")

    def get_latest_environment(self, source_id: str = "") -> dict | None:
        """Return the latest cached environment reading.

        If source_id is empty, returns the most recent reading from any source.
        """
        if source_id:
            return self._env_cache.get(source_id)
        if not self._env_cache:
            return None
        # Return the most recent by timestamp
        return max(self._env_cache.values(), key=lambda e: e.get("timestamp", 0))

    def get_all_environments(self) -> dict[str, dict]:
        """Return all cached environment readings keyed by source_id."""
        return dict(self._env_cache)

    # -- Internal ----------------------------------------------------------

    def _listen_loop(self) -> None:
        """Background loop: drain EventBus for meshtastic:environment events."""
        while self._running:
            try:
                event = self._queue.get(timeout=1.0)
            except queue_mod.Empty:
                continue
            except Exception:
                continue

            event_type = event.get("type", event.get("event_type", ""))
            if event_type == "meshtastic:environment":
                data = event.get("data", {})
                self._on_environment(data)

    def _on_environment(self, data: dict) -> None:
        """Process a meshtastic:environment event.

        Expected data format (from MeshtasticPlugin):
            {
                "source_id": "!abcd1234",
                "source_name": "Node-Alpha",
                "temperature_c": 22.5,
                "humidity_pct": 45.0,
                "pressure_hpa": 1013.25,
            }
        """
        source_id = data.get("source_id", "")
        if not source_id:
            return

        # Cache the environment reading
        env_snapshot = {
            "source_id": source_id,
            "source_name": data.get("source_name", source_id),
            "temperature_c": data.get("temperature_c"),
            "humidity_pct": data.get("humidity_pct"),
            "pressure_hpa": data.get("pressure_hpa"),
            "timestamp": time.time(),
        }
        self._env_cache[source_id] = env_snapshot

        # Build a human-readable environment description
        parts = []
        temp_c = data.get("temperature_c")
        if temp_c is not None:
            temp_f = temp_c * 9 / 5 + 32
            parts.append(f"{temp_f:.0f}F ({temp_c:.1f}C)")

        humidity = data.get("humidity_pct")
        if humidity is not None:
            parts.append(f"{humidity:.0f}% humidity")

        pressure = data.get("pressure_hpa")
        if pressure is not None:
            parts.append(f"{pressure:.0f} hPa")

        if not parts:
            return

        env_desc = ", ".join(parts)
        source_name = data.get("source_name", source_id)
        ts_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Find all active BLE targets and enrich their dossiers
        self._enrich_active_targets(env_desc, source_name, ts_str, env_snapshot)

    def _enrich_active_targets(
        self,
        env_desc: str,
        source_name: str,
        ts_str: str,
        env_snapshot: dict,
    ) -> None:
        """Enrich all active BLE targets with environment context."""
        if self._tracker is None:
            return

        now = time.time()

        # Get all active targets from the tracker
        try:
            targets = self._tracker.get_all_targets()
        except Exception:
            try:
                targets = self._tracker.targets
                if isinstance(targets, dict):
                    targets = list(targets.values())
            except Exception:
                return

        enriched_count = 0
        for target in targets:
            # Only enrich BLE-sourced targets
            target_id = ""
            if isinstance(target, dict):
                target_id = target.get("target_id", "")
                source = target.get("source", target.get("asset_type", ""))
                last_seen = target.get("last_seen", target.get("last_update", 0))
            else:
                target_id = getattr(target, "target_id", "")
                source = getattr(target, "source", getattr(target, "asset_type", ""))
                last_seen = getattr(target, "last_seen", getattr(target, "last_update", 0))

            if not target_id:
                continue

            # Only enrich BLE targets
            is_ble = (
                target_id.startswith("ble_")
                or source in ("ble", "ble_device", "ble_scanner")
            )
            if not is_ble:
                continue

            # Check target freshness
            if isinstance(last_seen, (int, float)) and last_seen > 0:
                if now - last_seen > self._max_target_age:
                    continue

            # Check cooldown
            last_enrich = self._last_enrichment.get(target_id, 0)
            if now - last_enrich < self._cooldown:
                continue

            # Enrich the dossier
            enrichment_note = (
                f"Detected in area reporting {env_desc} "
                f"(sensor: {source_name}, {ts_str})"
            )

            if self._dossier_store is not None:
                try:
                    # Try to find the dossier by MAC identifier
                    mac = target_id.replace("ble_", "").upper()
                    # Format MAC with colons if needed
                    if len(mac) == 12 and ":" not in mac:
                        mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))

                    dossier = self._dossier_store.find_by_identifier("mac", mac)
                    if dossier:
                        self._dossier_store.add_enrichment(
                            dossier_id=dossier["dossier_id"],
                            provider="meshtastic_environment",
                            enrichment_type="environment_context",
                            data={
                                **env_snapshot,
                                "note": enrichment_note,
                            },
                        )
                        enriched_count += 1
                except Exception as exc:
                    logger.debug("Failed to enrich dossier for %s: %s", target_id, exc)

            # Update the target in the tracker with environment context
            try:
                if hasattr(self._tracker, "annotate_target"):
                    self._tracker.annotate_target(target_id, {
                        "environment": env_snapshot,
                        "environment_note": enrichment_note,
                    })
            except Exception:
                pass

            self._last_enrichment[target_id] = now

            # Emit enrichment event
            if self._event_bus is not None:
                try:
                    self._event_bus.publish("dossier:env_enriched", data={
                        "target_id": target_id,
                        "environment": env_snapshot,
                        "note": enrichment_note,
                    })
                except Exception:
                    pass

        if enriched_count > 0:
            logger.info(
                "Enriched %d BLE targets with environment data from %s",
                enriched_count, source_name,
            )

    def _prune_cooldowns(self) -> None:
        """Remove stale entries from the cooldown cache."""
        now = time.time()
        cutoff = now - self._cooldown * 2
        stale = [k for k, v in self._last_enrichment.items() if v < cutoff]
        for k in stale:
            del self._last_enrichment[k]
