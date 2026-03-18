# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT bridge for remote Meshtastic radios.

Subscribes to MQTT topics published by remote tritium-agent instances
running Meshtastic hardware and auto-discovers them into the DeviceRegistry.
Ingests node data into per-device NodeManager instances.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from tritium_lib.sdk import DeviceRegistry, DeviceState

from .node_manager import NodeManager

log = logging.getLogger("meshtastic.mqtt_bridge")


class MeshtasticMQTTBridge:
    """Bridges remote Meshtastic radios over MQTT into the local addon.

    Subscribes to:
        tritium/{site}/meshtastic/+/status — radio online/offline
        tritium/{site}/meshtastic/+/nodes  — node list updates

    Auto-discovers remote radios and ingests their mesh node data
    into per-device NodeManager instances for unified mesh tracking.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        node_managers: dict[str, NodeManager],
        site_id: str = "home",
        event_bus: Any = None,
        target_tracker: Any = None,
    ) -> None:
        self.registry = registry
        self._node_managers = node_managers
        self.site_id = site_id
        self._event_bus = event_bus
        self._target_tracker = target_tracker
        self._mqtt_client: Any = None
        self._running = False
        self._status_topic = f"tritium/{site_id}/meshtastic/+/status"
        self._nodes_topic = f"tritium/{site_id}/meshtastic/+/nodes"

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, mqtt_client: Any) -> None:
        """Subscribe to remote Meshtastic topics on the given MQTT client.

        Args:
            mqtt_client: A paho-mqtt-compatible client (must support
                         subscribe() and message_callback_add()).
        """
        self._mqtt_client = mqtt_client
        self._running = True

        mqtt_client.subscribe(self._status_topic)
        mqtt_client.subscribe(self._nodes_topic)
        mqtt_client.message_callback_add(self._status_topic, self._on_message)
        mqtt_client.message_callback_add(self._nodes_topic, self._on_message)

        log.info(
            "Meshtastic MQTT bridge started — listening on "
            f"{self._status_topic} and {self._nodes_topic}"
        )

    def stop(self) -> None:
        """Unsubscribe from remote Meshtastic topics."""
        if self._mqtt_client and self._running:
            try:
                self._mqtt_client.unsubscribe(self._status_topic)
                self._mqtt_client.unsubscribe(self._nodes_topic)
            except Exception as e:
                log.debug(f"Unsubscribe error (non-fatal): {e}")
        self._running = False
        log.info("Meshtastic MQTT bridge stopped")

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
        # Expected: tritium/{site}/meshtastic/{device_id}/{type}
        if len(parts) < 5:
            return

        device_id = parts[3]
        msg_type = parts[4]

        if msg_type == "status":
            self._on_status(topic, payload, device_id)
        elif msg_type == "nodes":
            self._on_nodes(topic, payload, device_id)

    # ------------------------------------------------------------------
    # Status handling — auto-discovery
    # ------------------------------------------------------------------

    def _on_status(self, topic: str, payload: dict, device_id: str | None = None) -> None:
        """Handle a radio status message — auto-discover or update state.

        Payload example::

            {"online": true, "firmware": "2.5.6", "hw_model": "TLORA_V2_1_1P6"}
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
                    device_type="meshtastic",
                    transport_type="mqtt",
                    metadata={
                        "firmware": payload.get("firmware", ""),
                        "hw_model": payload.get("hw_model", ""),
                        "remote": True,
                        "site_id": self.site_id,
                    },
                )
                log.info(f"Auto-discovered remote Meshtastic radio: {device_id}")
            except ValueError:
                pass  # Race condition — already registered

            # Create a NodeManager for this remote device
            if device_id not in self._node_managers:
                self._node_managers[device_id] = NodeManager(
                    event_bus=self._event_bus,
                    target_tracker=None,  # aggregate manager handles target updates
                )

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
    # Node data ingestion
    # ------------------------------------------------------------------

    def _on_nodes(self, topic: str, payload: dict, device_id: str | None = None) -> None:
        """Handle incoming node list data from a remote radio.

        Delegates to ingest_remote_nodes() for actual data parsing.
        """
        if device_id is None:
            parts = topic.split("/")
            device_id = parts[3] if len(parts) >= 5 else "unknown"

        nm = self._node_managers.get(device_id)
        if nm is None:
            # Device not yet known — auto-register it
            self._on_status(topic, {"online": True}, device_id=device_id)
            nm = self._node_managers.get(device_id)
            if nm is None:
                return

        count = self.ingest_remote_nodes(nm, payload, bridge_id=device_id)
        if count > 0:
            self.registry.touch(device_id)
            log.debug(f"Ingested {count} mesh nodes from {device_id}")

    def ingest_remote_nodes(
        self,
        nm: NodeManager,
        payload: dict,
        bridge_id: str = "",
    ) -> int:
        """Parse and ingest remote mesh node data into a NodeManager.

        Expected payload format (same as meshtastic library interface.nodes)::

            {
                "!abcd1234": {
                    "user": {"longName": "Node A", "shortName": "NA", ...},
                    "position": {"latitude": 30.0, "longitude": -97.0, ...},
                    "lastHeard": 1234567890,
                    "snr": 5.0,
                    ...
                },
                ...
            }

        Also accepts a flat list format::

            [{"node_id": "!abcd1234", "long_name": "Node A", "lat": 30.0, ...}, ...]

        Each node gets a ``bridge_id`` field set to the remote device_id
        so the aggregate NodeManager knows which radio reported it.

        Args:
            nm: The NodeManager to ingest nodes into.
            payload: Node data in one of the formats described above.
            bridge_id: The remote device_id to stamp on each node.

        Returns:
            Number of nodes ingested.
        """
        if isinstance(payload, list):
            # Flat list format — convert to dict-of-dicts for update_nodes
            raw_nodes: dict[str, dict] = {}
            for node in payload:
                node_id = node.get("node_id", "")
                if not node_id:
                    continue
                # Mark with bridge_id
                node["bridge_id"] = bridge_id
                # Wrap in the format update_nodes expects if needed
                if "user" not in node:
                    # Already flat format — store directly in nm.nodes
                    nm.nodes[node_id] = node
                else:
                    raw_nodes[node_id] = node
            if raw_nodes:
                nm.update_nodes(raw_nodes)
            # Stamp bridge_id on all nodes from this source
            for nid in nm.nodes:
                if nm.nodes[nid].get("bridge_id", "") == bridge_id or nm.nodes[nid].get("bridge_id") is None:
                    nm.nodes[nid]["bridge_id"] = bridge_id
            return len(payload)

        # Dict-of-dicts format (standard meshtastic interface.nodes)
        if not isinstance(payload, dict):
            return 0

        nm.update_nodes(payload)

        # Stamp bridge_id on ingested nodes
        for node_id in payload:
            if node_id in nm.nodes:
                nm.nodes[node_id]["bridge_id"] = bridge_id

        return len(payload)
