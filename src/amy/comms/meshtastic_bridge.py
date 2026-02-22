"""MeshtasticBridge — bridges meshtastic mesh radio <-> internal EventBus + TargetTracker.

LoRa mesh radios (Heltec V3, T-Beam, etc.) connect via TCP. This bridge
subscribes to pypubsub events from the meshtastic library, injects into
EventBus and TargetTracker.

Architecture follows MQTTBridge pattern exactly:
  - Graceful import: try/except for ``meshtastic`` package
  - Thread-safe state with locks
  - Stats property matching MQTTBridge shape
  - EventBus publish for all inbound events
  - Position conversion via latlng_to_local()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_bus import EventBus
    from ..tactical.target_tracker import TargetTracker

logger = logging.getLogger("amy.meshtastic")

# LoRa max payload is 237 bytes; reserve 9 for framing overhead.
MESHTASTIC_MAX_TEXT = 228


@dataclass
class MeshtasticNode:
    """A discovered mesh radio node."""

    node_id: str
    long_name: str = ""
    short_name: str = ""
    hardware: str = ""
    position: dict | None = None  # {"lat": float, "lng": float, "alt": float}
    battery: float | None = None
    voltage: float | None = None
    snr: float | None = None
    rssi: int | None = None
    hops: int = 0
    last_heard: float = field(default_factory=time.monotonic)


class MeshtasticBridge:
    """Bridges meshtastic mesh <-> EventBus. Follows MQTTBridge pattern."""

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        host: str = "",
        port: int = 4403,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._host = host
        self._port = port
        self._interface = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()
        self._nodes: dict[str, MeshtasticNode] = {}
        self._messages: list[dict] = []  # capped at 500
        self._messages_received: int = 0
        self._messages_sent: int = 0
        self._last_error: str = ""

    # --- Properties ---

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def nodes(self) -> dict[str, MeshtasticNode]:
        with self._lock:
            return dict(self._nodes)

    @property
    def messages(self) -> list[dict]:
        with self._lock:
            return list(self._messages)

    @property
    def stats(self) -> dict:
        return {
            "connected": self._connected,
            "host": f"{self._host}:{self._port}" if self._host else "auto-discover",
            "messages_received": self._messages_received,
            "messages_sent": self._messages_sent,
            "nodes_discovered": len(self._nodes),
            "last_error": self._last_error,
        }

    # --- Lifecycle ---

    def start(self) -> None:
        """Connect via TCPInterface + subscribe to pypubsub events."""
        if self._running:
            return

        try:
            from meshtastic.tcp_interface import TCPInterface
            from pubsub import pub
        except ImportError:
            logger.warning("meshtastic package not installed — mesh bridge disabled")
            self._last_error = "meshtastic not installed"
            return

        self._running = True

        try:
            self._interface = TCPInterface(hostname=self._host, portNumber=self._port)

            # Subscribe to pypubsub events from meshtastic library
            pub.subscribe(self._on_text, "meshtastic.receive.text")
            pub.subscribe(self._on_position, "meshtastic.receive.position")
            pub.subscribe(self._on_telemetry, "meshtastic.receive.telemetry")
            pub.subscribe(self._on_connect, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect, "meshtastic.connection.lost")
            pub.subscribe(self._on_node_update, "meshtastic.node.updated")

            self._connected = True
            logger.info(f"Meshtastic bridge connected to {self._host}:{self._port}")
            self._event_bus.publish("mesh_connected", {"host": self._host})
        except Exception as e:
            logger.error(f"Meshtastic connection failed: {e}")
            self._last_error = str(e)
            self._interface = None
            self._running = False

    def stop(self) -> None:
        """Disconnect from mesh radio."""
        self._running = False

        # Unsubscribe from pypubsub events
        try:
            from pubsub import pub
            pub.unsubscribe(self._on_text, "meshtastic.receive.text")
            pub.unsubscribe(self._on_position, "meshtastic.receive.position")
            pub.unsubscribe(self._on_telemetry, "meshtastic.receive.telemetry")
            pub.unsubscribe(self._on_connect, "meshtastic.connection.established")
            pub.unsubscribe(self._on_disconnect, "meshtastic.connection.lost")
            pub.unsubscribe(self._on_node_update, "meshtastic.node.updated")
        except Exception:
            pass

        if self._interface is not None:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None

        self._connected = False
        logger.info("Meshtastic bridge stopped")

    # --- Inbound handlers (pypubsub callbacks) ---

    def _on_text(self, packet, interface=None) -> None:
        """Handle incoming text message from mesh."""
        self._messages_received += 1
        try:
            decoded = packet.get("decoded", {})
            text = decoded.get("text", "") if isinstance(decoded, dict) else ""
            from_id = packet.get("fromId", "unknown")
            to_id = packet.get("toId", "^all")
            channel = packet.get("channel", 0)

            msg = {
                "from": from_id,
                "to": to_id,
                "text": text,
                "channel": channel,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "snr": packet.get("rxSnr", None),
                "rssi": packet.get("rxRssi", None),
                "hops": packet.get("hopStart", 0) - packet.get("hopLimit", 0)
                if "hopStart" in packet
                else 0,
            }

            with self._lock:
                self._messages.append(msg)
                if len(self._messages) > 500:
                    self._messages = self._messages[-500:]

            self._event_bus.publish("mesh_text", msg)
        except Exception as e:
            logger.debug(f"Meshtastic text handler error: {e}")

    def _on_position(self, packet, interface=None) -> None:
        """Handle incoming position from mesh node."""
        self._messages_received += 1
        try:
            decoded = packet.get("decoded", {})
            position = decoded.get("position", {}) if isinstance(decoded, dict) else {}
            from_id = packet.get("fromId", "unknown")

            lat = position.get("latitude", 0.0) or position.get("latitudeI", 0) / 1e7
            lng = position.get("longitude", 0.0) or position.get("longitudeI", 0) / 1e7
            alt = position.get("altitude", 0.0)

            if lat == 0.0 and lng == 0.0:
                return

            # Convert WGS84 to local coordinates
            try:
                from amy.tactical.geo import latlng_to_local
                x, y, z = latlng_to_local(lat, lng, alt)
            except Exception:
                x, y, z = 0.0, 0.0, 0.0

            # Update node
            with self._lock:
                node = self._nodes.get(from_id)
                if node is not None:
                    node.position = {"lat": lat, "lng": lng, "alt": alt}
                    node.last_heard = time.monotonic()

            # Update target tracker with local coordinates
            self._tracker.update_from_simulation({
                "target_id": f"mesh_{from_id}",
                "name": self._get_node_name(from_id),
                "alliance": "friendly",
                "asset_type": "mesh_radio",
                "position": {"x": x, "y": y},
                "heading": 0,
                "speed": 0,
                "battery": self._get_node_battery(from_id),
                "status": "active",
            })

            self._event_bus.publish("mesh_position", {
                "node_id": from_id,
                "lat": lat,
                "lng": lng,
                "alt": alt,
                "local_x": x,
                "local_y": y,
            })
        except Exception as e:
            logger.debug(f"Meshtastic position handler error: {e}")

    def _on_telemetry(self, packet, interface=None) -> None:
        """Handle incoming telemetry from mesh node."""
        self._messages_received += 1
        try:
            decoded = packet.get("decoded", {})
            telemetry = decoded.get("telemetry", {}) if isinstance(decoded, dict) else {}
            from_id = packet.get("fromId", "unknown")

            device_metrics = telemetry.get("deviceMetrics", {})
            battery = device_metrics.get("batteryLevel", None)
            voltage = device_metrics.get("voltage", None)

            with self._lock:
                node = self._nodes.get(from_id)
                if node is not None:
                    if battery is not None:
                        node.battery = battery
                    if voltage is not None:
                        node.voltage = voltage
                    node.last_heard = time.monotonic()

            self._event_bus.publish("mesh_telemetry", {
                "node_id": from_id,
                "battery": battery,
                "voltage": voltage,
                "device_metrics": device_metrics,
            })
        except Exception as e:
            logger.debug(f"Meshtastic telemetry handler error: {e}")

    def _on_node_update(self, node, interface=None) -> None:
        """Handle node discovery/update from meshtastic library."""
        try:
            node_id = node.get("num", "")
            if not node_id:
                return

            node_id = str(node_id)
            user = node.get("user", {})
            position = node.get("position", {})
            device_metrics = node.get("deviceMetrics", {})
            snr = node.get("snr", None)

            mesh_node = MeshtasticNode(
                node_id=node_id,
                long_name=user.get("longName", ""),
                short_name=user.get("shortName", ""),
                hardware=user.get("hwModel", ""),
                snr=snr,
                last_heard=time.monotonic(),
            )

            if position:
                lat = position.get("latitude", 0.0)
                lng = position.get("longitude", 0.0)
                alt = position.get("altitude", 0.0)
                if lat != 0.0 or lng != 0.0:
                    mesh_node.position = {"lat": lat, "lng": lng, "alt": alt}

            if device_metrics:
                mesh_node.battery = device_metrics.get("batteryLevel", None)
                mesh_node.voltage = device_metrics.get("voltage", None)

            with self._lock:
                self._nodes[node_id] = mesh_node

            self._event_bus.publish("mesh_node_update", {
                "node_id": node_id,
                "long_name": mesh_node.long_name,
                "short_name": mesh_node.short_name,
                "hardware": mesh_node.hardware,
            })
        except Exception as e:
            logger.debug(f"Meshtastic node update error: {e}")

    def _on_connect(self, interface=None, topic=None) -> None:
        """Handle connection established."""
        self._connected = True
        logger.info("Meshtastic connection established")
        self._event_bus.publish("mesh_connected", {"host": self._host})

    def _on_disconnect(self, interface=None, topic=None) -> None:
        """Handle connection lost."""
        self._connected = False
        logger.warning("Meshtastic connection lost")
        self._last_error = "Connection lost"
        self._event_bus.publish("mesh_disconnected", {})

    # --- Outbound ---

    def send_text(self, text: str, channel: int = 0, destination: str | None = None) -> bool:
        """Send a text message to the mesh.

        Args:
            text: Message text (truncated to 228 chars for LoRa).
            channel: Channel index (default 0 = primary).
            destination: Node ID for DM, or None for broadcast.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._connected or self._interface is None:
            return False

        # Enforce LoRa payload limit
        text = text[:MESHTASTIC_MAX_TEXT]

        try:
            kwargs = {"text": text, "channelIndex": channel}
            if destination is not None:
                kwargs["destinationId"] = destination

            self._interface.sendText(**kwargs)
            self._messages_sent += 1

            msg = {
                "from": "local",
                "to": destination or "^all",
                "text": text,
                "channel": channel,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with self._lock:
                self._messages.append(msg)
                if len(self._messages) > 500:
                    self._messages = self._messages[-500:]

            return True
        except Exception as e:
            logger.debug(f"Meshtastic send error: {e}")
            self._last_error = str(e)
            return False

    def send_position(self, lat: float, lng: float, alt: float = 0) -> bool:
        """Send our position to the mesh.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._connected or self._interface is None:
            return False

        try:
            self._interface.sendPosition(
                latitude=lat,
                longitude=lng,
                altitude=int(alt),
            )
            self._messages_sent += 1
            return True
        except Exception as e:
            logger.debug(f"Meshtastic send position error: {e}")
            self._last_error = str(e)
            return False

    # --- Dynamic connect / disconnect ---

    def connect(self, host: str, port: int) -> bool:
        """Connect to a meshtastic radio at the given host:port.

        Disconnects any existing connection first, then creates a new
        TCPInterface and subscribes to pypubsub events.

        Returns:
            True if connected successfully, False otherwise.
        """
        # Disconnect existing connection first
        if self._connected or self._interface is not None:
            self.disconnect()

        try:
            from meshtastic.tcp_interface import TCPInterface
            from pubsub import pub
        except ImportError:
            self._last_error = "meshtastic not installed"
            return False

        self._host = host
        self._port = port

        try:
            self._interface = TCPInterface(hostname=host, portNumber=port)

            pub.subscribe(self._on_text, "meshtastic.receive.text")
            pub.subscribe(self._on_position, "meshtastic.receive.position")
            pub.subscribe(self._on_telemetry, "meshtastic.receive.telemetry")
            pub.subscribe(self._on_connect, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect, "meshtastic.connection.lost")
            pub.subscribe(self._on_node_update, "meshtastic.node.updated")

            self._connected = True
            self._running = True
            self._last_error = ""
            logger.info(f"Meshtastic bridge connected to {host}:{port}")
            self._event_bus.publish("mesh_connected", {"host": host, "port": port})
            return True
        except Exception as e:
            logger.error(f"Meshtastic connection failed: {e}")
            self._last_error = str(e)
            self._interface = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the current meshtastic radio.

        Unsubscribes from pypubsub events, closes the interface, and
        resets connection state.
        """
        was_connected = self._connected

        # Unsubscribe from pypubsub events
        try:
            from pubsub import pub
            pub.unsubscribe(self._on_text, "meshtastic.receive.text")
            pub.unsubscribe(self._on_position, "meshtastic.receive.position")
            pub.unsubscribe(self._on_telemetry, "meshtastic.receive.telemetry")
            pub.unsubscribe(self._on_connect, "meshtastic.connection.established")
            pub.unsubscribe(self._on_disconnect, "meshtastic.connection.lost")
            pub.unsubscribe(self._on_node_update, "meshtastic.node.updated")
        except Exception:
            pass

        if self._interface is not None:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None

        self._connected = False
        self._running = False

        if was_connected:
            logger.info("Meshtastic bridge disconnected")
            self._event_bus.publish("mesh_disconnected", {})

    def get_channels(self) -> list[dict]:
        """Extract channel info from the connected radio.

        Returns a list of channel dicts with index, name, and role.
        Returns empty list if not connected.
        """
        if not self._connected or self._interface is None:
            return []

        channels = []
        try:
            local_node = self._interface.localNode
            if local_node is None:
                return []
            raw_channels = getattr(local_node, "channels", None)
            if raw_channels is None:
                return []

            for i, ch in enumerate(raw_channels):
                # Channel settings are in ch.settings
                settings = getattr(ch, "settings", None)
                role = getattr(ch, "role", 0)
                name = ""
                if settings is not None:
                    name = getattr(settings, "name", "") or ""

                # role: 0=DISABLED, 1=PRIMARY, 2=SECONDARY
                role_name = {0: "DISABLED", 1: "PRIMARY", 2: "SECONDARY"}.get(role, "UNKNOWN")
                channels.append({
                    "index": i,
                    "name": name,
                    "role": role_name,
                })
        except Exception as e:
            logger.debug(f"Error reading channels: {e}")

        return channels

    def get_node(self, node_id: str) -> dict | None:
        """Return detailed info for a specific mesh node.

        Args:
            node_id: The node identifier string.

        Returns:
            Dict with full node details, or None if not found.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None

            return {
                "node_id": node.node_id,
                "long_name": node.long_name,
                "short_name": node.short_name,
                "hardware": node.hardware,
                "position": node.position,
                "battery": node.battery,
                "voltage": node.voltage,
                "snr": node.snr,
                "rssi": node.rssi,
                "hops": node.hops,
                "last_heard": node.last_heard,
            }

    # --- Discovery ---

    @staticmethod
    def discover(timeout: float = 5.0) -> list[dict]:
        """Scan for meshtastic devices via mDNS/zeroconf.

        Returns list of {"host": str, "port": int, "name": str}.
        """
        try:
            from zeroconf import ServiceBrowser, Zeroconf

            results: list[dict] = []
            zc = Zeroconf()

            class Listener:
                def add_service(self, zc_instance, service_type, name):
                    info = zc_instance.get_service_info(service_type, name)
                    if info:
                        for addr in info.parsed_scoped_addresses():
                            results.append({
                                "host": addr,
                                "port": info.port,
                                "name": info.server,
                            })

                def remove_service(self, *args):
                    pass

                def update_service(self, *args):
                    pass

            browser = ServiceBrowser(zc, "_meshtastic._tcp.local.", Listener())
            time.sleep(timeout)
            zc.close()

            return results
        except ImportError:
            logger.debug("zeroconf not installed — mDNS discovery unavailable")
            return []
        except Exception as e:
            logger.debug(f"mDNS discovery error: {e}")
            return []

    # --- Internal helpers ---

    def _get_node_name(self, node_id: str) -> str:
        """Get display name for a node, falling back to node_id."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None and node.long_name:
                return node.long_name
        return node_id

    def _get_node_battery(self, node_id: str) -> float:
        """Get battery level for a node, defaulting to 1.0."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None and node.battery is not None:
                return node.battery / 100.0  # meshtastic reports 0-100
        return 1.0
