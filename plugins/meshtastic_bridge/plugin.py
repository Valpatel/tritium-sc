# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MeshtasticPlugin — LoRa mesh radio bridge for Tritium SC.

Bridges Meshtastic radio networks into the Tritium command center,
enabling long-range command and control of remote sensor nodes, robots,
and edge devices via LoRa mesh.

Supports two operational modes:
1. Direct connection — plugin connects to a local Meshtastic radio
   (serial or TCP) and polls nodes directly.
2. MQTT bridge mode — an external bridge script (scripts/meshtastic-bridge.py)
   connects to the radio and publishes node data to MQTT topics.
   The plugin subscribes to those topics and ingests the data.

In both modes, each Meshtastic node appears as a TrackedTarget on the
tactical map with real GPS coordinates.

Messages are bridged bidirectionally:
- Meshtastic -> Tritium: node positions, telemetry, text messages
- Tritium -> Meshtastic: commands, waypoints, alerts
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("meshtastic")


class MeshtasticConfig:
    """Configuration for the Meshtastic plugin."""

    def __init__(self) -> None:
        self.connection_type: str = os.environ.get(
            "MESHTASTIC_CONNECTION", "serial"
        )  # serial, tcp, mqtt
        self.serial_port: str = os.environ.get(
            "MESHTASTIC_SERIAL_PORT", "/dev/ttyUSB0"
        )
        self.tcp_host: str = os.environ.get("MESHTASTIC_TCP_HOST", "localhost")
        self.tcp_port: int = int(os.environ.get("MESHTASTIC_TCP_PORT", "4403"))
        self.mqtt_topic_prefix: str = os.environ.get(
            "MESHTASTIC_MQTT_PREFIX", "msh/US"
        )
        self.poll_interval: float = float(
            os.environ.get("MESHTASTIC_POLL_INTERVAL", "5.0")
        )
        self.enabled: bool = os.environ.get(
            "MESHTASTIC_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        self.site_id: str = os.environ.get("MQTT_SITE_ID", "home")


class MeshtasticPlugin(PluginInterface):
    """LoRa mesh radio bridge for long-range command and control.

    Connects to Meshtastic radios and bridges their mesh network
    into the Tritium command center. Each radio node appears as a
    tracked target on the tactical map with real GPS coordinates.

    Also subscribes to MQTT topics published by the external
    meshtastic-bridge.py script for real hardware integration.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._config = MeshtasticConfig()
        self._interface: Any = None  # meshtastic.SerialInterface or TcpInterface
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._nodes: dict[str, dict] = {}  # node_id -> last known state
        self._messages: list[dict] = []  # recent mesh messages
        self._max_messages = 500
        self._bridge_online = False  # whether external bridge is connected
        self._mqtt_bridge: Any = None  # reference to SC's MQTTBridge
        # Telemetry history: node_id -> list of {ts, battery, voltage, temperature, ...}
        self._telemetry_history: dict[str, list[dict]] = {}
        self._max_telemetry_points = 100  # per node

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.meshtastic"

    @property
    def name(self) -> str:
        return "Meshtastic Bridge"

    @property
    def version(self) -> str:
        return "0.2.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes", "ui"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references and register routes."""
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        self._register_routes()

        # Subscribe to MQTT meshtastic topics from external bridge
        self._subscribe_mqtt_bridge(ctx)

        # Subscribe to operator chat events for mesh forwarding
        self._subscribe_operator_chat(ctx)

        self._logger.info(
            "Meshtastic plugin configured (connection=%s, enabled=%s)",
            self._config.connection_type,
            self._config.enabled,
        )

    def _subscribe_mqtt_bridge(self, ctx: PluginContext) -> None:
        """Subscribe to MQTT topics published by meshtastic-bridge.py.

        The bridge script publishes to:
          tritium/{site}/meshtastic/{node_hex}/nodes    — node data
          tritium/{site}/meshtastic/{node_hex}/message  — text messages
          tritium/{site}/meshtastic/{node_hex}/position — position updates
          tritium/{site}/meshtastic/{bridge_id}/status  — bridge online/offline
          tritium/{site}/meshtastic/{bridge_id}/summary — aggregate stats
        """
        # Try to get the MQTTBridge from the context or app state
        mqtt_bridge = getattr(ctx, "mqtt_bridge", None)
        if mqtt_bridge is None and hasattr(ctx, "app") and ctx.app:
            mqtt_bridge = getattr(ctx.app.state, "mqtt_bridge", None)

        if mqtt_bridge is None:
            self._logger.info(
                "No MQTT bridge available — will rely on direct connection or API polling"
            )
            return

        self._mqtt_bridge = mqtt_bridge
        site = self._config.site_id
        prefix = f"tritium/{site}/meshtastic"

        # Subscribe to all meshtastic topics using wildcard
        try:
            mqtt_bridge.subscribe(
                f"{prefix}/+/nodes",
                self._on_mqtt_node_update,
            )
            mqtt_bridge.subscribe(
                f"{prefix}/+/message",
                self._on_mqtt_message,
            )
            mqtt_bridge.subscribe(
                f"{prefix}/+/position",
                self._on_mqtt_position,
            )
            mqtt_bridge.subscribe(
                f"{prefix}/+/telemetry",
                self._on_mqtt_telemetry,
            )
            mqtt_bridge.subscribe(
                f"{prefix}/+/status",
                self._on_mqtt_bridge_status,
            )
            self._logger.info("Subscribed to MQTT meshtastic topics: %s/+/#", prefix)
        except Exception as exc:
            self._logger.warning(
                "Could not subscribe to MQTT meshtastic topics: %s — "
                "MQTT bridge may not support topic subscriptions. "
                "Plugin will work via direct connection or API polling.",
                exc,
            )

    # -- MQTT callbacks from external bridge --------------------------------

    def _on_mqtt_node_update(self, topic: str, payload: bytes | str) -> None:
        """Handle node data from the external bridge."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            node_id = data.get("node_id", "")
            if not node_id:
                return
            self._ingest_bridge_node(node_id, data)
        except Exception as exc:
            self._logger.error("Error processing MQTT node update: %s", exc)

    def _on_mqtt_message(self, topic: str, payload: bytes | str) -> None:
        """Handle text message from the external bridge.

        When a mesh user sends a text message, this:
        1. Stores it in the message buffer.
        2. Emits an event for UI updates.
        3. Forwards to MQTT as an operator chat message so SC operators
           see mesh messages in their chat panel.
        4. Publishes to the operator chat topic for bidirectional comms.
        """
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self._messages.append(data)
            if len(self._messages) > self._max_messages:
                self._messages = self._messages[-self._max_messages:]

            # Emit event for UI
            if self._event_bus:
                self._event_bus.publish("meshtastic:text_received", data=data)

            # Forward mesh message to operator chat via MQTT
            self._forward_to_operator_chat(data)
        except Exception as exc:
            self._logger.error("Error processing MQTT message: %s", exc)

    def _forward_to_operator_chat(self, msg_data: dict) -> None:
        """Forward a mesh text message to the operator chat system.

        Publishes the message to the MQTT operator chat topic so that
        SC operators see mesh user messages in the chat panel, enabling
        bidirectional communication between mesh radio users and SC operators.
        """
        if self._mqtt_bridge is None:
            return

        sender = msg_data.get("from_name") or msg_data.get("sender") or msg_data.get("from", "mesh_user")
        text = msg_data.get("text") or msg_data.get("message", "")
        channel = msg_data.get("channel", 0)

        if not text:
            return

        chat_payload = {
            "source": "meshtastic",
            "sender": f"[Mesh] {sender}",
            "text": text,
            "channel": channel,
            "timestamp": msg_data.get("timestamp") or time.time(),
            "node_id": msg_data.get("from_id") or msg_data.get("node_id", ""),
        }

        try:
            site = self._config.site_id
            chat_topic = f"tritium/{site}/chat/mesh"
            self._mqtt_bridge.publish(chat_topic, json.dumps(chat_payload))
            self._logger.debug(
                "Forwarded mesh message from %s to operator chat: %s",
                sender, text[:50],
            )
        except Exception as exc:
            self._logger.debug("Could not forward mesh message to MQTT chat: %s", exc)

        # Also emit an operator chat event for WebSocket broadcast
        if self._event_bus:
            self._event_bus.publish("operator:chat_message", data=chat_payload)

    def _subscribe_operator_chat(self, ctx: PluginContext) -> None:
        """Subscribe to operator chat events for mesh forwarding.

        When an operator sends a chat message in the SC UI destined for
        the mesh network, forward it to the Meshtastic radio. This enables
        bidirectional communication: mesh users see operator messages.
        """
        if self._event_bus is None:
            return

        # Subscribe to MQTT-based operator chat destined for mesh
        mqtt_bridge = self._mqtt_bridge
        if mqtt_bridge:
            site = self._config.site_id
            try:
                mqtt_bridge.subscribe(
                    f"tritium/{site}/chat/operator_to_mesh",
                    self._on_mqtt_operator_to_mesh,
                )
                self._logger.info(
                    "Subscribed to operator-to-mesh chat topic"
                )
            except Exception as exc:
                self._logger.debug(
                    "Could not subscribe to operator-to-mesh topic: %s", exc
                )

    def _on_mqtt_operator_to_mesh(self, topic: str, payload: bytes | str) -> None:
        """Handle operator chat messages destined for the mesh network.

        Forwards the message text to the Meshtastic radio for broadcast
        to mesh users.
        """
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            text = data.get("text") or data.get("content", "")
            sender = data.get("sender") or data.get("operator_name", "SC")

            if not text:
                return

            # Prefix with sender name so mesh users know who sent it
            mesh_text = f"[{sender}] {text}"
            if len(mesh_text) > 228:
                mesh_text = mesh_text[:225] + "..."

            sent = self.send_text(mesh_text)
            self._logger.info(
                "Forwarded operator message to mesh: %s -> %s",
                sender, text[:50],
            )

            # Log in local message buffer
            msg = {
                "from_name": sender,
                "text": text,
                "channel": 0,
                "timestamp": time.time(),
                "source": "operator",
                "forwarded_to_mesh": sent,
            }
            self._messages.append(msg)
            if len(self._messages) > self._max_messages:
                self._messages = self._messages[-self._max_messages:]

        except Exception as exc:
            self._logger.error("Error forwarding operator message to mesh: %s", exc)

    def _on_mqtt_position(self, topic: str, payload: bytes | str) -> None:
        """Handle position update from the external bridge."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            node_id = data.get("node_id", "")
            if not node_id:
                return

            # Update position in cached node
            if node_id in self._nodes:
                if data.get("latitude") is not None:
                    self._nodes[node_id]["lat"] = data["latitude"]
                if data.get("longitude") is not None:
                    self._nodes[node_id]["lng"] = data["longitude"]
                if data.get("altitude") is not None:
                    self._nodes[node_id]["alt"] = data["altitude"]

                # Update tracker with new position
                self._push_node_to_tracker(node_id, self._nodes[node_id])
        except Exception as exc:
            self._logger.error("Error processing MQTT position: %s", exc)

    def _on_mqtt_telemetry(self, topic: str, payload: bytes | str) -> None:
        """Handle telemetry update from the external bridge."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            node_id = data.get("node_id", "")
            if not node_id or node_id not in self._nodes:
                return

            dm = data.get("device_metrics", {})
            env = data.get("environment_metrics", {})
            node = self._nodes[node_id]

            if dm.get("batteryLevel") is not None:
                node["battery"] = dm["batteryLevel"]
            if dm.get("voltage") is not None:
                node["voltage"] = dm["voltage"]
            if dm.get("channelUtilization") is not None:
                node["channel_utilization"] = dm["channelUtilization"]
            if dm.get("airUtilTx") is not None:
                node["air_util_tx"] = dm["airUtilTx"]
            if env.get("temperature") is not None:
                node["temperature"] = env["temperature"]
            if env.get("relativeHumidity") is not None:
                node["humidity"] = env["relativeHumidity"]
            if env.get("barometricPressure") is not None:
                node["pressure"] = env["barometricPressure"]

            # Record telemetry history for sparkline charts
            self._record_telemetry(node_id, node)

            # Publish environment data for Amy's sensorium
            if any(env.get(k) is not None for k in ("temperature", "relativeHumidity", "barometricPressure")):
                env_data = {
                    "source_id": node_id,
                    "source_name": node.get("name") or node.get("short_name") or node_id,
                    "temperature_c": env.get("temperature"),
                    "humidity_pct": env.get("relativeHumidity"),
                    "pressure_hpa": env.get("barometricPressure"),
                }
                if self._event_bus:
                    self._event_bus.publish("meshtastic:environment", data=env_data)

        except Exception as exc:
            self._logger.error("Error processing MQTT telemetry: %s", exc)

    def _on_mqtt_bridge_status(self, topic: str, payload: bytes | str) -> None:
        """Handle bridge status from the external bridge."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self._bridge_online = data.get("online", False)
            self._logger.info(
                "Meshtastic bridge %s: %s",
                data.get("bridge_id", "unknown"),
                "ONLINE" if self._bridge_online else "OFFLINE",
            )
        except Exception as exc:
            self._logger.error("Error processing MQTT bridge status: %s", exc)

    def _ingest_bridge_node(self, node_id: str, data: dict) -> None:
        """Ingest a node update from the external bridge and create TrackedTarget."""
        pos = data.get("position") or {}
        dm = data.get("device_metrics") or {}
        env = data.get("environment") or {}

        node_state = {
            "node_id": node_id,
            "long_name": data.get("long_name", ""),
            "short_name": data.get("short_name", ""),
            "name": data.get("long_name") or data.get("short_name") or node_id,
            "hw_model": data.get("hw_model", ""),
            "firmware_version": data.get("firmware_version", ""),
            "role": data.get("role"),
            "lat": pos.get("latitude"),
            "lng": pos.get("longitude"),
            "alt": pos.get("altitude"),
            "battery": dm.get("battery_level"),
            "voltage": dm.get("voltage"),
            "channel_utilization": dm.get("channel_utilization"),
            "air_util_tx": dm.get("air_util_tx"),
            "snr": data.get("snr"),
            "rssi": data.get("rssi"),
            "last_heard": data.get("last_heard"),
            "hops_away": data.get("hops_away"),
            "is_favorite": data.get("is_favorite", False),
            "via_mqtt": data.get("via_mqtt", False),
            "temperature": env.get("temperature"),
            "humidity": env.get("relative_humidity"),
            "pressure": env.get("barometric_pressure"),
            "position": {"lat": pos.get("latitude"), "lng": pos.get("longitude")},
            "hardware": data.get("hw_model", ""),
        }

        self._nodes[node_id] = node_state

        # Record telemetry history for sparkline charts
        self._record_telemetry(node_id, node_state)

        # Push to tracker
        self._push_node_to_tracker(node_id, node_state)

        # Publish event for UI
        if self._event_bus:
            self._event_bus.publish("meshtastic:node_updated", data=node_state)

    def _push_node_to_tracker(self, node_id: str, node_state: dict) -> None:
        """Push a mesh node to the TargetTracker as a TrackedTarget."""
        lat = node_state.get("lat")
        lng = node_state.get("lng")

        if not self._tracker or lat is None or lng is None:
            return
        if lat == 0.0 and lng == 0.0:
            return

        try:
            from engine.tactical.geo import latlng_to_local
            lx, ly, lz = latlng_to_local(lat, lng, node_state.get("alt", 0.0) or 0.0)
        except Exception:
            # If geo conversion fails, skip tracker update
            return

        name = node_state.get("name", node_id)
        tid = f"mesh_{node_id.replace('!', '')}"
        battery_raw = node_state.get("battery")
        battery = battery_raw / 100.0 if battery_raw is not None and battery_raw > 1 else (battery_raw or 1.0)

        self._tracker.update_from_simulation({
            "target_id": tid,
            "name": f"[Mesh] {name}",
            "alliance": "friendly",
            "asset_type": "mesh_radio",
            "position": {"x": lx, "y": ly},
            "heading": 0.0,
            "speed": 0.0,
            "battery": battery,
            "status": "active",
        })

    def start(self) -> None:
        """Connect to Meshtastic radio and start listening."""
        if self._running:
            return
        self._running = True

        if not self._config.enabled:
            self._logger.info(
                "Meshtastic direct connection disabled "
                "(set MESHTASTIC_ENABLED=true to activate). "
                "MQTT bridge ingestion is always active."
            )
            return

        # Try to connect to the radio
        if self._connect():
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name="meshtastic-poll",
            )
            self._poll_thread.start()
            self._logger.info("Meshtastic bridge started")
        else:
            self._logger.warning(
                "Meshtastic radio not available — running in disconnected mode"
            )

    def stop(self) -> None:
        """Disconnect from radio and clean up."""
        if not self._running:
            return
        self._running = False

        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3.0)

        self._disconnect()
        self._logger.info("Meshtastic plugin stopped")

    @property
    def healthy(self) -> bool:
        if not self._config.enabled:
            return True  # Disabled but healthy
        return self._running

    # -- Connection management ---------------------------------------------

    def _connect(self) -> bool:
        """Connect to the Meshtastic radio.

        Returns True if connection succeeded, False otherwise.
        """
        try:
            import meshtastic
        except ImportError:
            self._logger.warning(
                "meshtastic package not installed — "
                "install with: pip install meshtastic"
            )
            return False

        try:
            if self._config.connection_type == "serial":
                from meshtastic.serial_interface import SerialInterface
                self._interface = SerialInterface(self._config.serial_port)
            elif self._config.connection_type == "tcp":
                from meshtastic.tcp_interface import TCPInterface
                self._interface = TCPInterface(
                    hostname=self._config.tcp_host,
                    portNumber=self._config.tcp_port,
                )
            else:
                self._logger.error(
                    "Unknown connection type: %s", self._config.connection_type
                )
                return False

            self._logger.info(
                "Connected to Meshtastic radio via %s",
                self._config.connection_type,
            )
            return True

        except Exception as exc:
            self._logger.error("Failed to connect to Meshtastic radio: %s", exc)
            return False

    def _disconnect(self) -> None:
        """Disconnect from the Meshtastic radio."""
        if self._interface is not None:
            try:
                self._interface.close()
            except Exception as exc:
                self._logger.error("Error closing Meshtastic interface: %s", exc)
            self._interface = None

    # -- Polling loop ------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background loop: poll radio for node updates."""
        while self._running:
            try:
                self._poll_nodes()
            except Exception as exc:
                self._logger.error("Meshtastic poll error: %s", exc)
            time.sleep(self._config.poll_interval)

    def _poll_nodes(self) -> None:
        """Read current node list from radio and update tracker."""
        if self._interface is None:
            return

        try:
            nodes = self._interface.nodes
            if not nodes:
                return

            for node_id, node_info in nodes.items():
                self._update_node(node_id, node_info)

            # Publish summary event
            if self._event_bus:
                self._event_bus.publish("meshtastic:nodes_updated", data={
                    "count": len(nodes),
                    "nodes": list(self._nodes.keys()),
                    "timestamp": time.time(),
                })

        except Exception as exc:
            self._logger.error("Failed to poll Meshtastic nodes: %s", exc)

    def _update_node(self, node_id: str, node_info: dict) -> None:
        """Update a single Meshtastic node in the tracker (direct connection mode)."""
        user = node_info.get("user", {})
        position = node_info.get("position", {})
        device_metrics = node_info.get("deviceMetrics", {})
        env_metrics = node_info.get("environmentMetrics", {})

        name = user.get("longName") or user.get("shortName") or node_id
        lat = position.get("latitude")
        lng = position.get("longitude")
        alt = position.get("altitude", 0.0)
        battery_raw = device_metrics.get("batteryLevel")
        last_heard = node_info.get("lastHeard", 0)
        snr = node_info.get("snr")

        # Cache node state with extended data
        self._nodes[node_id] = {
            "node_id": node_id,
            "name": name,
            "long_name": user.get("longName", ""),
            "short_name": user.get("shortName", ""),
            "lat": lat,
            "lng": lng,
            "alt": alt,
            "battery": battery_raw,
            "voltage": device_metrics.get("voltage"),
            "channel_utilization": device_metrics.get("channelUtilization"),
            "air_util_tx": device_metrics.get("airUtilTx"),
            "last_heard": last_heard,
            "snr": snr,
            "rssi": node_info.get("rssi"),
            "hops_away": node_info.get("hopsAway"),
            "hw_model": user.get("hwModel", "unknown"),
            "hardware": user.get("hwModel", "unknown"),
            "firmware_version": node_info.get("firmwareVersion", ""),
            "role": user.get("role"),
            "is_favorite": node_info.get("isFavorite", False),
            "via_mqtt": node_info.get("viaMqtt", False),
            "temperature": env_metrics.get("temperature"),
            "humidity": env_metrics.get("relativeHumidity"),
            "pressure": env_metrics.get("barometricPressure"),
            "position": {"lat": lat, "lng": lng},
        }

        # Record telemetry history for sparkline charts
        self._record_telemetry(node_id, self._nodes[node_id])

        # Push to tracker
        self._push_node_to_tracker(node_id, self._nodes[node_id])

        # Publish environment data for Amy's sensorium (direct connection mode)
        env_metrics = node_info.get("environmentMetrics", {})
        if any(env_metrics.get(k) is not None for k in ("temperature", "relativeHumidity", "barometricPressure")):
            env_data = {
                "source_id": node_id,
                "source_name": name,
                "temperature_c": env_metrics.get("temperature"),
                "humidity_pct": env_metrics.get("relativeHumidity"),
                "pressure_hpa": env_metrics.get("barometricPressure"),
            }
            if self._event_bus:
                self._event_bus.publish("meshtastic:environment", data=env_data)

    # -- Send messages -----------------------------------------------------

    def send_text(self, text: str, destination: str | None = None) -> bool:
        """Send a text message via the Meshtastic mesh.

        Args:
            text: Message to send (max ~228 bytes for LoRa).
            destination: Node ID to send to, or None for broadcast.

        Returns:
            True if message was sent.
        """
        if self._interface is None:
            self._logger.warning("Cannot send — no radio connection")
            return False

        try:
            if destination:
                self._interface.sendText(text, destinationId=destination)
            else:
                self._interface.sendText(text)
            self._logger.info("Sent Meshtastic message: %s", text[:50])

            if self._event_bus:
                self._event_bus.publish("meshtastic:message_sent", data={
                    "text": text,
                    "destination": destination or "broadcast",
                    "timestamp": time.time(),
                })
            return True
        except Exception as exc:
            self._logger.error("Failed to send Meshtastic message: %s", exc)
            return False

    def send_waypoint(
        self, lat: float, lng: float, name: str = "", destination: str | None = None
    ) -> bool:
        """Send a waypoint to a Meshtastic node.

        Args:
            lat: Latitude in degrees.
            lng: Longitude in degrees.
            name: Waypoint name/label.
            destination: Node ID, or None for broadcast.

        Returns:
            True if waypoint was sent.
        """
        if self._interface is None:
            return False

        try:
            from meshtastic.protobuf import mesh_pb2
            waypoint = mesh_pb2.Waypoint()
            waypoint.latitude_i = int(lat * 1e7)
            waypoint.longitude_i = int(lng * 1e7)
            if name:
                waypoint.name = name[:30]

            self._interface.sendWaypoint(
                waypoint, destinationId=destination or "^all"
            )
            self._logger.info("Sent waypoint: %s (%.6f, %.6f)", name, lat, lng)
            return True
        except Exception as exc:
            self._logger.error("Failed to send waypoint: %s", exc)
            return False

    # -- Telemetry history -------------------------------------------------

    def _record_telemetry(self, node_id: str, node_state: dict) -> None:
        """Record a telemetry snapshot for sparkline charting.

        Called whenever node state is updated with new battery/voltage/temp data.
        Keeps up to _max_telemetry_points per node in a ring buffer.
        """
        # Only record if we have at least one interesting metric
        battery = node_state.get("battery")
        voltage = node_state.get("voltage")
        temperature = node_state.get("temperature")
        humidity = node_state.get("humidity")
        channel_util = node_state.get("channel_utilization")
        air_util = node_state.get("air_util_tx")

        if all(v is None for v in (battery, voltage, temperature, humidity, channel_util, air_util)):
            return

        point = {
            "ts": int(time.time()),
            "battery": battery,
            "voltage": voltage,
            "temperature": temperature,
            "humidity": humidity,
            "channel_utilization": channel_util,
            "air_util_tx": air_util,
        }

        if node_id not in self._telemetry_history:
            self._telemetry_history[node_id] = []

        history = self._telemetry_history[node_id]
        history.append(point)
        if len(history) > self._max_telemetry_points:
            self._telemetry_history[node_id] = history[-self._max_telemetry_points:]

    def get_telemetry_history(self, node_id: str) -> list[dict]:
        """Return telemetry history for a node (for API route)."""
        return list(self._telemetry_history.get(node_id, []))

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the Meshtastic API."""
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
