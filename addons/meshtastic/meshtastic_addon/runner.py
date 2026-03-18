# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.

"""Meshtastic runner — standalone mode for remote Pi, publishes node/message/position to MQTT."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from tritium_lib.sdk import BaseRunner

logger = logging.getLogger(__name__)

# Meshtastic device USB VID:PID pairs
MESHTASTIC_VIDS: dict[int, str] = {
    0x303A: "Espressif",
    0x10C4: "SiLabs CP210x",
    0x1A86: "CH340",
    0x0403: "FTDI",
}

# Try importing optional dependencies — may not be installed
try:
    from serial.tools import list_ports

    HAS_SERIAL = True
except ImportError:
    list_ports = None  # type: ignore[assignment]
    HAS_SERIAL = False

try:
    import meshtastic  # noqa: F401
    import meshtastic.serial_interface

    HAS_MESHTASTIC = True
except ImportError:
    HAS_MESHTASTIC = False


class MeshtasticRunner(BaseRunner):
    """Agent that connects to a Meshtastic radio via serial and publishes
    node, message, and position data over MQTT.

    MQTT topics published:
        tritium/{site_id}/meshtastic/{device_id}/nodes    — full node list
        tritium/{site_id}/meshtastic/{device_id}/message   — received messages
        tritium/{site_id}/meshtastic/{device_id}/position  — position updates
        tritium/{site_id}/meshtastic/{device_id}/status    — connection status
    """

    def __init__(
        self,
        agent_id: str = "mesh0",
        site_id: str = "default",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        poll_interval: float = 30.0,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            device_type="meshtastic",
            site_id=site_id,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        )
        self._interface: Any | None = None
        self._connected = False
        self._poll_interval = poll_interval
        self._poll_thread: threading.Thread | None = None
        self._active_devices: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Scan serial ports for Meshtastic VID:PIDs."""
        if not HAS_SERIAL or list_ports is None:
            logger.warning("pyserial not installed — cannot discover serial ports")
            return []

        found: list[dict[str, Any]] = []
        for port in list_ports.comports():
            if port.vid is not None and port.vid in MESHTASTIC_VIDS:
                found.append(
                    {
                        "id": port.device.replace("/dev/", "").replace("/", "_"),
                        "port": port.device,
                        "vid": port.vid,
                        "pid": port.pid,
                        "manufacturer": MESHTASTIC_VIDS.get(port.vid, "Unknown"),
                        "description": port.description or "",
                        "serial_number": port.serial_number or "",
                    }
                )
        logger.info("Discovered %d Meshtastic device(s)", len(found))
        return found

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    async def start_device(self, device_info: dict[str, Any]) -> bool:
        """Connect to a Meshtastic device on the given serial port."""
        if not HAS_MESHTASTIC:
            logger.error("meshtastic package not installed — pip install meshtastic")
            return False

        port = device_info.get("port", "/dev/ttyACM0")
        device_id = device_info.get(
            "id", port.replace("/dev/", "").replace("/", "_")
        )

        logger.info("Connecting to Meshtastic on %s ...", port)

        try:
            iface = meshtastic.serial_interface.SerialInterface(port)
        except Exception:
            logger.exception("Failed to connect to %s", port)
            return False

        self._interface = iface
        self._connected = True
        self._active_devices[device_id] = {
            "port": port,
            "interface": iface,
            "started_at": time.time(),
        }

        # Register callbacks via pub.subscribe (meshtastic uses pypubsub)
        try:
            from pubsub import pub

            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_node_update, "meshtastic.node.updated")
        except ImportError:
            logger.warning("pubsub not available — callbacks won't fire")

        # Publish initial status
        self._publish_data("status", {"status": "connected"}, device_id)

        # Start background polling for node list
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            args=(device_id,),
            daemon=True,
        )
        self._poll_thread.start()

        logger.info("Meshtastic device %s started", device_id)
        return True

    async def stop_device(self, device_id: str) -> bool:
        """Disconnect from a Meshtastic device."""
        dev = self._active_devices.pop(device_id, None)
        if dev is None:
            logger.warning("Device %s not found", device_id)
            return False

        self._connected = False
        iface = dev.get("interface")
        if iface is not None:
            try:
                # Unsubscribe callbacks
                try:
                    from pubsub import pub

                    pub.unsubscribe(self._on_receive, "meshtastic.receive")
                    pub.unsubscribe(self._on_node_update, "meshtastic.node.updated")
                except Exception:
                    pass

                # Close with a small delay to drain serial buffer
                time.sleep(0.2)
                iface.close()
            except Exception:
                logger.exception("Error closing meshtastic interface")

        self._interface = None
        self._publish_data("status", {"status": "disconnected"}, device_id)
        logger.info("Meshtastic device %s stopped", device_id)
        return True

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def on_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle commands from SC."""
        if command == "send_text":
            return self._cmd_send_text(payload)
        elif command == "send_position":
            return self._cmd_send_position(payload)
        elif command == "get_nodes":
            return {"nodes": self._build_node_list()}
        elif command == "status":
            return {
                "connected": self._connected,
                "devices": list(self._active_devices.keys()),
                "has_meshtastic": HAS_MESHTASTIC,
            }
        else:
            logger.warning("Unknown command: %s", command)
            return {"error": f"unknown command: {command}"}

    def _cmd_send_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a text message to the mesh."""
        if self._interface is None:
            return {"error": "not connected"}
        text = payload.get("text", "")
        dest = payload.get("destination", "^all")
        try:
            self._interface.sendText(text, destinationId=dest)
            return {"sent": True, "text": text, "destination": dest}
        except Exception as exc:
            logger.exception("Failed to send text")
            return {"error": str(exc)}

    def _cmd_send_position(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a position update to the mesh."""
        if self._interface is None:
            return {"error": "not connected"}
        lat = payload.get("latitude", 0.0)
        lng = payload.get("longitude", 0.0)
        alt = payload.get("altitude", 0)
        try:
            self._interface.sendPosition(
                latitude=lat,
                longitude=lng,
                altitude=alt,
            )
            return {"sent": True, "lat": lat, "lng": lng, "alt": alt}
        except Exception as exc:
            logger.exception("Failed to send position")
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Meshtastic callbacks
    # ------------------------------------------------------------------

    def _on_receive(self, packet: dict[str, Any], interface: Any = None) -> None:
        """Handle a received meshtastic packet."""
        try:
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum", "UNKNOWN")

            msg_data: dict[str, Any] = {
                "from": packet.get("fromId", ""),
                "to": packet.get("toId", ""),
                "portnum": portnum,
                "rx_time": packet.get("rxTime", 0),
                "rx_snr": packet.get("rxSnr", 0.0),
                "hop_limit": packet.get("hopLimit", 0),
                "timestamp": time.time(),
            }

            # Extract text payload if present
            if portnum == "TEXT_MESSAGE_APP":
                msg_data["text"] = decoded.get("text", "")

            # Publish to MQTT
            for device_id in self._active_devices:
                self._publish_data("message", msg_data, device_id)
        except Exception:
            logger.exception("Error processing received packet")

    def _on_node_update(self, node: dict[str, Any], interface: Any = None) -> None:
        """Handle a node info update."""
        try:
            node_data = self._parse_node(node)
            for device_id in self._active_devices:
                self._publish_data("position", node_data, device_id)
        except Exception:
            logger.exception("Error processing node update")

    # ------------------------------------------------------------------
    # Node list building
    # ------------------------------------------------------------------

    def _build_node_list(self) -> list[dict[str, Any]]:
        """Build a list of all known mesh nodes from the interface."""
        if self._interface is None:
            return []

        nodes: list[dict[str, Any]] = []
        node_db = getattr(self._interface, "nodes", None)
        if node_db is None:
            return []

        for node_id, node in node_db.items():
            parsed = self._parse_node(node)
            parsed["node_id"] = node_id
            nodes.append(parsed)

        return nodes

    @staticmethod
    def _parse_node(node: dict[str, Any]) -> dict[str, Any]:
        """Parse a meshtastic node dict into a clean format.

        Handles camelCase fields from the meshtastic library (hasWifi,
        hasBluetooth, etc.) and converts integer lat/lng to floats.
        """
        user = node.get("user", {})
        position = node.get("position", {})
        device_metrics = node.get("deviceMetrics", {})

        # Meshtastic stores lat/lng as int32 * 1e7
        lat_raw = position.get("latitude", position.get("latitudeI", 0))
        lng_raw = position.get("longitude", position.get("longitudeI", 0))

        # If values look like raw integers (> 1000), convert from 1e7 format
        if isinstance(lat_raw, int) and abs(lat_raw) > 1000:
            lat = lat_raw / 1e7
        else:
            lat = float(lat_raw) if lat_raw else 0.0

        if isinstance(lng_raw, int) and abs(lng_raw) > 1000:
            lng = lng_raw / 1e7
        else:
            lng = float(lng_raw) if lng_raw else 0.0

        return {
            "long_name": user.get("longName", user.get("long_name", "")),
            "short_name": user.get("shortName", user.get("short_name", "")),
            "hw_model": user.get("hwModel", user.get("hw_model", "UNKNOWN")),
            "role": user.get("role", "CLIENT"),
            "latitude": lat,
            "longitude": lng,
            "altitude": position.get("altitude", 0),
            "battery_level": device_metrics.get(
                "batteryLevel", device_metrics.get("battery_level", 0)
            ),
            "voltage": device_metrics.get("voltage", 0.0),
            "snr": node.get("snr", 0.0),
            "air_util_tx": device_metrics.get(
                "airUtilTx", device_metrics.get("air_util_tx", 0.0)
            ),
            "has_wifi": user.get("hasWifi", user.get("has_wifi", False)),
            "has_bluetooth": user.get(
                "hasBluetooth", user.get("has_bluetooth", False)
            ),
            "last_heard": node.get("lastHeard", node.get("last_heard", 0)),
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Background polling
    # ------------------------------------------------------------------

    def _poll_loop(self, device_id: str) -> None:
        """Periodically publish the full node list to MQTT."""
        while self._connected and self._running:
            try:
                nodes = self._build_node_list()
                self._publish_data(
                    "nodes",
                    {"nodes": nodes, "count": len(nodes), "timestamp": time.time()},
                    device_id,
                )
            except Exception:
                logger.exception("Error in node poll loop")

            # Sleep in small increments so we can exit quickly
            for _ in range(int(self._poll_interval)):
                if not self._connected or not self._running:
                    break
                time.sleep(1.0)
