# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Message bridge — bidirectional messaging between Meshtastic mesh and Tritium.

Handles:
- Receiving mesh text messages, position reports, telemetry
- Sending messages from Tritium to the mesh (broadcast, direct, channel)
- Position report bridging (mesh node GPS -> target tracker)
- Telemetry bridging (battery, voltage, channel/air utilization)
- In-memory message history (last 100 messages)

UX Loop 2 (Add Sensor) — mesh nodes report sightings and messages into Tritium.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

log = logging.getLogger("meshtastic.bridge")

# Meshtastic position integers use 1e-7 degree units
_POS_SCALE = 1e-7

# Maximum messages retained in memory
MAX_MESSAGE_HISTORY = 100


class MessageType(str, Enum):
    """Types of messages flowing through the bridge."""
    TEXT = "text"
    POSITION = "position"
    TELEMETRY = "telemetry"
    NODEINFO = "nodeinfo"
    ROUTING = "routing"
    ADMIN = "admin"


@dataclass
class MeshMessage:
    """A single message from or to the mesh network."""
    sender_id: str
    sender_name: str
    text: str
    timestamp: float
    channel: int = 0
    type: str = "text"
    destination: str = ""
    # Position data (if position report)
    lat: float | None = None
    lng: float | None = None
    altitude: float | None = None
    speed: float | None = None
    heading: float | None = None
    # Telemetry data (if telemetry report)
    battery: int | None = None
    voltage: float | None = None
    channel_util: float | None = None
    air_util: float | None = None
    uptime: int | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        d = {
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "channel": self.channel,
            "type": self.type,
            "destination": self.destination,
        }
        if self.lat is not None:
            d["lat"] = self.lat
            d["lng"] = self.lng
        if self.altitude is not None:
            d["altitude"] = self.altitude
        if self.speed is not None:
            d["speed"] = self.speed
        if self.heading is not None:
            d["heading"] = self.heading
        if self.battery is not None:
            d["battery"] = self.battery
        if self.voltage is not None:
            d["voltage"] = self.voltage
        if self.channel_util is not None:
            d["channel_util"] = self.channel_util
        if self.air_util is not None:
            d["air_util"] = self.air_util
        if self.uptime is not None:
            d["uptime"] = self.uptime
        return d


