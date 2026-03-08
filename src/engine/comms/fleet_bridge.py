# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FleetBridge — bridges tritium-edge fleet server WebSocket to internal EventBus.

Connects to the fleet server's WebSocket endpoint and injects device
heartbeats, registration events, and BLE sensor presence data into the
local EventBus.  Runs in a background thread with auto-reconnect,
mirroring the pattern used by MQTTBridge.

Fleet Server WebSocket Events:
    device_heartbeat   -> fleet.heartbeat   (device telemetry)
    device_registered  -> fleet.registered  (new device auto-registered)
    device_offline     -> fleet.offline     (missed heartbeats)
    ota_started        -> fleet.ota_started
    ota_result         -> fleet.ota_result
    command_sent       -> fleet.command_sent

BLE sensor data extracted from heartbeats:
    heartbeat.sensors.ble_scanner.devices -> fleet.ble_presence per device
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("amy.fleet")


class FleetBridge:
    """Bridges tritium-edge fleet server WebSocket <-> internal EventBus.

    Usage::

        bridge = FleetBridge(event_bus, ws_url="ws://192.168.86.9:8080/ws")
        bridge.start()
        ...
        bridge.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        ws_url: str = "ws://192.168.86.9:8080/ws",
        reconnect_interval: float = 5.0,
        ping_interval: float = 30.0,
    ) -> None:
        self._event_bus = event_bus
        self._ws_url = ws_url
        self._reconnect_interval = reconnect_interval
        self._ping_interval = ping_interval
        self._ws = None
        self._connected = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Stats
        self._messages_received: int = 0
        self._last_error: str = ""
        self._last_heartbeat_ts: float = 0.0
        # Device tracking: device_id -> last heartbeat data
        self._devices: dict[str, dict] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return {
            "connected": self._connected,
            "ws_url": self._ws_url,
            "messages_received": self._messages_received,
            "last_error": self._last_error,
            "devices_tracked": len(self._devices),
            "device_ids": list(self._devices.keys()),
        }

    @property
    def devices(self) -> dict[str, dict]:
        """Return dict of tracked devices (device_id -> last heartbeat data)."""
        return dict(self._devices)

    def start(self) -> None:
        """Connect to fleet server WebSocket in a background thread."""
        if self._running:
            return
        try:
            import websocket  # noqa: F401
        except ImportError:
            logger.warning("websocket-client not installed — fleet bridge disabled")
            self._last_error = "websocket-client not installed"
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="fleet-bridge",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Fleet bridge starting, target: {self._ws_url}")

    def stop(self) -> None:
        """Disconnect from fleet server WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        logger.info("Fleet bridge stopped")

    # --- Background thread ---

    def _run_loop(self) -> None:
        """Main loop: connect, listen, reconnect on failure."""
        import websocket

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(
                    ping_interval=self._ping_interval,
                    ping_timeout=10,
                )
            except Exception as e:
                logger.debug(f"Fleet WebSocket error: {e}")
                self._last_error = str(e)

            self._connected = False
            if self._running:
                logger.info(
                    f"Fleet bridge reconnecting in {self._reconnect_interval}s"
                )
                time.sleep(self._reconnect_interval)

    # --- WebSocket callbacks ---

    def _on_open(self, ws) -> None:
        self._connected = True
        logger.info(f"Fleet bridge connected to {self._ws_url}")
        self._event_bus.publish("fleet.connected", {"ws_url": self._ws_url})

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self._connected = False
        logger.info(f"Fleet bridge disconnected (code={close_status_code})")
        self._event_bus.publish("fleet.disconnected", {
            "code": close_status_code,
            "message": close_msg,
        })

    def _on_error(self, ws, error) -> None:
        self._last_error = str(error)
        logger.debug(f"Fleet WebSocket error: {error}")

    def _on_message(self, ws, message: str) -> None:
        """Parse incoming fleet server message and inject into EventBus."""
        self._messages_received += 1
        try:
            msg = json.loads(message)
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Fleet bridge bad payload: {e}")
            return

        event_type = msg.get("type", "")
        data = msg.get("data", {})
        timestamp = msg.get("timestamp", "")

        try:
            if event_type == "device_heartbeat":
                self._handle_heartbeat(data, timestamp)
            elif event_type == "device_registered":
                self._handle_registered(data, timestamp)
            elif event_type == "device_offline":
                self._handle_offline(data, timestamp)
            elif event_type in ("ota_started", "ota_result", "ota_scheduled",
                                "command_sent", "firmware_uploaded"):
                # Forward other fleet events with fleet.* prefix
                self._event_bus.publish(f"fleet.{event_type}", {
                    **data,
                    "server_timestamp": timestamp,
                })
            elif event_type == "pong":
                pass  # Keepalive response, ignore
            else:
                logger.debug(f"Fleet bridge unknown event: {event_type}")
        except Exception as e:
            logger.debug(f"Fleet bridge handler error for {event_type}: {e}")

    # --- Event handlers ---

    def _handle_heartbeat(self, data: dict, timestamp: str) -> None:
        """Process device_heartbeat -> fleet.heartbeat + fleet.ble_presence."""
        device_id = data.get("device_id", "unknown")
        self._devices[device_id] = data
        self._last_heartbeat_ts = time.monotonic()

        # Emit fleet.heartbeat with full device data
        self._event_bus.publish("fleet.heartbeat", {
            "device_id": device_id,
            "board": data.get("board", "unknown"),
            "version": data.get("version", "unknown"),
            "ip": data.get("ip"),
            "mac": data.get("mac"),
            "rssi": data.get("rssi"),
            "free_heap": data.get("free_heap"),
            "uptime_s": data.get("uptime_s"),
            "online": data.get("_online", True),
            "capabilities": data.get("capabilities", []),
            "server_timestamp": timestamp,
        })

        # Extract BLE sensor data and emit per-device presence events
        sensors = data.get("sensors", {})
        ble_scanner = sensors.get("ble_scanner", {})
        ble_devices = ble_scanner.get("devices", [])
        if ble_devices:
            for ble_dev in ble_devices:
                self._event_bus.publish("fleet.ble_presence", {
                    "reporter_id": device_id,
                    "ble_addr": ble_dev.get("addr", ""),
                    "ble_name": ble_dev.get("name", ""),
                    "rssi": ble_dev.get("rssi"),
                    "device_type": ble_dev.get("type", "unknown"),
                    "server_timestamp": timestamp,
                })

        # Also emit fleet.sensor for any non-BLE sensor data
        for sensor_type, sensor_data in sensors.items():
            if sensor_type == "ble_scanner":
                continue  # Already handled above
            self._event_bus.publish("fleet.sensor", {
                "device_id": device_id,
                "sensor_type": sensor_type,
                "data": sensor_data,
                "server_timestamp": timestamp,
            })

    def _handle_registered(self, data: dict, timestamp: str) -> None:
        """Process device_registered -> fleet.registered."""
        device_id = data.get("device_id", "unknown")
        self._devices[device_id] = data
        self._event_bus.publish("fleet.registered", {
            "device_id": device_id,
            "board": data.get("board", "unknown"),
            "mac": data.get("mac"),
            "tags": data.get("tags", []),
            "server_timestamp": timestamp,
        })
        logger.info(f"Fleet device registered: {device_id}")

    def _handle_offline(self, data: dict, timestamp: str) -> None:
        """Process device_offline -> fleet.offline."""
        device_id = data.get("device_id", "unknown")
        # Mark device as offline in our tracking
        if device_id in self._devices:
            self._devices[device_id]["_online"] = False
        self._event_bus.publish("fleet.offline", {
            "device_id": device_id,
            "server_timestamp": timestamp,
        })
        logger.info(f"Fleet device offline: {device_id}")
