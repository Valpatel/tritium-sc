# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT bridge for remote HackRF/SDR devices.

Subscribes to MQTT topics published by remote tritium-agent instances
running HackRF hardware and auto-discovers them into the DeviceRegistry.
Ingests spectrum sweep data into per-device SignalDatabase instances.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from tritium_lib.sdk import DeviceRegistry, DeviceState

from .signal_db import SignalDatabase

log = logging.getLogger("hackrf.mqtt_bridge")


class HackRFMQTTBridge:
    """Bridges remote HackRF devices over MQTT into the local addon.

    Subscribes to:
        tritium/{site}/sdr/+/status   — device online/offline announcements
        tritium/{site}/sdr/+/spectrum — spectrum sweep data

    Auto-discovers remote devices and ingests their data into local
    SignalDatabase instances for unified spectrum analysis.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        spectrum_instances: dict,
        signal_dbs: dict[str, SignalDatabase],
        site_id: str = "home",
    ) -> None:
        self.registry = registry
        self._spectrum_instances = spectrum_instances
        self._signal_dbs = signal_dbs
        self.site_id = site_id
        self._mqtt_client: Any = None
        self._running = False
        self._status_topic = f"tritium/{site_id}/sdr/+/status"
        self._spectrum_topic = f"tritium/{site_id}/sdr/+/spectrum"

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, mqtt_client: Any) -> None:
        """Subscribe to remote SDR topics on the given MQTT client.

        Args:
            mqtt_client: A paho-mqtt-compatible client (must support
                         subscribe() and message_callback_add()).
        """
        self._mqtt_client = mqtt_client
        self._running = True

        mqtt_client.subscribe(self._status_topic)
        mqtt_client.subscribe(self._spectrum_topic)
        mqtt_client.message_callback_add(self._status_topic, self._on_message)
        mqtt_client.message_callback_add(self._spectrum_topic, self._on_message)

        log.info(
            "HackRF MQTT bridge started — listening on "
            f"{self._status_topic} and {self._spectrum_topic}"
        )

    def stop(self) -> None:
        """Unsubscribe from remote SDR topics."""
        if self._mqtt_client and self._running:
            try:
                self._mqtt_client.unsubscribe(self._status_topic)
                self._mqtt_client.unsubscribe(self._spectrum_topic)
            except Exception as e:
                log.debug(f"Unsubscribe error (non-fatal): {e}")
        self._running = False
        log.info("HackRF MQTT bridge stopped")

    # ------------------------------------------------------------------
    # Internal MQTT callback dispatcher
    # ------------------------------------------------------------------

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Dispatch incoming MQTT messages by topic suffix."""
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.debug(f"Invalid JSON on {msg.topic}: {e}")
            return

        topic = msg.topic
        parts = topic.split("/")
        # Expected: tritium/{site}/sdr/{device_id}/{type}
        if len(parts) < 5:
            return

        device_id = parts[3]
        msg_type = parts[4]

        if msg_type == "status":
            self._on_status(topic, payload, device_id)
        elif msg_type == "spectrum":
            self._on_spectrum(topic, payload, device_id)

    # ------------------------------------------------------------------
    # Status handling — auto-discovery
    # ------------------------------------------------------------------

    def _on_status(self, topic: str, payload: dict, device_id: str | None = None) -> None:
        """Handle a device status message — auto-discover or update state.

        Payload example::

            {"online": true, "firmware": "2024.02.1", "serial": "abc123"}
        """
        if device_id is None:
            parts = topic.split("/")
            device_id = parts[3] if len(parts) >= 5 else "unknown"

        online = payload.get("online", payload.get("state") == "online")

        # Auto-discover: register if new
        if device_id not in self.registry:
            try:
                self.registry.add_device(
                    device_id=device_id,
                    device_type="hackrf",
                    transport_type="mqtt",
                    metadata={
                        "serial": payload.get("serial", ""),
                        "firmware": payload.get("firmware", ""),
                        "remote": True,
                        "site_id": self.site_id,
                    },
                )
                log.info(f"Auto-discovered remote HackRF: {device_id}")
            except ValueError:
                pass  # Race condition — already registered

            # Create a SignalDatabase for this remote device
            if device_id not in self._signal_dbs:
                self._signal_dbs[device_id] = SignalDatabase()

        # Update state
        if online:
            self.registry.set_state(device_id, DeviceState.CONNECTED)
        else:
            self.registry.set_state(device_id, DeviceState.DISCONNECTED)
        self.registry.touch(device_id)

        # Update metadata if provided
        meta_fields = {
            k: v
            for k, v in payload.items()
            if k not in ("online", "state") and v
        }
        if meta_fields:
            self.registry.update_metadata(device_id, **meta_fields)

    # ------------------------------------------------------------------
    # Spectrum data ingestion
    # ------------------------------------------------------------------

    def _on_spectrum(self, topic: str, payload: dict, device_id: str | None = None) -> None:
        """Handle incoming spectrum sweep data from a remote device.

        Delegates to ingest_remote_sweep() for the actual data parsing.
        """
        if device_id is None:
            parts = topic.split("/")
            device_id = parts[3] if len(parts) >= 5 else "unknown"

        sig_db = self._signal_dbs.get(device_id)
        if sig_db is None:
            # Device not yet known — auto-register it
            self._on_status(topic, {"online": True}, device_id=device_id)
            sig_db = self._signal_dbs.get(device_id)
            if sig_db is None:
                return

        count = self.ingest_remote_sweep(sig_db, payload)
        if count > 0:
            self.registry.touch(device_id)
            log.debug(f"Ingested {count} spectrum points from {device_id}")

    def ingest_remote_sweep(self, sig_db: SignalDatabase, payload: dict) -> int:
        """Parse and ingest a remote spectrum sweep into a SignalDatabase.

        Expected payload format::

            {
                "freq_hz": [f1, f2, ...],
                "power_dbm": [p1, p2, ...],
                "timestamp": 1234567890.123
            }

        Also accepts a list-of-dicts format::

            [{"freq_hz": f, "power_dbm": p, "timestamp": t}, ...]

        Args:
            sig_db: The SignalDatabase to store measurements in.
            payload: Spectrum data as described above.

        Returns:
            Number of points ingested.
        """
        if isinstance(payload, list):
            # List-of-dicts format
            sig_db.store_batch(payload)
            return len(payload)

        freq_list = payload.get("freq_hz", [])
        power_list = payload.get("power_dbm", [])
        timestamp = payload.get("timestamp", time.time())

        if not freq_list or not power_list:
            return 0

        count = min(len(freq_list), len(power_list))
        measurements = [
            {"freq_hz": int(freq_list[i]), "power_dbm": float(power_list[i]), "timestamp": timestamp}
            for i in range(count)
        ]
        sig_db.store_batch(measurements)
        return count