class MessageBridge:
    """Bidirectional message bridge between Meshtastic mesh and Tritium internals.

    Subscribes to meshtastic library callbacks for incoming messages.
    Provides send methods for outbound messages.
    Publishes events to Tritium event bus and optionally MQTT.
    """

    def __init__(
        self,
        connection=None,
        node_manager=None,
        event_bus=None,
        mqtt_bridge=None,
        site_id: str = "home",
        data_store=None,
    ):
        self.connection = connection
        self.node_manager = node_manager
        self.event_bus = event_bus
        self.mqtt_bridge = mqtt_bridge
        self.site_id = site_id
        self.data_store = data_store

        # Message history — newest at the end
        self._messages: deque[MeshMessage] = deque(maxlen=MAX_MESSAGE_HISTORY)
        self._registered = False

        # Stats
        self.messages_received: int = 0
        self.messages_sent: int = 0
        self.position_reports: int = 0
        self.telemetry_reports: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register_callbacks(self):
        """Register meshtastic library receive callback on the connection interface."""
        if not self.connection or not self.connection.interface:
            log.debug("No meshtastic interface available — bridge in passive mode")
            return

        iface = self.connection.interface

        # The meshtastic Python library uses pub.subscribe for callbacks
        try:
            from pubsub import pub
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            self._registered = True
            log.info("Message bridge callbacks registered")
        except ImportError:
            # Fallback: direct callback attribute
            log.debug("pubsub not available, using direct callback")
            if hasattr(iface, "onReceive"):
                iface.onReceive = self._on_receive_legacy
                self._registered = True
                log.info("Message bridge legacy callback registered")

    def unregister_callbacks(self):
        """Remove meshtastic library callbacks."""
        if not self._registered:
            return
        try:
            from pubsub import pub
            pub.unsubscribe(self._on_receive, "meshtastic.receive")
            pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
        except (ImportError, Exception):
            pass
        self._registered = False
        log.info("Message bridge callbacks unregistered")

    # ------------------------------------------------------------------
    # Incoming message handling
    # ------------------------------------------------------------------

    def _on_receive(self, packet, interface=None):
        """Callback for meshtastic pubsub — dispatches by port number."""
        if not packet:
            return

        decoded = packet.get("decoded", {})
        portnum = decoded.get("portnum", "")

        if portnum == "TEXT_MESSAGE_APP":
            self._handle_text_message(packet)
        elif portnum == "POSITION_APP":
            self._handle_position(packet)
        elif portnum in ("TELEMETRY_APP", "DEVICE_TELEMETRY_APP"):
            self._handle_telemetry(packet)
        elif portnum == "NODEINFO_APP":
            self._handle_nodeinfo(packet)
        else:
            log.debug(f"Unhandled portnum: {portnum}")

    def _on_receive_legacy(self, packet):
        """Legacy callback for older meshtastic library versions."""
        self._on_receive(packet)

    def _on_connection(self, interface=None, topic=None):
        """Called when meshtastic connection is established."""
        log.info("Meshtastic connection established — bridge active")

    def _handle_text_message(self, packet: dict):
        """Process an incoming text message from the mesh."""
        decoded = packet.get("decoded", {})
        from_id = packet.get("fromId", packet.get("from", "unknown"))
        to_id = packet.get("toId", packet.get("to", ""))
        text = decoded.get("text", decoded.get("payload", b"").decode("utf-8", errors="replace") if isinstance(decoded.get("payload"), bytes) else str(decoded.get("payload", "")))

        sender_name = self._resolve_node_name(from_id)
        channel = packet.get("channel", 0)

        msg = MeshMessage(
            sender_id=str(from_id),
            sender_name=sender_name,
            text=text,
            timestamp=time.time(),
            channel=channel,
            type=MessageType.TEXT,
            destination=str(to_id) if to_id else "",
        )

        self._messages.append(msg)
        self.messages_received += 1
        self._persist_message(msg)

        log.info(f"Mesh message from {sender_name} ({from_id}): {text[:80]}")

        # Emit to Tritium event bus
        if self.event_bus:
            self.event_bus.publish("meshtastic:message_received", msg.to_dict())

        # Publish to MQTT
        self._publish_mqtt(
            f"tritium/{self.site_id}/meshtastic/{from_id}/messages",
            msg.to_dict(),
        )

    def _handle_position(self, packet: dict):
        """Process a position report — update target tracker and store."""
        decoded = packet.get("decoded", {})
        position = decoded.get("position", {})
        from_id = packet.get("fromId", packet.get("from", "unknown"))

        lat_i = position.get("latitudeI", position.get("latitude"))
        lng_i = position.get("longitudeI", position.get("longitude"))

        if lat_i is None or lng_i is None:
            return

        # Convert meshtastic integer positions to float degrees
        # latitudeI and longitudeI are in 1e-7 degree units
        if isinstance(lat_i, int) and abs(lat_i) > 1000:
            lat = lat_i * _POS_SCALE
            lng = lng_i * _POS_SCALE
        else:
            # Already float degrees
            lat = float(lat_i)
            lng = float(lng_i)

        altitude = position.get("altitude")
        speed = position.get("groundSpeed", position.get("speed"))
        heading = position.get("groundTrack", position.get("heading"))
        # groundTrack is in 1e-5 degree units
        if heading is not None and isinstance(heading, int) and abs(heading) > 360:
            heading = heading / 1e5

        sender_name = self._resolve_node_name(from_id)

        msg = MeshMessage(
            sender_id=str(from_id),
            sender_name=sender_name,
            text=f"Position: {lat:.6f}, {lng:.6f}",
            timestamp=time.time(),
            type=MessageType.POSITION,
            lat=lat,
            lng=lng,
            altitude=altitude,
            speed=speed,
            heading=heading,
        )

        self._messages.append(msg)
        self.position_reports += 1
        self._persist_message(msg)

        # Update node manager with position
        if self.node_manager:
            node_id = str(from_id)
            node = self.node_manager.nodes.get(node_id, {})
            node["lat"] = lat
            node["lng"] = lng
            if altitude is not None:
                node["altitude"] = altitude
            node["last_heard"] = time.time()
            self.node_manager.nodes[node_id] = node

            # Push to target tracker via node manager
            if self.node_manager.target_tracker:
                target = {
                    "target_id": f"mesh_{node_id.replace('!', '')}",
                    "name": sender_name,
                    "source": "mesh",
                    "asset_type": "mesh_radio",
                    "alliance": "friendly",
                    "lat": lat,
                    "lng": lng,
                    "alt": altitude or 0,
                    "position": {"x": lng, "y": lat},
                    "last_seen": time.time(),
                }
                if speed is not None:
                    target["speed"] = speed
                if heading is not None:
                    target["heading"] = heading
                try:
                    self.node_manager.target_tracker.update_target(target)
                except Exception as e:
                    log.debug(f"Target tracker update failed: {e}")

        # Emit event
        if self.event_bus:
            self.event_bus.publish("meshtastic:position_received", msg.to_dict())

        # Publish to MQTT
        self._publish_mqtt(
            f"tritium/{self.site_id}/meshtastic/{from_id}/position",
            msg.to_dict(),
        )

    def _handle_telemetry(self, packet: dict):
        """Process telemetry data — battery, voltage, channel utilization."""
        decoded = packet.get("decoded", {})
        telemetry = decoded.get("telemetry", decoded)
        device_metrics = telemetry.get("deviceMetrics", telemetry)
        from_id = packet.get("fromId", packet.get("from", "unknown"))

        battery = device_metrics.get("batteryLevel")
        voltage = device_metrics.get("voltage")
        channel_util = device_metrics.get("channelUtilization")
        air_util = device_metrics.get("airUtilTx")
        uptime = device_metrics.get("uptimeSeconds")

        sender_name = self._resolve_node_name(from_id)

        parts = []
        if battery is not None:
            parts.append(f"bat:{battery}%")
        if voltage is not None:
            parts.append(f"v:{voltage:.1f}V")
        if channel_util is not None:
            parts.append(f"ch:{channel_util:.1f}%")

        msg = MeshMessage(
            sender_id=str(from_id),
            sender_name=sender_name,
            text=f"Telemetry: {', '.join(parts)}" if parts else "Telemetry",
            timestamp=time.time(),
            type=MessageType.TELEMETRY,
            battery=battery,
            voltage=voltage,
            channel_util=channel_util,
            air_util=air_util,
            uptime=uptime,
        )

        self._messages.append(msg)
        self.telemetry_reports += 1
        self._persist_message(msg)

        # Update node manager with telemetry
        if self.node_manager:
            node_id = str(from_id)
            node = self.node_manager.nodes.get(node_id, {})
            if battery is not None:
                node["battery"] = battery
            if voltage is not None:
                node["voltage"] = voltage
            if channel_util is not None:
                node["channel_util"] = channel_util
            if air_util is not None:
                node["air_util"] = air_util
            if uptime is not None:
                node["uptime"] = uptime
            node["last_heard"] = time.time()
            self.node_manager.nodes[node_id] = node

        # Emit event
        if self.event_bus:
            self.event_bus.publish("meshtastic:telemetry_received", msg.to_dict())

        # Publish to MQTT
        self._publish_mqtt(
            f"tritium/{self.site_id}/meshtastic/{from_id}/telemetry",
            msg.to_dict(),
        )

    def _handle_nodeinfo(self, packet: dict):
        """Process node info update."""
        decoded = packet.get("decoded", {})
        from_id = packet.get("fromId", packet.get("from", "unknown"))
        user = decoded.get("user", {})

        if self.node_manager and user:
            node_id = str(from_id)
            node = self.node_manager.nodes.get(node_id, {})
            if user.get("longName"):
                node["long_name"] = user["longName"]
            if user.get("shortName"):
                node["short_name"] = user["shortName"]
            if user.get("hwModel"):
                node["hw_model"] = user["hwModel"]
            node["last_heard"] = time.time()
            self.node_manager.nodes[node_id] = node

        log.debug(f"Node info from {from_id}: {user.get('longName', '?')}")

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def send_text(
        self,
        text: str,
        destination: str | None = None,
        channel: int = 0,
    ) -> bool:
        """Send a text message to the mesh.

        Args:
            text: Message text to send.
            destination: Node ID for direct message, or None for broadcast.
            channel: Channel index (0 = primary, 1+ = secondary).

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.connection:
            log.warning("Cannot send — no connection manager")
            return False

        ok = await self.connection.send_text(text, destination=destination)
        if ok:
            self.messages_sent += 1

            # Record in history as outbound
            msg = MeshMessage(
                sender_id="local",
                sender_name="Tritium",
                text=text,
                timestamp=time.time(),
                channel=channel,
                type=MessageType.TEXT,
                destination=str(destination) if destination else "broadcast",
            )
            self._messages.append(msg)

            if self.event_bus:
                self.event_bus.publish("meshtastic:message_sent", msg.to_dict())

            log.info(f"Sent to mesh: {text[:80]} -> {destination or 'broadcast'}")

        return ok

    async def send_data(
        self,
        data: bytes,
        destination: str | None = None,
        portnum: int = 1,
    ) -> bool:
        """Send raw data to the mesh (for advanced protocols).

        Args:
            data: Raw bytes to send.
            destination: Node ID for direct send, or None for broadcast.
            portnum: Meshtastic port number.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.connection or not self.connection.interface:
            return False

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            kwargs = {"data": data, "portNum": portnum}
            if destination:
                kwargs["destinationId"] = destination
            await loop.run_in_executor(
                None,
                lambda: self.connection.interface.sendData(**kwargs),
            )
            self.messages_sent += 1
            return True
        except Exception as e:
            log.warning(f"Send data failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Message history
    # ------------------------------------------------------------------

    def get_messages(
        self,
        limit: int = 100,
        msg_type: str | None = None,
        since: float | None = None,
    ) -> list[dict]:
        """Return message history as a list of dicts.

        Args:
            limit: Max messages to return.
            msg_type: Filter by message type ('text', 'position', 'telemetry').
            since: Only return messages after this Unix timestamp.

        Returns:
            List of message dicts, newest last.
        """
        msgs = list(self._messages)

        if msg_type:
            msgs = [m for m in msgs if m.type == msg_type]

        if since is not None:
            msgs = [m for m in msgs if m.timestamp >= since]

        return [m.to_dict() for m in msgs[-limit:]]

    def get_stats(self) -> dict:
        """Return bridge statistics."""
        return {
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "position_reports": self.position_reports,
            "telemetry_reports": self.telemetry_reports,
            "history_size": len(self._messages),
            "registered": self._registered,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_node_name(self, node_id) -> str:
        """Look up a human-readable name for a node ID."""
        node_id_str = str(node_id)
        if self.node_manager:
            node = self.node_manager.nodes.get(node_id_str, {})
            name = node.get("long_name") or node.get("short_name")
            if name:
                return name
        return node_id_str

    def _persist_message(self, msg: MeshMessage):
        """Persist a message to the data store (fire-and-forget async)."""
        if not self.data_store:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.data_store.store_message(msg.to_dict()))
            else:
                loop.run_until_complete(self.data_store.store_message(msg.to_dict()))
        except Exception as e:
            log.debug(f"Message persist failed: {e}")

    def _publish_mqtt(self, topic: str, payload: dict):
        """Publish a message to MQTT if the bridge is available."""
        if not self.mqtt_bridge:
            return
        try:
            import json
            self.mqtt_bridge.publish(topic, json.dumps(payload))
        except Exception as e:
            log.debug(f"MQTT publish failed: {e}")
