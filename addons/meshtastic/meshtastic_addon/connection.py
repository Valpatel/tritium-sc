# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Connection manager — handles USB serial, TCP, BLE, and MQTT transports."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("meshtastic.connection")


class ConnectionManager:
    """Manages connection to a Meshtastic device across multiple transports."""

    def __init__(self, node_manager=None, event_bus=None):
        self.node_manager = node_manager
        self.event_bus = event_bus
        self.interface = None
        self.is_connected = False
        self.transport_type: str = "none"  # serial, tcp, ble, mqtt
        self.port: str = ""
        self.device_info: dict = {}

    async def auto_connect(self):
        """Try to auto-detect and connect to a Meshtastic device.

        Connection priority:
        1. Environment variable MESHTASTIC_SERIAL_PORT (exact port)
        2. /dev/ttyACM0 (known T-LoRa Pager port)
        3. Auto-detect by VID:PID scan
        4. TCP host if MESHTASTIC_TCP_HOST is set
        5. Graceful disconnected mode if all fail
        """
        # Try USB serial first
        port = self._find_serial_device()
        if port:
            try:
                await self.connect_serial(port)
                if self.is_connected:
                    return
            except Exception as e:
                log.warning(f"Serial connect to {port} failed: {e}")

        # Try known port /dev/ttyACM0 as fallback (T-LoRa Pager default)
        if not self.is_connected:
            from pathlib import Path
            fallback_port = "/dev/ttyACM0"
            if Path(fallback_port).exists() and port != fallback_port:
                try:
                    await self.connect_serial(fallback_port)
                    if self.is_connected:
                        return
                except Exception as e:
                    log.warning(f"Fallback serial connect to {fallback_port} failed: {e}")

        # Try TCP if configured
        tcp_host = os.environ.get("MESHTASTIC_TCP_HOST")
        if tcp_host and not self.is_connected:
            try:
                await self.connect_tcp(tcp_host)
                if self.is_connected:
                    return
            except Exception as e:
                log.warning(f"TCP connect to {tcp_host} failed: {e}")

        log.info("No Meshtastic device found — running in disconnected mode (connect later via API)")

    async def connect_serial(self, port: str, timeout: float = 30.0, retries: int = 1):
        """Connect via USB serial port.

        Args:
            port: Serial device path (e.g. /dev/ttyACM0).
            timeout: Max seconds to wait for the meshtastic library to connect
                     and receive device config. The library's internal default
                     is 300s which is far too long for an API call.
            retries: Number of retry attempts after a failure (with 2s delay).
        """
        from pathlib import Path
        if not Path(port).exists():
            log.warning(f"Serial port {port} does not exist")
            self.is_connected = False
            return

        for attempt in range(1 + retries):
            try:
                import meshtastic.serial_interface
                log.info(f"Connecting to Meshtastic on {port} (attempt {attempt + 1}, timeout {timeout}s)...")

                # Disconnect any existing interface first
                if self.interface:
                    try:
                        self.interface.close()
                    except Exception:
                        pass
                    self.interface = None

                loop = asyncio.get_event_loop()

                # The meshtastic SerialInterface constructor blocks while it
                # waits for the device to send its config (waitForConfig).
                # The default timeout is 300s which is far too long.  We pass
                # a shorter timeout to the library AND wrap the executor call
                # in asyncio.wait_for so the API endpoint doesn't hang.
                lib_timeout = max(int(timeout) - 2, 10)  # leave 2s headroom

                def _connect():
                    return meshtastic.serial_interface.SerialInterface(
                        port, debugOut=None, noProto=False, timeout=lib_timeout,
                    )

                self.interface = await asyncio.wait_for(
                    loop.run_in_executor(None, _connect),
                    timeout=timeout,
                )
                self.is_connected = True
                self.transport_type = "serial"
                self.port = port
                self._read_device_info()
                log.info(f"Connected to {self.device_info.get('long_name', port)} via serial")
                if self.event_bus:
                    self.event_bus.emit("meshtastic:connected", {
                        "transport": "serial", "port": port, "device": self.device_info,
                    })
                return  # success
            except asyncio.TimeoutError:
                log.warning(f"Serial connection to {port} timed out after {timeout}s (attempt {attempt + 1})")
                # Clean up the partially-connected interface
                if self.interface:
                    try:
                        self.interface.close()
                    except Exception:
                        pass
                    self.interface = None
                self.is_connected = False
            except ImportError:
                log.warning("meshtastic package not installed — pip install meshtastic")
                self.is_connected = False
                return  # no point retrying
            except Exception as e:
                log.warning(f"Serial connection failed on {port}: {e} (attempt {attempt + 1})")
                # Clean up on failure
                if self.interface:
                    try:
                        self.interface.close()
                    except Exception:
                        pass
                    self.interface = None
                self.is_connected = False

            # Retry delay (only if we have retries left)
            if attempt < retries:
                log.info(f"Retrying serial connection in 2s...")
                await asyncio.sleep(2)

    async def connect_tcp(self, host: str, port: int = 4403, timeout: float = 30.0):
        """Connect via WiFi/TCP."""
        try:
            import meshtastic.tcp_interface
            log.info(f"Connecting to Meshtastic on {host}:{port} (timeout {timeout}s)...")

            if self.interface:
                try:
                    self.interface.close()
                except Exception:
                    pass
                self.interface = None

            loop = asyncio.get_event_loop()
            lib_timeout = max(int(timeout) - 2, 10)

            def _connect():
                return meshtastic.tcp_interface.TCPInterface(host, noProto=False, timeout=lib_timeout)

            self.interface = await asyncio.wait_for(
                loop.run_in_executor(None, _connect),
                timeout=timeout,
            )
            self.is_connected = True
            self.transport_type = "tcp"
            self.port = f"{host}:{port}"
            self._read_device_info()
            log.info(f"Connected to {self.device_info.get('long_name', host)} via TCP")
        except asyncio.TimeoutError:
            log.warning(f"TCP connection to {host}:{port} timed out after {timeout}s")
            if self.interface:
                try:
                    self.interface.close()
                except Exception:
                    pass
                self.interface = None
            self.is_connected = False
        except Exception as e:
            log.warning(f"TCP connection failed: {e}")
            if self.interface:
                try:
                    self.interface.close()
                except Exception:
                    pass
                self.interface = None
            self.is_connected = False

    async def disconnect(self):
        """Disconnect from the current device."""
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass
            self.interface = None
        self.is_connected = False
        self.transport_type = "none"
        self.port = ""
        log.info("Disconnected from Meshtastic device")

    async def get_nodes(self) -> dict:
        """Get all known mesh nodes from the connected device."""
        if not self.interface or not self.is_connected:
            return {}
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: dict(self.interface.nodes or {}))
        except Exception as e:
            log.warning(f"Failed to get nodes: {e}")
            return {}

    async def send_text(self, text: str, destination: int | str | None = None):
        """Send a text message via the mesh."""
        if not self.interface or not self.is_connected:
            return False
        try:
            loop = asyncio.get_event_loop()
            if destination:
                await loop.run_in_executor(None, lambda: self.interface.sendText(text, destinationId=destination))
            else:
                await loop.run_in_executor(None, lambda: self.interface.sendText(text))
            return True
        except Exception as e:
            log.warning(f"Send failed: {e}")
            return False

    def _find_serial_device(self) -> str | None:
        """Scan /dev for Meshtastic-compatible serial devices."""
        # Check environment variable first
        env_port = os.environ.get("MESHTASTIC_SERIAL_PORT")
        if env_port and Path(env_port).exists():
            return env_port

        # Auto-detect by checking /dev/ttyACM* and /dev/ttyUSB*
        for pattern in ["/dev/ttyACM*", "/dev/ttyUSB*"]:
            import glob
            for port in sorted(glob.glob(pattern)):
                # Check if this is a Meshtastic device by trying to read its VID:PID
                if self._check_vid_pid(port):
                    return port

        return None

    def _check_vid_pid(self, port: str) -> bool:
        """Check if a serial port matches known Meshtastic VID:PIDs."""
        known_vids = {"303a", "10c4", "1a86"}  # Espressif, SiLabs, CH340
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                if p.device == port and p.vid:
                    vid_hex = f"{p.vid:04x}"
                    if vid_hex in known_vids:
                        return True
        except ImportError:
            # No pyserial — just try the port
            return Path(port).exists()
        return False

    def _read_device_info(self):
        """Read device metadata after connecting.

        Only reads data that's already cached from the initial config exchange.
        Avoids getMetadata() which sends a new request and blocks waiting for a reply.
        """
        if not self.interface:
            return
        try:
            info = self.interface.getMyNodeInfo()
            user = info.get("user", {})
            self.device_info = {
                "node_id": user.get("id", ""),
                "long_name": user.get("longName", ""),
                "short_name": user.get("shortName", ""),
                "hw_model": user.get("hwModel", ""),
                "mac": user.get("macaddr", ""),
            }
            # Note: getMetadata() sends an admin request and blocks waiting
            # for a reply, which can hang.  Only call it if we already have
            # metadata cached from the initial config exchange.
            if hasattr(self.interface, 'metadata') and self.interface.metadata:
                metadata = self.interface.metadata
                self.device_info["firmware"] = getattr(metadata, 'firmware_version', '')
                self.device_info["has_wifi"] = getattr(metadata, 'has_wifi', False)
                self.device_info["has_bluetooth"] = getattr(metadata, 'has_bluetooth', False)
                self.device_info["role"] = getattr(metadata, 'role', '')
        except Exception as e:
            log.warning(f"Failed to read device info: {e}")
