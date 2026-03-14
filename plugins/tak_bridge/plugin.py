# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TAKBridgePlugin — publishes Tritium targets as CoT events for ATAK/WinTAK.

Three transport layers:
    1. Multicast UDP (standard TAK SA broadcast, default 239.2.3.1:6969)
    2. TCP to TAK server (configurable host:port)
    3. MQTT (tritium/{site}/cot topic)

Inbound CoT from any transport is parsed and injected as TrackedTargets.

Config via env vars:
    TAK_ENABLED           — master enable (default: false)
    TAK_SERVER_HOST       — TAK server TCP host (default: "")
    TAK_SERVER_PORT       — TAK server TCP port (default: 8087)
    TAK_MULTICAST_ADDR    — multicast group (default: 239.2.3.1)
    TAK_MULTICAST_PORT    — multicast port (default: 6969)
    TAK_CALLSIGN          — our callsign (default: TRITIUM-SC)
    TAK_PUBLISH_INTERVAL  — seconds between target publishes (default: 5)
    TAK_STALE_SECONDS     — CoT stale timeout (default: 120)
    MQTT_SITE_ID          — MQTT site id for topic prefix (default: home)
"""

from __future__ import annotations

import logging
import os
import queue as queue_mod
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("tak-bridge-plugin")


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


class TAKBridgePlugin(PluginInterface):
    """Publishes Tritium targets as CoT events for ATAK/WinTAK interoperability.

    Transports:
        - Multicast UDP (standard TAK SA broadcast)
        - TCP to TAK server
        - MQTT (via EventBus -> mqtt_bridge)

    Subscribes to TargetTracker updates and converts TrackedTargets to CoT XML.
    Receives inbound CoT and creates TrackedTargets.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        # Config (set in configure from env vars)
        self._enabled = False
        self._server_host = ""
        self._server_port = 8087
        self._multicast_addr = "239.2.3.1"
        self._multicast_port = 6969
        self._callsign = "TRITIUM-SC"
        self._publish_interval = 5.0
        self._stale_seconds = 120
        self._site_id = "home"

        # State
        self._running = False
        self._lock = threading.Lock()

        # Sockets
        self._mcast_sock: Optional[socket.socket] = None
        self._tcp_sock: Optional[socket.socket] = None
        self._tcp_connected = False

        # Threads
        self._publish_thread: Optional[threading.Thread] = None
        self._mcast_recv_thread: Optional[threading.Thread] = None
        self._tcp_recv_thread: Optional[threading.Thread] = None

        # Stats
        self._messages_sent = 0
        self._messages_received = 0
        self._last_error = ""
        self._connected_clients: dict[str, dict] = {}

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.tak-bridge"

    @property
    def name(self) -> str:
        return "TAK Bridge"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Read config from env
        self._enabled = _env_bool("TAK_ENABLED", False)
        self._server_host = os.environ.get("TAK_SERVER_HOST", "")
        self._server_port = _env_int("TAK_SERVER_PORT", 8087)
        self._multicast_addr = os.environ.get("TAK_MULTICAST_ADDR", "239.2.3.1")
        self._multicast_port = _env_int("TAK_MULTICAST_PORT", 6969)
        self._callsign = os.environ.get("TAK_CALLSIGN", "TRITIUM-SC")
        self._publish_interval = _env_float("TAK_PUBLISH_INTERVAL", 5.0)
        self._stale_seconds = _env_int("TAK_STALE_SECONDS", 120)
        self._site_id = os.environ.get("MQTT_SITE_ID", "home")

        # Register API routes
        self._register_routes()

        self._logger.info(
            "TAK Bridge plugin configured (enabled=%s, mcast=%s:%d, server=%s:%d)",
            self._enabled, self._multicast_addr, self._multicast_port,
            self._server_host or "(none)", self._server_port,
        )

    def start(self) -> None:
        if self._running:
            return
        if not self._enabled:
            self._logger.info("TAK Bridge disabled (TAK_ENABLED not set)")
            return

        self._running = True

        # Setup multicast socket
        self._setup_multicast()

        # Setup TCP connection
        if self._server_host:
            self._setup_tcp()

        # Publish thread
        self._publish_thread = threading.Thread(
            target=self._publish_loop,
            daemon=True,
            name="tak-bridge-publish",
        )
        self._publish_thread.start()

        # Multicast receive thread
        if self._mcast_sock is not None:
            self._mcast_recv_thread = threading.Thread(
                target=self._mcast_recv_loop,
                daemon=True,
                name="tak-bridge-mcast-recv",
            )
            self._mcast_recv_thread.start()

        # TCP receive thread
        if self._tcp_connected:
            self._tcp_recv_thread = threading.Thread(
                target=self._tcp_recv_loop,
                daemon=True,
                name="tak-bridge-tcp-recv",
            )
            self._tcp_recv_thread.start()

        self._logger.info("TAK Bridge plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._publish_thread and self._publish_thread.is_alive():
            self._publish_thread.join(timeout=3.0)
        if self._mcast_recv_thread and self._mcast_recv_thread.is_alive():
            self._mcast_recv_thread.join(timeout=3.0)
        if self._tcp_recv_thread and self._tcp_recv_thread.is_alive():
            self._tcp_recv_thread.join(timeout=3.0)

        self._close_sockets()
        self._logger.info("TAK Bridge plugin stopped")

    @property
    def healthy(self) -> bool:
        if not self._enabled:
            return True  # disabled is fine
        return self._running

    # -- Properties --------------------------------------------------------

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "running": self._running,
                "callsign": self._callsign,
                "multicast": f"{self._multicast_addr}:{self._multicast_port}",
                "server": f"{self._server_host}:{self._server_port}" if self._server_host else "",
                "tcp_connected": self._tcp_connected,
                "messages_sent": self._messages_sent,
                "messages_received": self._messages_received,
                "connected_clients": len(self._connected_clients),
                "last_error": self._last_error,
                "site_id": self._site_id,
            }

    @property
    def connected_clients(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._connected_clients)

    # -- Socket setup ------------------------------------------------------

    def _setup_multicast(self) -> None:
        """Create and bind multicast UDP socket."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass

            # Bind to receive multicast
            sock.bind(("", self._multicast_port))

            # Join multicast group
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self._multicast_addr),
                socket.INADDR_ANY,
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Set multicast TTL for outbound
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)

            sock.settimeout(1.0)
            self._mcast_sock = sock
            self._logger.info(
                "Multicast socket ready on %s:%d",
                self._multicast_addr, self._multicast_port,
            )
        except OSError as e:
            self._logger.warning("Failed to setup multicast: %s", e)
            self._last_error = f"multicast setup: {e}"
            self._mcast_sock = None

    def _setup_tcp(self) -> None:
        """Connect TCP socket to TAK server."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((self._server_host, self._server_port))
            sock.settimeout(1.0)
            self._tcp_sock = sock
            self._tcp_connected = True
            self._logger.info(
                "TCP connected to TAK server %s:%d",
                self._server_host, self._server_port,
            )
        except OSError as e:
            self._logger.warning("Failed to connect to TAK server: %s", e)
            self._last_error = f"TCP connect: {e}"
            self._tcp_sock = None
            self._tcp_connected = False

    def _close_sockets(self) -> None:
        if self._mcast_sock:
            try:
                self._mcast_sock.close()
            except OSError:
                pass
            self._mcast_sock = None

        if self._tcp_sock:
            try:
                self._tcp_sock.close()
            except OSError:
                pass
            self._tcp_sock = None
            self._tcp_connected = False

    # -- CoT generation (reuses engine/comms/cot.py) -----------------------

    def _target_to_cot(self, target_dict: dict) -> str:
        """Convert target dict to CoT XML using engine's cot module."""
        from engine.comms.cot import target_to_cot_xml
        return target_to_cot_xml(target_dict, stale_seconds=self._stale_seconds)

    def _cot_to_target(self, xml_str: str) -> Optional[dict]:
        """Parse CoT XML to target dict using engine's cot module."""
        from engine.comms.cot import cot_xml_to_target
        return cot_xml_to_target(xml_str)

    # -- Outbound ----------------------------------------------------------

    def _should_publish(self, target_dict: dict) -> bool:
        """Skip targets that originated from TAK (prevent echo loops)."""
        tid = target_dict.get("target_id", "")
        return not tid.startswith("tak_")

    def _send_cot(self, xml_str: str) -> None:
        """Send CoT XML to all active transports."""
        xml_bytes = xml_str.encode("utf-8")

        # 1. Multicast UDP
        if self._mcast_sock is not None:
            try:
                self._mcast_sock.sendto(
                    xml_bytes,
                    (self._multicast_addr, self._multicast_port),
                )
            except OSError as e:
                self._logger.debug("Multicast send error: %s", e)

        # 2. TCP to TAK server
        if self._tcp_sock is not None and self._tcp_connected:
            try:
                self._tcp_sock.sendall(xml_bytes)
            except OSError as e:
                self._logger.debug("TCP send error: %s", e)
                self._tcp_connected = False
                self._last_error = f"TCP send: {e}"

        # 3. MQTT via EventBus
        if self._event_bus is not None:
            self._event_bus.publish("tak_cot_outbound", {
                "topic": f"tritium/{self._site_id}/cot",
                "xml": xml_str,
            })

    def _publish_loop(self) -> None:
        """Periodically read targets and publish as CoT."""
        self._logger.info("TAK publish loop started")
        while self._running:
            try:
                if self._tracker is not None:
                    targets = self._tracker.get_all()
                    for target in targets:
                        d = target.to_dict()
                        if self._should_publish(d):
                            xml = self._target_to_cot(d)
                            self._send_cot(xml)
                            with self._lock:
                                self._messages_sent += 1
            except Exception as e:
                self._logger.debug("TAK publish error: %s", e)
                with self._lock:
                    self._last_error = str(e)

            time.sleep(self._publish_interval)

        self._logger.info("TAK publish loop stopped")

    # -- Inbound -----------------------------------------------------------

    def _handle_inbound_cot(self, xml_str: str) -> None:
        """Process an inbound CoT XML message from any transport."""
        target = self._cot_to_target(xml_str)
        if target is None:
            return

        with self._lock:
            self._messages_received += 1

        original_id = target["target_id"]
        target["target_id"] = f"tak_{original_id}"
        target["source"] = "tak"

        # Track client
        with self._lock:
            self._connected_clients[original_id] = {
                "callsign": target.get("name", original_id),
                "uid": original_id,
                "lat": target.get("lat", 0.0),
                "lng": target.get("lng", 0.0),
                "alliance": target.get("alliance", "unknown"),
                "asset_type": target.get("asset_type", "person"),
                "last_seen": time.time(),
            }

        # Inject into TargetTracker
        if self._tracker is not None:
            self._tracker.update_from_simulation(target)

        # Publish event
        if self._event_bus is not None:
            self._event_bus.publish("tak_client_update", {
                "uid": original_id,
                "target_id": target["target_id"],
                "callsign": target.get("name", original_id),
                "alliance": target.get("alliance", "unknown"),
                "lat": target.get("lat", 0.0),
                "lng": target.get("lng", 0.0),
            })

    def _mcast_recv_loop(self) -> None:
        """Receive CoT XML from multicast UDP."""
        self._logger.info("Multicast receive loop started")
        while self._running and self._mcast_sock is not None:
            try:
                data, addr = self._mcast_sock.recvfrom(65535)
                if data:
                    xml_str = data.decode("utf-8", errors="replace")
                    self._handle_inbound_cot(xml_str)
            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    self._logger.debug("Multicast recv error: %s", e)
                break
        self._logger.info("Multicast receive loop stopped")

    def _tcp_recv_loop(self) -> None:
        """Receive CoT XML from TAK server TCP connection."""
        self._logger.info("TCP receive loop started")
        buf = b""
        while self._running and self._tcp_sock is not None and self._tcp_connected:
            try:
                data = self._tcp_sock.recv(65535)
                if not data:
                    self._tcp_connected = False
                    break
                buf += data

                # CoT events are complete XML documents — split on </event>
                while b"</event>" in buf:
                    idx = buf.index(b"</event>") + len(b"</event>")
                    xml_bytes = buf[:idx]
                    buf = buf[idx:]
                    xml_str = xml_bytes.decode("utf-8", errors="replace")
                    self._handle_inbound_cot(xml_str)

            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    self._logger.debug("TCP recv error: %s", e)
                self._tcp_connected = False
                break
        self._logger.info("TCP receive loop stopped")

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
