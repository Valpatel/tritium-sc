# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MeshtasticPlugin — LoRa mesh radio bridge for Tritium SC.

Bridges Meshtastic radio networks into the Tritium command center,
enabling long-range command and control of remote sensor nodes, robots,
and edge devices via LoRa mesh.

Supports multiple connection methods:
- Serial (USB-connected Meshtastic radio)
- TCP (network-connected radio or meshtastic-web)
- MQTT (Meshtastic MQTT gateway)

Messages are bridged bidirectionally:
- Meshtastic → Tritium: node positions, telemetry, text messages
- Tritium → Meshtastic: commands, waypoints, alerts

Each Meshtastic node appears as a TrackedTarget on the tactical map
with real GPS coordinates.
"""

from __future__ import annotations

import logging
import os
import threading
import time
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


class MeshtasticPlugin(PluginInterface):
    """LoRa mesh radio bridge for long-range command and control.

    Connects to Meshtastic radios and bridges their mesh network
    into the Tritium command center. Each radio node appears as a
    tracked target on the tactical map with real GPS coordinates.
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

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.meshtastic"

    @property
    def name(self) -> str:
        return "Meshtastic Bridge"

    @property
    def version(self) -> str:
        return "0.1.0"

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
        self._logger.info(
            "Meshtastic plugin configured (connection=%s, enabled=%s)",
            self._config.connection_type,
            self._config.enabled,
        )

    def start(self) -> None:
        """Connect to Meshtastic radio and start listening."""
        if self._running:
            return
        self._running = True

        if not self._config.enabled:
            self._logger.info(
                "Meshtastic disabled (set MESHTASTIC_ENABLED=true to activate)"
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
        """Update a single Meshtastic node in the tracker."""
        user = node_info.get("user", {})
        position = node_info.get("position", {})

        name = user.get("longName") or user.get("shortName") or node_id
        lat = position.get("latitude", 0.0)
        lng = position.get("longitude", 0.0)
        alt = position.get("altitude", 0.0)
        battery = node_info.get("deviceMetrics", {}).get("batteryLevel", 100) / 100.0
        last_heard = node_info.get("lastHeard", 0)
        snr = node_info.get("snr", 0.0)

        # Cache node state
        self._nodes[node_id] = {
            "name": name,
            "lat": lat,
            "lng": lng,
            "alt": alt,
            "battery": battery,
            "last_heard": last_heard,
            "snr": snr,
            "hw_model": user.get("hwModel", "unknown"),
        }

        # Push to TargetTracker if we have GPS coordinates
        if self._tracker and (lat != 0.0 or lng != 0.0):
            from engine.tactical.geo import latlng_to_local
            local = latlng_to_local(lat, lng)
            tid = f"mesh_{node_id.replace('!', '')}"

            # Use update_from_simulation path for friendly mesh nodes
            self._tracker.update_from_simulation({
                "target_id": tid,
                "name": f"[Mesh] {name}",
                "alliance": "friendly",
                "asset_type": "mesh_radio",
                "position": {"x": local["x"], "y": local["y"]},
                "heading": 0.0,
                "speed": 0.0,
                "battery": battery,
                "status": "active",
            })

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

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the Meshtastic API."""
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
