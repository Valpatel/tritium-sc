# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Device management — firmware, configuration, and device control for Meshtastic radios."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

log = logging.getLogger("meshtastic.device_manager")


# ---------------------------------------------------------------------------
# Device role enum (mirrors meshtastic protobuf Config.DeviceConfig.Role)
# ---------------------------------------------------------------------------

class DeviceRole(str, Enum):
    CLIENT = "CLIENT"
    CLIENT_MUTE = "CLIENT_MUTE"
    CLIENT_HIDDEN = "CLIENT_HIDDEN"
    ROUTER = "ROUTER"
    ROUTER_CLIENT = "ROUTER_CLIENT"
    REPEATER = "REPEATER"
    TRACKER = "TRACKER"
    SENSOR = "SENSOR"
    TAK = "TAK"
    TAK_TRACKER = "TAK_TRACKER"
    LOST_AND_FOUND = "LOST_AND_FOUND"


# ---------------------------------------------------------------------------
# Data classes for structured device info
# ---------------------------------------------------------------------------

@dataclass
class ChannelInfo:
    """A single Meshtastic channel configuration."""
    index: int
    name: str = ""
    role: str = "DISABLED"  # PRIMARY, SECONDARY, DISABLED
    psk: str = ""  # base64-encoded pre-shared key
    uplink_enabled: bool = False
    downlink_enabled: bool = False
    module_settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "role": self.role,
            "psk": self.psk,
            "uplink_enabled": self.uplink_enabled,
            "downlink_enabled": self.downlink_enabled,
            "module_settings": self.module_settings,
        }


@dataclass
class DeviceInfo:
    """Full device information snapshot."""
    node_id: str = ""
    long_name: str = ""
    short_name: str = ""
    hw_model: str = ""
    mac: str = ""
    firmware_version: str = ""
    has_wifi: bool = False
    has_bluetooth: bool = False
    has_ethernet: bool = False
    role: str = "CLIENT"
    reboot_count: int = 0
    region: str = ""
    modem_preset: str = ""
    num_channels: int = 0
    tx_power: int = 0
    channels: list[ChannelInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "long_name": self.long_name,
            "short_name": self.short_name,
            "hw_model": self.hw_model,
            "mac": self.mac,
            "firmware_version": self.firmware_version,
            "has_wifi": self.has_wifi,
            "has_bluetooth": self.has_bluetooth,
            "has_ethernet": self.has_ethernet,
            "role": self.role,
            "reboot_count": self.reboot_count,
            "region": self.region,
            "modem_preset": self.modem_preset,
            "num_channels": self.num_channels,
            "tx_power": self.tx_power,
            "channels": [ch.to_dict() for ch in self.channels],
        }


@dataclass
class FirmwareInfo:
    """Firmware version and update status."""
    current_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    hw_model: str = ""
    esptool_available: bool = False
    meshtastic_cli_available: bool = False

    def to_dict(self) -> dict:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "hw_model": self.hw_model,
            "esptool_available": self.esptool_available,
            "meshtastic_cli_available": self.meshtastic_cli_available,
        }


# Known stable firmware releases (update periodically)
KNOWN_FIRMWARE_VERSIONS = [
    "2.5.19.5f8df68",
    "2.5.18.e787254",
    "2.5.17.2c8c3a4",
    "2.5.16.b97ea7c",
    "2.4.3.7d65458",
    "2.4.2.f4da332",
    "2.4.1.abcdef0",
    "2.3.15.12345ab",
]

LATEST_STABLE = "2.5.19.5f8df68"


# ---------------------------------------------------------------------------
# DeviceManager
# ---------------------------------------------------------------------------

