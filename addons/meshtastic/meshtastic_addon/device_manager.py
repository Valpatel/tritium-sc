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
    ROUTER_LATE = "ROUTER_LATE"
    CLIENT_BASE = "CLIENT_BASE"


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
        from meshtastic.protobuf.config_pb2 import Config
        node = iface.localNode
        role_enum = Config.DeviceConfig.Role.Value(role)
        node.localConfig.device.role = role_enum
        node.writeConfig("device")

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
        from meshtastic.protobuf.config_pb2 import Config
        node = iface.localNode
        lora = node.localConfig.lora
        if "tx_power" in config:
            lora.tx_power = config["tx_power"]
        if "region" in config:
            lora.region = Config.LoRaConfig.RegionCode.Value(config["region"])
        if "modem_preset" in config:
            lora.modem_preset = Config.LoRaConfig.ModemPreset.Value(config["modem_preset"])
        node.writeConfig("lora")

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
        from meshtastic.protobuf.config_pb2 import Config
        node = iface.localNode
        node.localConfig.position.gps_mode = Config.PositionConfig.GpsMode.Value(mode)
        node.writeConfig("position")

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
        net = node.localConfig.network
        if "wifi_enabled" in config:
            net.wifi_enabled = config["wifi_enabled"]
        if "wifi_ssid" in config:
            net.wifi_ssid = config["wifi_ssid"]
        if "wifi_psk" in config:
            net.wifi_psk = config["wifi_psk"]
        node.writeConfig("network")

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
        bt = node.localConfig.bluetooth
        if "enabled" in config:
            bt.enabled = config["enabled"]
        node.writeConfig("bluetooth")

    async def set_display_config(
        self,
        screen_on_secs: int | None = None,
        gps_format: int | None = None,
        auto_screen_carousel_secs: int | None = None,
        flip_screen: bool | None = None,
        units: str | None = None,
    ) -> bool:
        """Set display configuration.

        Args:
            screen_on_secs: Screen timeout in seconds (0 = always on).
            gps_format: GPS coordinate format (deprecated, use 0).
            auto_screen_carousel_secs: Auto-rotate screens interval (0 = disabled).
            flip_screen: Flip the display upside down.
            units: Display units — "METRIC" or "IMPERIAL".
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(
                self._set_display_config_sync, iface,
                screen_on_secs, gps_format, auto_screen_carousel_secs,
                flip_screen, units,
            )
            log.info("Set display config")
            return True
        except Exception as e:
            log.warning(f"Failed to set display config: {e}")
            return False

    @staticmethod
    def _set_display_config_sync(
        iface, screen_on_secs, gps_format, auto_screen_carousel_secs,
        flip_screen, units,
    ):
        from meshtastic.protobuf.config_pb2 import Config
        node = iface.localNode
        display = node.localConfig.display
        if screen_on_secs is not None:
            display.screen_on_secs = screen_on_secs
        if gps_format is not None:
            display.gps_format = gps_format
        if auto_screen_carousel_secs is not None:
            display.auto_screen_carousel_secs = auto_screen_carousel_secs
        if flip_screen is not None:
            display.flip_screen = flip_screen
        if units is not None:
            display.units = Config.DisplayConfig.DisplayUnits.Value(units)
        node.writeConfig("display")

    async def set_power_config(
        self,
        is_power_saving: bool | None = None,
        on_battery_shutdown_after_secs: int | None = None,
    ) -> bool:
        """Set power configuration.

        Args:
            is_power_saving: Enable power saving mode.
            on_battery_shutdown_after_secs: Shutdown after N secs on battery (0 = disabled).
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(
                self._set_power_config_sync, iface,
                is_power_saving, on_battery_shutdown_after_secs,
            )
            log.info("Set power config")
            return True
        except Exception as e:
            log.warning(f"Failed to set power config: {e}")
            return False

    @staticmethod
    def _set_power_config_sync(iface, is_power_saving, on_battery_shutdown_after_secs):
        node = iface.localNode
        power = node.localConfig.power
        if is_power_saving is not None:
            power.is_power_saving = is_power_saving
        if on_battery_shutdown_after_secs is not None:
            power.on_battery_shutdown_after_secs = on_battery_shutdown_after_secs
        node.writeConfig("power")

    async def set_mqtt_config(
        self,
        enabled: bool | None = None,
        address: str | None = None,
        username: str | None = None,
        password: str | None = None,
        encryption_enabled: bool | None = None,
        json_enabled: bool | None = None,
    ) -> bool:
        """Set MQTT module configuration.

        Args:
            enabled: Enable MQTT.
            address: MQTT broker address (host:port).
            username: MQTT username.
            password: MQTT password.
            encryption_enabled: Enable payload encryption over MQTT.
            json_enabled: Publish JSON-encoded messages.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            config = {}
            if enabled is not None:
                config["enabled"] = enabled
            if address is not None:
                config["address"] = address
            if username is not None:
                config["username"] = username
            if password is not None:
                config["password"] = password
            if encryption_enabled is not None:
                config["encryption_enabled"] = encryption_enabled
            if json_enabled is not None:
                config["json_enabled"] = json_enabled

            if not config:
                return True

            await self._run_in_executor(self._set_mqtt_config_sync, iface, config)
            log.info(f"Set MQTT config: {config}")
            return True
        except Exception as e:
            log.warning(f"Failed to set MQTT config: {e}")
            return False

    @staticmethod
    def _set_mqtt_config_sync(iface, config: dict):
        node = iface.localNode
        mqtt = node.moduleConfig.mqtt
        for key, value in config.items():
            setattr(mqtt, key, value)
        node.writeConfig("mqtt")

    async def set_telemetry_config(
        self,
        device_update_interval: int | None = None,
        environment_measurement_enabled: bool | None = None,
        environment_update_interval: int | None = None,
    ) -> bool:
        """Set telemetry module configuration.

        Args:
            device_update_interval: Device metrics interval in seconds.
            environment_measurement_enabled: Enable environment sensors.
            environment_update_interval: Environment metrics interval in seconds.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            config = {}
            if device_update_interval is not None:
                config["device_update_interval"] = device_update_interval
            if environment_measurement_enabled is not None:
                config["environment_measurement_enabled"] = environment_measurement_enabled
            if environment_update_interval is not None:
                config["environment_update_interval"] = environment_update_interval

            if not config:
                return True

            await self._run_in_executor(self._set_telemetry_config_sync, iface, config)
            log.info(f"Set telemetry config: {config}")
            return True
        except Exception as e:
            log.warning(f"Failed to set telemetry config: {e}")
            return False

    @staticmethod
    def _set_telemetry_config_sync(iface, config: dict):
        node = iface.localNode
        tel = node.moduleConfig.telemetry
        for key, value in config.items():
            setattr(tel, key, value)
        node.writeConfig("telemetry")

    async def get_channel_url(self) -> str:
        """Get the shareable channel URL for this device.

        Returns:
            A meshtastic:// URL string, or empty string on failure.
        """
        iface = self._interface
        if not iface:
            return ""

        try:
            url = await self._run_in_executor(self._get_channel_url_sync, iface)
            return url
        except Exception as e:
            log.warning(f"Failed to get channel URL: {e}")
            return ""

    @staticmethod
    def _get_channel_url_sync(iface) -> str:
        node = iface.localNode
        return node.getURL()

    async def set_channel_url(self, url: str) -> bool:
        """Set channels from a shareable channel URL.

        Args:
            url: A meshtastic:// URL string.

        Returns True on success.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(self._set_channel_url_sync, iface, url)
            log.info(f"Set channel URL: {url[:40]}...")
            return True
        except Exception as e:
            log.warning(f"Failed to set channel URL: {e}")
            return False

    @staticmethod
    def _set_channel_url_sync(iface, url: str):
        node = iface.localNode
        node.setURL(url)

    async def shutdown(self) -> bool:
        """Gracefully power off the device.

        Returns True if the shutdown command was sent successfully.
        """
        iface = self._interface
        if not iface:
            return False

        try:
            await self._run_in_executor(self._shutdown_sync, iface)
            log.info("Shutdown command sent")
            self.connection.is_connected = False
            return True
        except Exception as e:
            log.warning(f"Shutdown failed: {e}")
            return False

    @staticmethod
    def _shutdown_sync(iface):
        node = iface.localNode
        node.shutdown()

    async def export_config(self) -> dict:
        """Export full device configuration as a serializable dict.

        Returns a dict with sections: device, lora, position, network,
        bluetooth, display, power, channels, and modules.
        """
        iface = self._interface
        if not iface:
            return {}

        try:
            return await self._run_in_executor(self._export_config_sync, iface)
        except Exception as e:
            log.warning(f"Failed to export config: {e}")
            return {}

    @staticmethod
    def _export_config_sync(iface) -> dict:
        result = {}
        node = iface.localNode

        # Local config sections
        local_config = iface.localConfig if hasattr(iface, "localConfig") else None
        if local_config:
            for section_name in ["device", "lora", "position", "network",
                                  "bluetooth", "display", "power"]:
                section = getattr(local_config, section_name, None)
                if section is not None:
                    try:
                        result[section_name] = _proto_to_dict(section)
                    except Exception:
                        result[section_name] = str(section)

        # Module config sections
        module_config = iface.moduleConfig if hasattr(iface, "moduleConfig") else None
        if module_config:
            modules = {}
            for module_name in ["mqtt", "telemetry", "serial", "range_test",
                                "store_forward", "external_notification",
                                "canned_message", "audio", "remote_hardware",
                                "neighbor_info", "detection_sensor",
                                "paxcounter", "ambient_lighting"]:
                mod = getattr(module_config, module_name, None)
                if mod is not None:
                    try:
                        modules[module_name] = _proto_to_dict(mod)
                    except Exception:
                        modules[module_name] = str(mod)
            result["modules"] = modules

        # Channels
        channels = DeviceManager._read_channels_sync(iface)
        result["channels"] = [ch.to_dict() for ch in channels]

        # Channel URL
        try:
            result["channel_url"] = node.getURL()
        except Exception:
            pass

        return result

    async def import_config(self, config: dict) -> dict:
        """Import device configuration from a dict (as exported by export_config).

        Applies config sections in order using transactions where possible.
        Returns a dict of section_name -> success boolean.

        Args:
            config: Dict with keys like "device", "lora", "network", etc.
        """
        iface = self._interface
        if not iface:
            return {}

        try:
            return await self._run_in_executor(self._import_config_sync, iface, config)
        except Exception as e:
            log.warning(f"Failed to import config: {e}")
            return {"error": str(e)}

    @staticmethod
    def _import_config_sync(iface, config: dict) -> dict:
        from meshtastic.protobuf.config_pb2 import Config
        node = iface.localNode
        results = {}

        node.beginSettingsTransaction()
        try:
            # Local config sections — set fields directly on localConfig
            section_map = {
                "device": node.localConfig.device,
                "lora": node.localConfig.lora,
                "position": node.localConfig.position,
                "network": node.localConfig.network,
                "bluetooth": node.localConfig.bluetooth,
                "display": node.localConfig.display,
                "power": node.localConfig.power,
            }

            for section_name, proto_obj in section_map.items():
                if section_name not in config:
                    continue
                try:
                    section_data = config[section_name]
                    if isinstance(section_data, dict):
                        for key, value in section_data.items():
                            if hasattr(proto_obj, key):
                                setattr(proto_obj, key, value)
                    node.writeConfig(section_name)
                    results[section_name] = True
                except Exception as e:
                    log.warning(f"Import {section_name} failed: {e}")
                    results[section_name] = False

            # Module configs
            if "modules" in config and isinstance(config["modules"], dict):
                for mod_name, mod_data in config["modules"].items():
                    try:
                        mod_obj = getattr(node.moduleConfig, mod_name, None)
                        if mod_obj and isinstance(mod_data, dict):
                            for key, value in mod_data.items():
                                if hasattr(mod_obj, key):
                                    setattr(mod_obj, key, value)
                            node.writeConfig(mod_name)
                            results[f"module.{mod_name}"] = True
                    except Exception as e:
                        log.warning(f"Import module {mod_name} failed: {e}")
                        results[f"module.{mod_name}"] = False

            # Channel URL (fastest way to restore channels)
            if "channel_url" in config:
                try:
                    node.setURL(config["channel_url"])
                    results["channels"] = True
                except Exception as e:
                    log.warning(f"Import channel URL failed: {e}")
                    results["channels"] = False

            node.commitSettingsTransaction()
        except Exception as e:
            log.warning(f"Settings transaction failed: {e}")
            results["transaction_error"] = str(e)

        return results

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

        # Display
        display_keys = {"screen_on_secs", "auto_screen_carousel_secs", "flip_screen", "display_units"}
        if display_keys & set(body.keys()):
            ok = await device_manager.set_display_config(
                screen_on_secs=body.get("screen_on_secs"),
                auto_screen_carousel_secs=body.get("auto_screen_carousel_secs"),
                flip_screen=body.get("flip_screen"),
                units=body.get("display_units"),
            )
            results["display"] = ok

        # Power
        power_keys = {"is_power_saving", "on_battery_shutdown_after_secs"}
        if power_keys & set(body.keys()):
            ok = await device_manager.set_power_config(
                is_power_saving=body.get("is_power_saving"),
                on_battery_shutdown_after_secs=body.get("on_battery_shutdown_after_secs"),
            )
            results["power"] = ok

        # MQTT module
        mqtt_keys = {"mqtt_enabled", "mqtt_address", "mqtt_username", "mqtt_password",
                      "mqtt_encryption_enabled", "mqtt_json_enabled"}
        if mqtt_keys & set(body.keys()):
            ok = await device_manager.set_mqtt_config(
                enabled=body.get("mqtt_enabled"),
                address=body.get("mqtt_address"),
                username=body.get("mqtt_username"),
                password=body.get("mqtt_password"),
                encryption_enabled=body.get("mqtt_encryption_enabled"),
                json_enabled=body.get("mqtt_json_enabled"),
            )
            results["mqtt"] = ok

        # Telemetry module
        telemetry_keys = {"telemetry_device_interval", "telemetry_env_enabled",
                           "telemetry_env_interval"}
        if telemetry_keys & set(body.keys()):
            ok = await device_manager.set_telemetry_config(
                device_update_interval=body.get("telemetry_device_interval"),
                environment_measurement_enabled=body.get("telemetry_env_enabled"),
                environment_update_interval=body.get("telemetry_env_interval"),
            )
            results["telemetry"] = ok

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

    @router.post("/display")
    async def set_display(body: dict):
        """Set display configuration.

        Body: { screen_on_secs, gps_format, auto_screen_carousel_secs,
                flip_screen, units }
        """
        ok = await device_manager.set_display_config(
            screen_on_secs=body.get("screen_on_secs"),
            gps_format=body.get("gps_format"),
            auto_screen_carousel_secs=body.get("auto_screen_carousel_secs"),
            flip_screen=body.get("flip_screen"),
            units=body.get("units"),
        )
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or display config failed")
        return {"success": True}

    @router.post("/power")
    async def set_power(body: dict):
        """Set power configuration.

        Body: { is_power_saving, on_battery_shutdown_after_secs }
        """
        ok = await device_manager.set_power_config(
            is_power_saving=body.get("is_power_saving"),
            on_battery_shutdown_after_secs=body.get("on_battery_shutdown_after_secs"),
        )
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or power config failed")
        return {"success": True}

    @router.post("/mqtt")
    async def set_mqtt(body: dict):
        """Set MQTT module configuration.

        Body: { enabled, address, username, password, encryption_enabled, json_enabled }
        """
        ok = await device_manager.set_mqtt_config(
            enabled=body.get("enabled"),
            address=body.get("address"),
            username=body.get("username"),
            password=body.get("password"),
            encryption_enabled=body.get("encryption_enabled"),
            json_enabled=body.get("json_enabled"),
        )
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or MQTT config failed")
        return {"success": True}

    @router.post("/telemetry")
    async def set_telemetry(body: dict):
        """Set telemetry module configuration.

        Body: { device_update_interval, environment_measurement_enabled,
                environment_update_interval }
        """
        ok = await device_manager.set_telemetry_config(
            device_update_interval=body.get("device_update_interval"),
            environment_measurement_enabled=body.get("environment_measurement_enabled"),
            environment_update_interval=body.get("environment_update_interval"),
        )
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or telemetry config failed")
        return {"success": True}

    @router.get("/channel-url")
    async def get_channel_url():
        """Get the shareable channel URL."""
        url = await device_manager.get_channel_url()
        return {"url": url}

    @router.post("/channel-url")
    async def set_channel_url(body: dict):
        """Set channels from a shareable channel URL.

        Body: { "url": "https://meshtastic.org/e/#..." }
        """
        url = body.get("url", "")
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        ok = await device_manager.set_channel_url(url)
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or set URL failed")
        return {"success": True}

    @router.post("/shutdown")
    async def shutdown_device():
        """Gracefully power off the device."""
        ok = await device_manager.shutdown()
        if not ok:
            raise HTTPException(status_code=503, detail="Device not connected or shutdown failed")
        return {"success": True, "message": "Shutdown command sent"}

    @router.get("/export")
    async def export_config():
        """Export full device configuration as JSON."""
        config = await device_manager.export_config()
        if not config:
            raise HTTPException(status_code=503, detail="Device not connected or export failed")
        return config

    @router.post("/import")
    async def import_config(body: dict):
        """Import device configuration from JSON (as exported by /export).

        Body: the full config dict from /export endpoint.
        """
        results = await device_manager.import_config(body)
        if not results:
            raise HTTPException(status_code=503, detail="Device not connected or import failed")
        return {"success": "error" not in results and "transaction_error" not in results, "results": results}

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
