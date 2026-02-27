"""MeshCoreBridge — bridges MeshCore mesh radio <-> internal EventBus + TargetTracker.

MeshCore radios connect via USB serial.  This bridge reads serial frames,
injects discovered nodes into EventBus and TargetTracker.

Architecture follows MeshtasticBridge pattern exactly:
  - Graceful import: try/except for ``serial`` (pyserial) package
  - Thread-safe state with locks
  - Stats property matching MeshtasticBridge shape
  - EventBus publish for all inbound events
  - Position conversion via latlng_to_local()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("amy.meshcore")


@dataclass
class MeshCoreNode:
    """A discovered MeshCore mesh radio node."""

    node_id: str
    name: str = ""
    hardware: str = ""
    position: dict | None = None  # {"lat": float, "lng": float, "alt": float}
    battery: float | None = None
    rssi: int | None = None
    last_heard: float = field(default_factory=time.monotonic)


class MeshCoreBridge:
    """Bridges MeshCore serial radio <-> EventBus.  Follows MeshtasticBridge pattern."""

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        serial_port: str = "",
        baud_rate: int = 115200,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._serial_port = serial_port
        self._baud_rate = baud_rate
        self._serial = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()
        self._nodes: dict[str, MeshCoreNode] = {}
        self._messages: list[dict] = []  # capped at 500
        self._frames_received: int = 0
        self._last_error: str = ""
        self._thread: threading.Thread | None = None

    # --- Properties ---

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def nodes(self) -> dict[str, MeshCoreNode]:
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
            "serial_port": self._serial_port or "none",
            "frames_received": self._frames_received,
            "nodes_discovered": len(self._nodes),
            "last_error": self._last_error,
        }

    # --- Lifecycle ---

    def start(self) -> None:
        """Open serial port and start reading frames in a background thread."""
        if self._running:
            return

        try:
            import serial as _serial_mod  # noqa: F401
        except ImportError:
            logger.warning("pyserial package not installed -- meshcore bridge disabled")
            self._last_error = "pyserial not installed"
            return

        if not self._serial_port:
            logger.warning("No serial port configured -- meshcore bridge disabled")
            self._last_error = "no serial port"
            return

        self._running = True

        try:
            import serial
            self._serial = serial.Serial(
                port=self._serial_port,
                baudrate=self._baud_rate,
                timeout=1.0,
            )
            self._connected = True
            logger.info(f"MeshCore bridge connected to {self._serial_port}")
            self._event_bus.publish("meshcore:connected", {"port": self._serial_port})

            # Start background reader thread
            self._thread = threading.Thread(
                target=self._read_loop, daemon=True, name="meshcore-reader"
            )
            self._thread.start()
        except Exception as e:
            logger.error(f"MeshCore connection failed: {e}")
            self._last_error = str(e)
            self._serial = None
            self._running = False

    def stop(self) -> None:
        """Stop reading and close serial port."""
        self._running = False

        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        self._connected = False
        logger.info("MeshCore bridge stopped")

    # --- Frame processing (public, also called from _read_loop) ---

    def process_frame(self, frame: dict) -> None:
        """Process a single MeshCore protocol frame.

        Frame types:
          - node_info: node discovery
          - position: GPS position update
          - text: text message
          - telemetry: battery/signal data
        """
        self._frames_received += 1
        frame_type = frame.get("type", "")

        try:
            if frame_type == "node_info":
                self._handle_node_info(frame)
            elif frame_type == "position":
                self._handle_position(frame)
            elif frame_type == "text":
                self._handle_text(frame)
            elif frame_type == "telemetry":
                self._handle_telemetry(frame)
            else:
                logger.debug(f"Unknown MeshCore frame type: {frame_type}")
        except Exception as e:
            logger.debug(f"MeshCore frame handler error: {e}")

    # --- Internal handlers ---

    def _handle_node_info(self, frame: dict) -> None:
        """Handle node discovery frame."""
        node_id = frame.get("node_id", "")
        if not node_id:
            return

        node = MeshCoreNode(
            node_id=node_id,
            name=frame.get("name", ""),
            hardware=frame.get("hardware", "meshcore"),
            last_heard=time.monotonic(),
        )

        with self._lock:
            self._nodes[node_id] = node

        # Register in target tracker
        self._tracker.update_from_simulation({
            "target_id": f"meshcore_{node_id}",
            "name": node.name or node_id,
            "alliance": "friendly",
            "asset_type": "mesh_radio",
            "position": {"x": 0.0, "y": 0.0},
            "heading": 0,
            "speed": 0,
            "battery": 1.0,
            "status": "active",
            "metadata": {"mesh_protocol": "meshcore"},
        })

        self._event_bus.publish("meshcore:node_discovered", {
            "node_id": node_id,
            "name": node.name,
            "hardware": node.hardware,
        })

    def _handle_position(self, frame: dict) -> None:
        """Handle position update frame."""
        node_id = frame.get("node_id", "")
        lat = frame.get("lat", 0.0)
        lng = frame.get("lng", 0.0)
        alt = frame.get("alt", 0.0)

        if lat == 0.0 and lng == 0.0:
            return

        # Convert WGS84 to local coordinates
        try:
            from engine.tactical.geo import latlng_to_local
            x, y, z = latlng_to_local(lat, lng, alt)
        except Exception:
            x, y, z = 0.0, 0.0, 0.0

        # Update node state
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None:
                node.position = {"lat": lat, "lng": lng, "alt": alt}
                node.last_heard = time.monotonic()

        # Update target tracker with local coordinates
        self._tracker.update_from_simulation({
            "target_id": f"meshcore_{node_id}",
            "name": self._get_node_name(node_id),
            "alliance": "friendly",
            "asset_type": "mesh_radio",
            "position": {"x": x, "y": y},
            "heading": 0,
            "speed": 0,
            "battery": self._get_node_battery(node_id),
            "status": "active",
            "metadata": {"mesh_protocol": "meshcore"},
        })

        self._event_bus.publish("meshcore:position_update", {
            "node_id": node_id,
            "lat": lat,
            "lng": lng,
            "alt": alt,
            "local_x": x,
            "local_y": y,
        })

    def _handle_text(self, frame: dict) -> None:
        """Handle text message frame."""
        node_id = frame.get("node_id", "unknown")
        text = frame.get("text", "")

        msg = {
            "from": node_id,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._messages.append(msg)
            if len(self._messages) > 500:
                self._messages = self._messages[-500:]

        self._event_bus.publish("meshcore:text_message", {
            "node_id": node_id,
            "text": text,
        })

    def _handle_telemetry(self, frame: dict) -> None:
        """Handle telemetry frame (battery, signal)."""
        node_id = frame.get("node_id", "")
        battery = frame.get("battery")
        rssi = frame.get("rssi")

        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None:
                if battery is not None:
                    node.battery = battery
                if rssi is not None:
                    node.rssi = rssi
                node.last_heard = time.monotonic()

        self._event_bus.publish("meshcore:telemetry", {
            "node_id": node_id,
            "battery": battery,
            "rssi": rssi,
        })

    # --- Background reader ---

    def _read_loop(self) -> None:
        """Read serial data in background thread. Parses newline-delimited JSON."""
        import json

        while self._running and self._serial is not None:
            try:
                line = self._serial.readline()
                if not line:
                    continue
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                frame = json.loads(line)
                self.process_frame(frame)
            except Exception as e:
                if self._running:
                    logger.debug(f"MeshCore read error: {e}")

    # --- Internal helpers ---

    def _get_node_name(self, node_id: str) -> str:
        """Get display name for a node, falling back to node_id."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None and node.name:
                return node.name
        return node_id

    def _get_node_battery(self, node_id: str) -> float:
        """Get battery level for a node, defaulting to 1.0."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None and node.battery is not None:
                return node.battery / 100.0
        return 1.0
