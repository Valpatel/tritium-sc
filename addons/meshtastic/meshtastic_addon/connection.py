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

# Default timeouts per transport.  Serial config exchange (channels, nodeinfo)
# can take 30-60s on mesh networks with many nodes.  The meshtastic library's
# SerialInterface `timeout` kwarg maps to `connectTimeout` (socket open), NOT
# to `waitForConfig` which has its own 300s internal default.  We use the
# outer asyncio.wait_for to enforce a hard wall-clock limit.
DEFAULT_SERIAL_TIMEOUT = 60.0
DEFAULT_TCP_TIMEOUT = 30.0
DEFAULT_BLE_TIMEOUT = 45.0
DEFAULT_MQTT_TIMEOUT = 15.0


class ConnectionManager:
    """Manages connection to a Meshtastic device across multiple transports."""

    def __init__(self, node_manager=None, event_bus=None):
        self.node_manager = node_manager
        self.event_bus = event_bus
        self.interface = None
        self._is_connected = False
        self.transport_type: str = "none"  # serial, tcp, ble, mqtt
        self.port: str = ""
        self.device_info: dict = {}

    @property
    def is_connected(self):
        """True if interface exists and we believe connection is active."""
        return self.interface is not None and self._is_connected

    @is_connected.setter
    def is_connected(self, value):
        self._is_connected = value

    async def auto_connect(self):
        """Try to auto-detect and connect to a Meshtastic device.

        Connection priority:
        1. Environment variable MESHTASTIC_SERIAL_PORT (exact port)
        2. /dev/ttyACM0 (known T-LoRa Pager port)
        3. Auto-detect by VID:PID scan
        4. TCP host if MESHTASTIC_TCP_HOST is set
        5. MQTT broker if MESHTASTIC_MQTT_HOST is set
        6. BLE if MESHTASTIC_BLE_ADDRESS is set
        7. Graceful disconnected mode if all fail

        Uses a two-phase strategy for serial: try fast connect first (noNodes,
        shorter timeout), then retry with full config exchange on failure.
        """
        # Try USB serial first — fast connect, then config is read after
        port = self._find_serial_device()
        if port:
            try:
                await self.connect_serial(
                    port, timeout=DEFAULT_SERIAL_TIMEOUT, retries=1, noNodes=True,
                )
                if self.is_connected:
                    # localConfig should be populated from config exchange
                    # even with noNodes=True (noNodes skips nodedb, not config)
                    return
            except Exception as e:
                log.warning(f"Serial connect to {port} failed: {e}")

        # Try known port /dev/ttyACM0 as fallback (T-LoRa Pager default)
        if not self.is_connected:
            fallback_port = "/dev/ttyACM0"
            if Path(fallback_port).exists() and port != fallback_port:
                try:
                    await self.connect_serial(
                        fallback_port, timeout=DEFAULT_SERIAL_TIMEOUT, retries=1,
                    )
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

        # Try MQTT if configured
        mqtt_host = os.environ.get("MESHTASTIC_MQTT_HOST")
        if mqtt_host and not self.is_connected:
            try:
                mqtt_topic = os.environ.get("MESHTASTIC_MQTT_TOPIC", "msh/US/2/e/#")
                mqtt_user = os.environ.get("MESHTASTIC_MQTT_USER", "meshdev")
                mqtt_pass = os.environ.get("MESHTASTIC_MQTT_PASSWORD", "large4cats")
                await self.connect_mqtt(
                    mqtt_host, topic=mqtt_topic,
                    username=mqtt_user, password=mqtt_pass,
                )
                if self.is_connected:
                    return
            except Exception as e:
                log.warning(f"MQTT connect to {mqtt_host} failed: {e}")

        # Try BLE if configured
        ble_addr = os.environ.get("MESHTASTIC_BLE_ADDRESS")
        if ble_addr and not self.is_connected:
            try:
                await self.connect_ble(ble_addr)
                if self.is_connected:
                    return
            except Exception as e:
                log.warning(f"BLE connect to {ble_addr} failed: {e}")

        log.info("No Meshtastic device found — running in disconnected mode (connect later via API)")

    async def connect_serial(
        self,
        port: str,
        timeout: float = DEFAULT_SERIAL_TIMEOUT,
        retries: int = 1,
        noNodes: bool = False,
    ):
        """Connect via USB serial port.

        Args:
            port: Serial device path (e.g. /dev/ttyACM0).
            timeout: Max wall-clock seconds for the entire connect+config
                     exchange.  The meshtastic library's SerialInterface
                     ``timeout`` kwarg sets ``connectTimeout`` (the serial
                     port open), NOT the config wait.  We rely on
                     ``asyncio.wait_for`` to enforce the real deadline.
            retries: Number of retry attempts after a failure (with 2s delay).
            noNodes: If True, pass ``noNodes=True`` to SerialInterface so it
                     skips waiting for the full node list.  This makes the
                     initial connect much faster on busy meshes — you can
                     request nodes later via ``get_nodes()``.
        """
        if not Path(port).exists():
            log.warning(f"Serial port {port} does not exist")
            self.is_connected = False
            return

        # If already connected to this port, return early
        if self.interface is not None and self.port == port:
            log.info(f"Already connected to {port}")
            self.is_connected = True
            return

        for attempt in range(1 + retries):
            try:
                import meshtastic.serial_interface
                log.info(
                    f"Connecting to Meshtastic on {port} "
                    f"(attempt {attempt + 1}, timeout {timeout}s, "
                    f"noNodes={noNodes})..."
                )

                # Disconnect any existing interface first
                self._close_interface()

                loop = asyncio.get_event_loop()

                # The SerialInterface ``timeout`` kwarg maps to
                # ``connectTimeout`` — the time to open the serial port
                # and get a basic response.  It does NOT control
                # ``_waitConnected`` (config exchange).  We set a
                # generous connect timeout and let asyncio.wait_for
                # enforce the outer wall-clock deadline.
                connect_timeout = min(int(timeout), 30)

                def _connect():
                    return meshtastic.serial_interface.SerialInterface(
                        port,
                        debugOut=None,
                        noProto=False,
                        noNodes=noNodes,
                        timeout=connect_timeout,
                    )

                self.interface = await asyncio.wait_for(
                    loop.run_in_executor(None, _connect),
                    timeout=timeout,
                )
                self.is_connected = True
                self.transport_type = "serial"
                self.port = port
                try:
                    self._read_device_info()
                except Exception as info_err:
                    log.warning(f"Device info read failed (connection still OK): {info_err}")
                log.info(f"Connected to {self.device_info.get('long_name', port)} via serial, is_connected={self.is_connected}")
                if self.event_bus:
                    self.event_bus.publish("meshtastic:connected", {
                        "transport": "serial", "port": port, "device": self.device_info,
                    })
                log.info(f"connect_serial returning, is_connected={self.is_connected}")
                return  # success
            except asyncio.TimeoutError:
                log.warning(f"Serial connection to {port} timed out after {timeout}s (attempt {attempt + 1})")
                self._close_interface()
                self.is_connected = False
            except ImportError as ie:
                log.error(f"meshtastic import failed: {ie}")
                self.is_connected = False
                return  # no point retrying
            except Exception as e:
                log.warning(f"Serial connection failed on {port}: {type(e).__name__}: {e} (attempt {attempt + 1})")
                import traceback
                log.debug(traceback.format_exc())
                self._close_interface()
                self.is_connected = False

            # Retry delay (only if we have retries left)
            if attempt < retries:
                log.info("Retrying serial connection in 2s...")
                await asyncio.sleep(2)

    async def connect_tcp(self, host: str, port: int = 4403, timeout: float = DEFAULT_TCP_TIMEOUT):
        """Connect via WiFi/TCP."""
        try:
            import meshtastic.tcp_interface
            log.info(f"Connecting to Meshtastic on {host}:{port} (timeout {timeout}s)...")

            self._close_interface()

            loop = asyncio.get_event_loop()
            connect_timeout = min(int(timeout), 30)

            def _connect():
                return meshtastic.tcp_interface.TCPInterface(
                    host, portNumber=port, noProto=False,
                    timeout=connect_timeout,
                )

            self.interface = await asyncio.wait_for(
                loop.run_in_executor(None, _connect),
                timeout=timeout,
            )
            self.is_connected = True
            self.transport_type = "tcp"
            self.port = f"{host}:{port}"
            self._read_device_info()
            log.info(f"Connected to {self.device_info.get('long_name', host)} via TCP")
            if self.event_bus:
                self.event_bus.publish("meshtastic:connected", {
                    "transport": "tcp", "port": self.port, "device": self.device_info,
                })
        except asyncio.TimeoutError:
            log.warning(f"TCP connection to {host}:{port} timed out after {timeout}s")
            self._close_interface()
            self.is_connected = False
        except ImportError:
            log.warning("meshtastic package not installed — pip install meshtastic")
            self.is_connected = False
        except Exception as e:
            log.warning(f"TCP connection failed: {e}")
            self._close_interface()
            self.is_connected = False

    async def connect_ble(
        self,
        address: str = "",
        timeout: float = DEFAULT_BLE_TIMEOUT,
        noNodes: bool = False,
    ):
        """Connect via Bluetooth Low Energy.

        Args:
            address: BLE device address (e.g. "AA:BB:CC:DD:EE:FF").
                     If empty, the meshtastic library will scan and pick the
                     first device it finds.
            timeout: Max wall-clock seconds for BLE discovery + config exchange.
            noNodes: If True, skip waiting for full node list.
        """
        try:
            import meshtastic.ble_interface
        except ImportError:
            log.warning(
                "meshtastic BLE interface not available — "
                "pip install meshtastic[ble] (requires bleak)"
            )
            self.is_connected = False
            return

        try:
            log.info(
                f"Connecting to Meshtastic via BLE "
                f"(address={address or 'auto-discover'}, timeout={timeout}s)..."
            )
            self._close_interface()

            loop = asyncio.get_event_loop()

            def _connect():
                kwargs: dict[str, Any] = {
                    "noNodes": noNodes,
                }
                if address:
                    kwargs["address"] = address
                return meshtastic.ble_interface.BLEInterface(**kwargs)

            self.interface = await asyncio.wait_for(
                loop.run_in_executor(None, _connect),
                timeout=timeout,
            )
            self.is_connected = True
            self.transport_type = "ble"
            self.port = address or "auto"
            self._read_device_info()
            log.info(
                f"Connected to {self.device_info.get('long_name', address)} via BLE"
            )
            if self.event_bus:
                self.event_bus.publish("meshtastic:connected", {
                    "transport": "ble", "address": address, "device": self.device_info,
                })
        except asyncio.TimeoutError:
            log.warning(f"BLE connection timed out after {timeout}s")
            self._close_interface()
            self.is_connected = False
        except Exception as e:
            log.warning(f"BLE connection failed: {e}")
            self._close_interface()
            self.is_connected = False

    async def connect_mqtt(
        self,
        host: str = "mqtt.meshtastic.org",
        port: int = 1883,
        topic: str = "msh/US/2/e/#",
        username: str = "meshdev",
        password: str = "large4cats",
        timeout: float = DEFAULT_MQTT_TIMEOUT,
    ):
        """Connect to the Meshtastic MQTT broker.

        Many Meshtastic nodes uplink their packets to an MQTT broker.
        This transport receives mesh traffic without a local radio.

        Args:
            host: MQTT broker hostname.
            port: MQTT broker port.
            topic: MQTT topic filter for mesh packets.
            username: Broker username (Meshtastic public broker default).
            password: Broker password.
            timeout: Max seconds to establish the MQTT connection.
        """
        try:
            import meshtastic.mqtt_interface
        except ImportError:
            log.warning(
                "meshtastic MQTT interface not available — "
                "pip install meshtastic (>=2.3.0 for MQTTInterface)"
            )
            self.is_connected = False
            return

        try:
            log.info(f"Connecting to Meshtastic via MQTT {host}:{port} topic={topic}...")
            self._close_interface()

            loop = asyncio.get_event_loop()

            def _connect():
                return meshtastic.mqtt_interface.MQTTInterface(
                    hostname=host,
                    port=port,
                    root_topic=topic,
                    username=username,
                    password=password,
                )

            self.interface = await asyncio.wait_for(
                loop.run_in_executor(None, _connect),
                timeout=timeout,
            )
            self.is_connected = True
            self.transport_type = "mqtt"
            self.port = f"{host}:{port}"
            # MQTT interface does not always expose local node info;
            # populate what we can.
            self.device_info = {
                "node_id": "",
                "long_name": f"MQTT ({host})",
                "short_name": "MQTT",
                "hw_model": "",
                "mac": "",
                "mqtt_topic": topic,
            }
            log.info(f"Connected to Meshtastic MQTT broker at {host}:{port}")
            if self.event_bus:
                self.event_bus.publish("meshtastic:connected", {
                    "transport": "mqtt",
                    "host": host,
                    "port": port,
                    "topic": topic,
                    "device": self.device_info,
                })
        except asyncio.TimeoutError:
            log.warning(f"MQTT connection to {host}:{port} timed out after {timeout}s")
            self._close_interface()
            self.is_connected = False
        except Exception as e:
            log.warning(f"MQTT connection failed: {e}")
            self._close_interface()
            self.is_connected = False

    async def disconnect(self):
        """Disconnect from the current device."""
        self._close_interface()
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_interface(self):
        """Safely close the current interface, if any."""
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass
            self.interface = None

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
            # Read cached metadata only — do NOT call getMetadata() as it blocks
            metadata = getattr(self.interface, 'metadata', None)
            if metadata:
                self.device_info["firmware"] = getattr(metadata, 'firmware_version', '')
                self.device_info["has_wifi"] = getattr(metadata, 'has_wifi', False)
                self.device_info["has_bluetooth"] = getattr(metadata, 'has_bluetooth', False)
                self.device_info["role"] = getattr(metadata, 'role', '')

            # Read radio config from localConfig (already cached, no blocking)
            try:
                lc = self.interface.localConfig
                if lc:
                    lora = getattr(lc, 'lora', None)
                    if lora:
                        # Convert protobuf enum ints to human-readable names
                        region_val = getattr(lora, 'region', 0)
                        modem_val = getattr(lora, 'modem_preset', 0)
                        try:
                            from meshtastic.protobuf.config_pb2 import Config
                            self.device_info['region'] = Config.LoRaConfig.RegionCode.Name(region_val)
                        except (ImportError, ValueError):
                            self.device_info['region'] = str(region_val)
                        try:
                            from meshtastic.protobuf.config_pb2 import Config
                            self.device_info['modem_preset'] = Config.LoRaConfig.ModemPreset.Name(modem_val)
                        except (ImportError, ValueError):
                            self.device_info['modem_preset'] = str(modem_val)
                        self.device_info['tx_power'] = getattr(lora, 'tx_power', 0)
                        self.device_info['hop_limit'] = getattr(lora, 'hop_limit', 0)
            except Exception:
                pass
        except Exception as e:
            log.warning(f"Failed to read device info: {e}")