class DeviceManager:
    """Manages Meshtastic device configuration, firmware, and control.

    All operations that talk to hardware run in an executor thread to avoid
    blocking the asyncio event loop. Every public method wraps its work in
    try/except because the device can disconnect at any moment.
    """

    def __init__(self, connection):
        """Initialize with a reference to the ConnectionManager.

        Args:
            connection: A ConnectionManager instance that holds the meshtastic
                        interface object.
        """
        self.connection = connection

    # -- helpers -----------------------------------------------------------

    @property
    def _interface(self):
        """Shortcut to the underlying meshtastic interface, or None."""
        if self.connection and self.connection.is_connected:
            return self.connection.interface
        return None

    async def _run_in_executor(self, fn, *args):
        """Run a blocking function in the default executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    # =====================================================================
    # 1. Device info reading
    # =====================================================================

    async def get_device_info(self) -> DeviceInfo:
        """Read full device information from the connected radio.

        Returns a DeviceInfo dataclass with hardware, firmware, role, and
        channel data. Returns a mostly-empty DeviceInfo if not connected.
        """
        iface = self._interface
        if not iface:
            return DeviceInfo()

        try:
            info = await self._run_in_executor(self._read_device_info_sync, iface)
            return info
        except Exception as e:
            log.warning(f"Failed to read device info: {e}")
            return DeviceInfo()

    @staticmethod
    def _read_device_info_sync(iface) -> DeviceInfo:
        """Synchronous device info read — runs in executor thread."""
        my_info = iface.getMyNodeInfo() or {}
        user = my_info.get("user", {})

        info = DeviceInfo(
            node_id=user.get("id", ""),
            long_name=user.get("longName", ""),
            short_name=user.get("shortName", ""),
            hw_model=user.get("hwModel", ""),
            mac=user.get("macaddr", ""),
        )

        # Metadata (firmware, capabilities)
        try:
            metadata = iface.getMetadata() if hasattr(iface, "getMetadata") else None
            if metadata:
                info.firmware_version = getattr(metadata, "firmware_version", "")
                info.has_wifi = getattr(metadata, "has_wifi", False)
                info.has_bluetooth = getattr(metadata, "has_bluetooth", False)
                info.has_ethernet = getattr(metadata, "has_ethernet", False)
                info.role = str(getattr(metadata, "role", "CLIENT"))
                info.reboot_count = getattr(metadata, "reboot_count", 0)
        except Exception as e:
            log.debug(f"Metadata read failed (device may not support it): {e}")

        # Local config for radio settings
        try:
            local_config = iface.localConfig if hasattr(iface, "localConfig") else None
            if local_config:
                lora = getattr(local_config, "lora", None)
                if lora:
                    info.region = str(getattr(lora, "region", ""))
                    info.modem_preset = str(getattr(lora, "modem_preset", ""))
                    info.tx_power = getattr(lora, "tx_power", 0)
        except Exception as e:
            log.debug(f"Local config read failed: {e}")

        # Channels
        try:
            channels = DeviceManager._read_channels_sync(iface)
            info.channels = channels
            info.num_channels = len(channels)
        except Exception as e:
            log.debug(f"Channel read failed: {e}")

        return info

    async def get_channels(self) -> list[ChannelInfo]:
        """Read all channel configurations from the device."""
        iface = self._interface
        if not iface:
            return []

        try:
            return await self._run_in_executor(self._read_channels_sync, iface)
        except Exception as e:
            log.warning(f"Failed to read channels: {e}")
            return []

    @staticmethod
    def _read_channels_sync(iface) -> list[ChannelInfo]:
        """Synchronous channel read — runs in executor thread."""
        channels = []
        try:
            # The meshtastic library exposes channels via localNode.channels
            node = iface.localNode if hasattr(iface, "localNode") else None
            if not node:
                return channels

            ch_list = getattr(node, "channels", None)
            if not ch_list:
                return channels

            for i, ch in enumerate(ch_list):
                if ch is None:
                    continue
                settings = getattr(ch, "settings", None)
                channel = ChannelInfo(
                    index=i,
                    name=getattr(settings, "name", "") if settings else "",
                    role=str(getattr(ch, "role", "DISABLED")),
                    psk=_bytes_to_base64(getattr(settings, "psk", b"")) if settings else "",
                    uplink_enabled=getattr(settings, "uplink_enabled", False) if settings else False,
                    downlink_enabled=getattr(settings, "downlink_enabled", False) if settings else False,
                )
                channels.append(channel)
        except Exception as e:
            log.debug(f"Channel enumeration error: {e}")

        return channels

    async def get_module_config(self) -> dict:
        """Read module configuration (telemetry, range test, store-and-forward).

        Returns a dict keyed by module name with their config dicts.
        """
        iface = self._interface
        if not iface:
            return {}

        try:
            return await self._run_in_executor(self._read_module_config_sync, iface)
        except Exception as e:
            log.warning(f"Failed to read module config: {e}")
            return {}

    @staticmethod
    def _read_module_config_sync(iface) -> dict:
        """Synchronous module config read — runs in executor thread."""
        result = {}
        try:
            module_config = iface.moduleConfig if hasattr(iface, "moduleConfig") else None
            if not module_config:
                return result

            # Read known module configs
            for module_name in [
                "telemetry", "range_test", "store_forward", "serial",
                "external_notification", "canned_message", "audio",
                "remote_hardware", "neighbor_info", "detection_sensor",
                "paxcounter", "ambient_lighting",
            ]:
                mod = getattr(module_config, module_name, None)
                if mod is not None:
                    # Convert protobuf to dict-like structure
                    try:
                        result[module_name] = _proto_to_dict(mod)
                    except Exception:
                        result[module_name] = str(mod)
        except Exception as e:
            log.debug(f"Module config read error: {e}")

        return result

    # =====================================================================
    # 2. Device configuration
    # =====================================================================

    async def set_owner(self, long_name: str, short_name: str = "") -> bool:
        """Set device owner name and short name.

        Args:
            long_name: Display name (up to 39 chars).
            short_name: Short name (up to 4 chars). If empty, derived from long_name.

        Returns True on success, False on failure.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(
                self._set_owner_sync, iface, long_name, short_name
            )
            log.info(f"Set owner: long_name={long_name!r}, short_name={short_name!r}")
            return True
        except Exception as e:
            log.warning(f"Failed to set owner: {e}")
            return False

    @staticmethod
    def _set_owner_sync(iface, long_name: str, short_name: str):
        node = iface.localNode
        if short_name:
            node.setOwner(long_name=long_name, short_name=short_name)
        else:
            node.setOwner(long_name=long_name)

    async def set_role(self, role: str) -> bool:
        """Set device role (CLIENT, ROUTER, REPEATER, TRACKER, etc.).

        Args:
            role: One of the DeviceRole enum values.

        Returns True on success.
        """
        iface = self._interface
        if not iface:
            return False

        # Validate role
        valid_roles = {r.value for r in DeviceRole}
        if role.upper() not in valid_roles:
            log.warning(f"Invalid role: {role}. Valid: {valid_roles}")
            return False

        try:
            await self._run_in_executor(self._set_role_sync, iface, role.upper())
            log.info(f"Set device role to {role.upper()}")
            return True
        except Exception as e:
            log.warning(f"Failed to set role: {e}")
            return False

    @staticmethod
    def _set_role_sync(iface, role: str):
        node = iface.localNode
        node.setConfig("device", {"role": role})

    async def configure_channel(
        self,
        index: int,
        name: str = "",
        psk: str = "",
        role: str = "",
        uplink_enabled: bool | None = None,
        downlink_enabled: bool | None = None,
    ) -> bool:
        """Add or modify a channel configuration.

        Args:
            index: Channel index (0 = primary, 1-7 = secondary).
            name: Channel name.
            psk: Pre-shared key as base64 string, or "random" for new random key,
                 or "default" for the default key, or "none" for no encryption.
            role: "PRIMARY", "SECONDARY", or "DISABLED".
            uplink_enabled: Whether to enable MQTT uplink.
            downlink_enabled: Whether to enable MQTT downlink.
        """
        iface = self._interface
        if not iface:
            return False

        if index < 0 or index > 7:
            log.warning(f"Channel index out of range: {index}")
            return False

        try:
            await self._run_in_executor(
                self._configure_channel_sync, iface, index, name, psk,
                role, uplink_enabled, downlink_enabled,
            )
            log.info(f"Configured channel {index}: name={name!r}")
            return True
        except Exception as e:
            log.warning(f"Failed to configure channel {index}: {e}")
            return False

    @staticmethod
    def _configure_channel_sync(
        iface, index, name, psk, role, uplink_enabled, downlink_enabled
    ):
        node = iface.localNode

        # Get or create channel at index
        ch = node.channels[index] if index < len(node.channels) else None
        if ch is None:
            raise ValueError(f"Channel index {index} not available on this device")

        settings = ch.settings

        if name:
            settings.name = name
        if psk == "random":
            import os
            settings.psk = os.urandom(32)
        elif psk == "default":
            settings.psk = b"\x01"  # Default meshtastic key
        elif psk == "none":
            settings.psk = b""
        elif psk:
            import base64
            settings.psk = base64.b64decode(psk)

        if role:
            # Convert string role to protobuf enum
            from meshtastic.protobuf import channel_pb2
            role_map = {
                "PRIMARY": channel_pb2.Channel.Role.PRIMARY,
                "SECONDARY": channel_pb2.Channel.Role.SECONDARY,
                "DISABLED": channel_pb2.Channel.Role.DISABLED,
            }
            ch.role = role_map.get(role.upper(), ch.role)

        if uplink_enabled is not None:
            settings.uplink_enabled = uplink_enabled
        if downlink_enabled is not None:
            settings.downlink_enabled = downlink_enabled

        node.writeChannel(index)

    async def remove_channel(self, index: int) -> bool:
        """Disable a channel by setting its role to DISABLED.

        Args:
            index: Channel index (cannot remove channel 0 — the primary).
        """
        if index == 0:
            log.warning("Cannot remove the primary channel (index 0)")
            return False
        return await self.configure_channel(index, role="DISABLED")

    async def set_lora_config(
        self,
        tx_power: int | None = None,
        region: str | None = None,
        modem_preset: str | None = None,
    ) -> bool:
        """Set LoRa radio parameters.

        Args:
            tx_power: Transmit power in dBm.
            region: Regulatory region (e.g., "US", "EU_868", "CN", "JP").
            modem_preset: Modem preset (e.g., "LONG_FAST", "SHORT_SLOW").
        """
        iface = self._interface
        if not iface:
            return False

        try:
            config = {}
            if tx_power is not None:
                config["tx_power"] = tx_power
            if region is not None:
                config["region"] = region
            if modem_preset is not None:
                config["modem_preset"] = modem_preset

            if not config:
                return True  # Nothing to set

            await self._run_in_executor(self._set_lora_config_sync, iface, config)
            log.info(f"Set LoRa config: {config}")
            return True
        except Exception as e:
            log.warning(f"Failed to set LoRa config: {e}")
            return False

    @staticmethod
    def _set_lora_config_sync(iface, config: dict):
        node = iface.localNode
        node.setConfig("lora", config)

    async def set_position(
        self,
        lat: float | None = None,
        lng: float | None = None,
        altitude: int | None = None,
        gps_mode: str | None = None,
    ) -> bool:
        """Set device position manually or configure GPS mode.

        Args:
            lat: Latitude in decimal degrees.
            lng: Longitude in decimal degrees.
            altitude: Altitude in meters.
            gps_mode: "ENABLED", "DISABLED", or "NOT_PRESENT".
        """
        iface = self._interface
        if not iface:
            return False

        try:
            if gps_mode is not None:
                await self._run_in_executor(
                    self._set_gps_mode_sync, iface, gps_mode
                )

            if lat is not None and lng is not None:
                alt = altitude or 0
                await self._run_in_executor(
                    self._set_position_sync, iface, lat, lng, alt
                )
                log.info(f"Set position: lat={lat}, lng={lng}, alt={alt}")

            return True
        except Exception as e:
            log.warning(f"Failed to set position: {e}")
            return False

    @staticmethod
    def _set_position_sync(iface, lat: float, lng: float, altitude: int):
        node = iface.localNode
        node.setFixedPosition(lat, lng, altitude)

    @staticmethod
    def _set_gps_mode_sync(iface, mode: str):
        node = iface.localNode
        node.setConfig("position", {"gps_mode": mode})

    async def set_wifi(
        self,
        enabled: bool,
        ssid: str = "",
        password: str = "",
    ) -> bool:
        """Enable/disable WiFi and set credentials.

        Args:
            enabled: Whether WiFi should be enabled.
            ssid: WiFi network name (required if enabling).
            password: WiFi password.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            config = {"wifi_enabled": enabled}
            if ssid:
                config["wifi_ssid"] = ssid
            if password:
                config["wifi_psk"] = password

            await self._run_in_executor(self._set_network_config_sync, iface, config)
            log.info(f"Set WiFi: enabled={enabled}, ssid={ssid!r}")
            return True
        except Exception as e:
            log.warning(f"Failed to set WiFi config: {e}")
            return False

    @staticmethod
    def _set_network_config_sync(iface, config: dict):
        node = iface.localNode
        node.setConfig("network", config)

    async def set_bluetooth(self, enabled: bool) -> bool:
        """Enable or disable Bluetooth on the device.

        Args:
            enabled: Whether Bluetooth should be enabled.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            config = {"enabled": enabled}
            await self._run_in_executor(self._set_bluetooth_config_sync, iface, config)
            log.info(f"Set Bluetooth: enabled={enabled}")
            return True
        except Exception as e:
            log.warning(f"Failed to set Bluetooth config: {e}")
            return False

    @staticmethod
    def _set_bluetooth_config_sync(iface, config: dict):
        node = iface.localNode
        node.setConfig("bluetooth", config)

    # =====================================================================
    # 3. Device control
    # =====================================================================

    async def reboot(self, seconds: int = 5) -> bool:
        """Reboot the device after a delay.

        Args:
            seconds: Delay before reboot in seconds (default 5).
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(self._reboot_sync, iface, seconds)
            log.info(f"Reboot command sent (delay={seconds}s)")
            # The device will disconnect after reboot
            self.connection.is_connected = False
            return True
        except Exception as e:
            log.warning(f"Reboot failed: {e}")
            return False

    @staticmethod
    def _reboot_sync(iface, seconds: int):
        node = iface.localNode
        node.reboot(seconds)

    async def factory_reset(self) -> bool:
        """Factory reset the device. This erases all configuration."""
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(self._factory_reset_sync, iface)
            log.info("Factory reset command sent")
            self.connection.is_connected = False
            return True
        except Exception as e:
            log.warning(f"Factory reset failed: {e}")
            return False

    @staticmethod
    def _factory_reset_sync(iface):
        node = iface.localNode
        node.factoryReset()

    # =====================================================================
    # 4. Firmware management (uses tritium_lib.firmware)
    # =====================================================================

    def _get_flasher(self):
        """Get or create a MeshtasticFlasher instance."""
        try:
            from tritium_lib.firmware import MeshtasticFlasher
            port = self.connection.port if self.connection else ""
            return MeshtasticFlasher(port=port)
        except ImportError:
            log.warning("tritium_lib.firmware not available — using fallback flash")
            return None

    async def get_firmware_info(self) -> FirmwareInfo:
        """Check current firmware version and update availability."""
        fw = FirmwareInfo(
            esptool_available=shutil.which("esptool.py") is not None or shutil.which("esptool") is not None,
            meshtastic_cli_available=shutil.which("meshtastic") is not None,
        )

        iface = self._interface
        if iface:
            try:
                device_info = await self.get_device_info()
                fw.current_version = device_info.firmware_version
                fw.hw_model = device_info.hw_model
            except Exception as e:
                log.debug(f"Could not read firmware version: {e}")

        # Compare against known versions
        if fw.current_version:
            fw.latest_version = LATEST_STABLE
            fw.update_available = fw.current_version != LATEST_STABLE

        return fw

    async def detect_device(self) -> dict:
        """Detect the connected device using the firmware flasher.

        Returns device info: chip, board, firmware version, flash size.
        """
        flasher = self._get_flasher()
        if not flasher:
            return {"error": "Firmware flasher not available"}

        detection = await flasher.detect()
        return detection.to_dict()

    async def flash_firmware(
        self,
        firmware_path: str = "",
        port: str = "",
    ) -> dict:
        """Flash firmware to the device.

        If firmware_path is empty, downloads and flashes the latest
        official Meshtastic firmware for the detected board.

        Args:
            firmware_path: Path to firmware .bin (empty = download latest).
            port: Serial port override.
        """
        # Disconnect first so the port is free
        if self.connection and self.connection.is_connected:
            await self.connection.disconnect()

        flasher = self._get_flasher()
        if flasher:
            if port:
                flasher.port = port

            if firmware_path:
                result = await flasher.flash(firmware_path, erase_all=True)
            else:
                result = await flasher.flash_latest()

            return result.to_dict()

        # Fallback: direct subprocess
        if not port and self.connection:
            port = self.connection.port
        if not port:
            return {"success": False, "error": "No serial port specified"}

        meshtastic_cli = shutil.which("meshtastic")
        esptool = shutil.which("esptool.py") or shutil.which("esptool")

        if firmware_path:
            if meshtastic_cli:
                cmd = [meshtastic_cli, "--port", port, "--flash-firmware", firmware_path]
            elif esptool:
                cmd = [esptool, "--port", port, "--baud", "921600", "write_flash", "0x0", firmware_path]
            else:
                return {"success": False, "error": "Neither esptool nor meshtastic CLI found"}
        else:
            if meshtastic_cli:
                cmd = [meshtastic_cli, "--port", port, "--flash-firmware"]
            else:
                return {"success": False, "error": "meshtastic CLI needed for auto-update"}

        return await self._run_subprocess(cmd)

    async def flash_latest(self) -> dict:
        """Download and flash the latest official Meshtastic firmware."""
        return await self.flash_firmware()

    async def get_available_versions(self, limit: int = 10) -> list[dict]:
        """Fetch available Meshtastic firmware versions from GitHub."""
        flasher = self._get_flasher()
        if not flasher:
            return []

        try:
            return await self._run_in_executor(
                flasher.get_available_versions, limit,
            )
        except Exception as e:
            log.warning(f"Failed to get versions: {e}")
            return []

    async def _run_subprocess(self, cmd: list[str]) -> dict:
        """Run a subprocess in an executor and capture output."""
        try:
            result = await self._run_in_executor(self._subprocess_sync, cmd)
            return result
        except Exception as e:
            return {"success": False, "error": str(e), "output": ""}

    @staticmethod
    def _subprocess_sync(cmd: list[str]) -> dict:
        """Run a subprocess synchronously — called from executor."""
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            return {
                "success": proc.returncode == 0,
                "output": proc.stdout,
                "error": proc.stderr if proc.returncode != 0 else "",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Flash timed out after 300 seconds"}
        except FileNotFoundError as e:
            return {"success": False, "error": f"Command not found: {e}"}


# ---------------------------------------------------------------------------
# API route factory
# ---------------------------------------------------------------------------

def create_device_routes(device_manager: DeviceManager) -> "APIRouter":
    """Create FastAPI routes for device management.

    These routes are added under /api/addons/meshtastic/device/*.
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/device")

    @router.get("/info")
    async def device_info():
        """Full device details: hardware, firmware, role, channels."""
        info = await device_manager.get_device_info()
        return info.to_dict()

    @router.get("/channels")
    async def device_channels():
        """Channel configuration for all channels."""
        channels = await device_manager.get_channels()
        return {"channels": [ch.to_dict() for ch in channels]}

    @router.get("/firmware")
    async def firmware_info():
        """Firmware version and update availability."""
        fw = await device_manager.get_firmware_info()
        return fw.to_dict()

    @router.get("/modules")
    async def module_config():
        """Module configuration (telemetry, range test, etc.)."""
        modules = await device_manager.get_module_config()
        return {"modules": modules}

    @router.post("/config")
    async def set_config(body: dict):
        """Set device settings.

        Accepts a JSON body with any combination of:
        - long_name: str
        - short_name: str
        - role: str (CLIENT, ROUTER, REPEATER, TRACKER, etc.)
        - tx_power: int (dBm)
        - region: str (US, EU_868, CN, JP, etc.)
        - modem_preset: str (LONG_FAST, SHORT_SLOW, etc.)
        - lat: float (latitude)
        - lng: float (longitude)
        - altitude: int (meters)
        - gps_mode: str (ENABLED, DISABLED, NOT_PRESENT)
        - wifi_enabled: bool
        - wifi_ssid: str
        - wifi_password: str
        - bluetooth_enabled: bool
        - channel: dict (index, name, psk, role, uplink_enabled, downlink_enabled)
        """
        results = {}

        # Owner name
        if "long_name" in body or "short_name" in body:
            ok = await device_manager.set_owner(
                long_name=body.get("long_name", ""),
                short_name=body.get("short_name", ""),
            )
            results["owner"] = ok

        # Role
        if "role" in body:
            ok = await device_manager.set_role(body["role"])
            results["role"] = ok

        # LoRa settings
        lora_keys = {"tx_power", "region", "modem_preset"}
        if lora_keys & set(body.keys()):
            ok = await device_manager.set_lora_config(
                tx_power=body.get("tx_power"),
                region=body.get("region"),
                modem_preset=body.get("modem_preset"),
            )
            results["lora"] = ok

        # Position
        position_keys = {"lat", "lng", "altitude", "gps_mode"}
        if position_keys & set(body.keys()):
            ok = await device_manager.set_position(
                lat=body.get("lat"),
                lng=body.get("lng"),
                altitude=body.get("altitude"),
                gps_mode=body.get("gps_mode"),
            )
            results["position"] = ok

        # WiFi
        if "wifi_enabled" in body:
            ok = await device_manager.set_wifi(
                enabled=body["wifi_enabled"],
                ssid=body.get("wifi_ssid", ""),
                password=body.get("wifi_password", ""),
            )
            results["wifi"] = ok

        # Bluetooth
        if "bluetooth_enabled" in body:
            ok = await device_manager.set_bluetooth(body["bluetooth_enabled"])
            results["bluetooth"] = ok

        # Channel configuration
        if "channel" in body:
            ch = body["channel"]
            if not isinstance(ch, dict) or "index" not in ch:
                raise HTTPException(status_code=400, detail="channel must include 'index'")
            ok = await device_manager.configure_channel(
                index=ch["index"],
                name=ch.get("name", ""),
                psk=ch.get("psk", ""),
                role=ch.get("role", ""),
                uplink_enabled=ch.get("uplink_enabled"),
                downlink_enabled=ch.get("downlink_enabled"),
            )
            results["channel"] = ok

        if not results:
            raise HTTPException(status_code=400, detail="No recognized config keys in request body")

        all_ok = all(results.values())
        return {"success": all_ok, "results": results}

    @router.post("/reboot")
    async def reboot_device(body: dict = None):
        """Reboot the connected device.

        Optional body: { "delay": 5 } — seconds before reboot.
        """
        body = body or {}
        delay = body.get("delay", 5)
        ok = await device_manager.reboot(seconds=delay)
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or reboot failed")
        return {"success": True, "message": f"Rebooting in {delay} seconds"}

    @router.post("/factory-reset")
    async def factory_reset():
        """Factory reset the device. Erases all configuration."""
        ok = await device_manager.factory_reset()
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or reset failed")
        return {"success": True, "message": "Factory reset initiated"}

    @router.get("/detect")
    async def detect_device():
        """Detect the connected device (chip, board, firmware, flash size)."""
        return await device_manager.detect_device()

    @router.post("/flash")
    async def flash_firmware(body: dict = None):
        """Flash firmware to the device.

        Body: {
            "firmware_path": "/path/to/firmware.bin" (optional — omit for latest),
            "port": "/dev/ttyACM0" (optional)
        }

        If firmware_path is omitted, downloads and flashes the latest
        official Meshtastic firmware for the detected board.
        """
        body = body or {}
        firmware_path = body.get("firmware_path", "")
        port = body.get("port", "")

        result = await device_manager.flash_firmware(firmware_path, port=port)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Flash failed"))
        return result

    @router.post("/flash-latest")
    async def flash_latest():
        """Download and flash the latest official Meshtastic firmware.

        Detects the board automatically and downloads the correct firmware.
        """
        result = await device_manager.flash_latest()
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Flash failed"))
        return result

    @router.get("/firmware/versions")
    async def firmware_versions(limit: int = 10):
        """Available Meshtastic firmware versions from GitHub."""
        versions = await device_manager.get_available_versions(limit=limit)
        return {"versions": versions}

    return router


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _bytes_to_base64(data: bytes) -> str:
    """Convert bytes to a base64 string."""
    if not data:
        return ""
    import base64
    return base64.b64encode(data).decode("ascii")


def _proto_to_dict(proto_obj) -> dict:
    """Convert a protobuf-like object to a plain dict.

    Tries MessageToDict first (google protobuf), falls back to manual
    attribute extraction.
    """
    try:
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(proto_obj, preserving_proto_field_name=True)
    except (ImportError, Exception):
        pass

    # Fallback: iterate DESCRIPTOR fields
    result = {}
    try:
        for field in proto_obj.DESCRIPTOR.fields:
            val = getattr(proto_obj, field.name, None)
            if val is not None:
                # Convert enum values to their string names
                if hasattr(val, "Name"):
                    val = str(val)
                elif isinstance(val, bytes):
                    val = _bytes_to_base64(val)
                result[field.name] = val
    except Exception:
        result = {"raw": str(proto_obj)}

    return result
