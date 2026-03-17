# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive end-to-end test sweep for the Meshtastic addon.

Gold standard for addon testing: exercises EVERY public method across
connection, node_manager, message_bridge, device_manager, and router.

Uses realistic fake data based on actual T-LoRa Pager output with 250
Bay Area nodes.

UX Loop 2 (Add Sensor) — mesh nodes report sightings and messages into Tritium.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import random
import time
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from meshtastic_addon.connection import (
    ConnectionManager,
    DEFAULT_BLE_TIMEOUT,
    DEFAULT_MQTT_TIMEOUT,
    DEFAULT_SERIAL_TIMEOUT,
    DEFAULT_TCP_TIMEOUT,
)
from meshtastic_addon.node_manager import NodeManager, ROLE_NAMES
from meshtastic_addon.message_bridge import (
    MAX_MESSAGE_HISTORY,
    MeshMessage,
    MessageBridge,
    MessageType,
)
from meshtastic_addon.device_manager import (
    ChannelInfo,
    DeviceInfo,
    DeviceManager,
    DeviceRole,
    FirmwareInfo,
    KNOWN_FIRMWARE_VERSIONS,
    LATEST_STABLE,
)
from meshtastic_addon.router import create_router, create_compat_router

# ---------------------------------------------------------------------------
# Realistic fake data generators
# ---------------------------------------------------------------------------

# Bay Area coordinate bounds
BAY_AREA_LAT = (37.3, 37.9)
BAY_AREA_LNG = (-122.5, -122.0)

HW_MODELS = [
    "T_LORA_PAGER", "HELTEC_V3", "TBEAM_V1", "RAK4631",
    "TLORA_V2_1_1P6", "STATION_G1", "T_ECHO", "NANO_G1",
]

LONG_NAMES = [
    "Matt's Pager", "BaseStation-SF", "Relay-Twin Peaks", "Tracker-GGB",
    "Node-Sunset", "Repeater-Bernal", "Sensor-Marina", "TAK-Presidio",
]


def _make_node_id(i: int) -> str:
    """Generate a realistic hex node ID like !ba33ff38."""
    return f"!{0xba330000 + i:08x}"


def _make_raw_node(i: int, *, with_position: bool = True, with_metrics: bool = True,
                   with_env: bool = False, with_neighbors: bool = False,
                   role: int = 0, hops_away: int | None = None,
                   stale: bool = False) -> dict:
    """Generate a single raw node dict as the meshtastic library returns."""
    node_id = _make_node_id(i)
    now = time.time()
    raw: dict = {
        "num": 0xba330000 + i,
        "user": {
            "id": node_id,
            "longName": f"Node-{i:03d}",
            "shortName": f"N{i:02d}" if i < 100 else f"{i}",
            "hwModel": HW_MODELS[i % len(HW_MODELS)],
            "macaddr": f"aa:bb:cc:dd:{i >> 8:02x}:{i & 0xff:02x}",
            "role": role,
        },
        "lastHeard": int(now - 7200) if stale else int(now - random.randint(0, 300)),
    }

    if with_position:
        lat = random.uniform(*BAY_AREA_LAT)
        lng = random.uniform(*BAY_AREA_LNG)
        raw["position"] = {
            "latitudeI": int(lat * 1e7),
            "longitudeI": int(lng * 1e7),
            "altitude": random.randint(0, 300),
            "time": int(now),
        }

    if with_metrics:
        raw["deviceMetrics"] = {
            "batteryLevel": random.randint(10, 100),
            "voltage": round(random.uniform(3.2, 4.2), 2),
            "channelUtilization": round(random.uniform(0, 15), 1),
            "airUtilTx": round(random.uniform(0, 5), 1),
            "uptimeSeconds": random.randint(60, 86400),
        }

    if with_env:
        raw["environmentMetrics"] = {
            "temperature": round(random.uniform(10, 35), 1),
            "relativeHumidity": round(random.uniform(30, 90), 1),
            "barometricPressure": round(random.uniform(990, 1030), 1),
        }

    raw["snr"] = round(random.uniform(-10, 15), 1)

    if hops_away is not None:
        raw["hopsAway"] = hops_away

    if with_neighbors:
        # Give this node 2-4 neighbors
        neighbor_count = random.randint(2, 4)
        neighbors = []
        for j in range(neighbor_count):
            nid = 0xba330000 + ((i + j + 1) % 250)
            neighbors.append({
                "nodeId": nid,
                "snr": round(random.uniform(-5, 12), 1),
            })
        raw["neighborInfo"] = {"neighbors": neighbors}

    return raw


def _make_250_nodes() -> dict:
    """Generate 250 realistic raw nodes for a Bay Area mesh."""
    nodes = {}
    for i in range(250):
        node_id = _make_node_id(i)
        role = 2 if i < 10 else (3 if i < 20 else 0)  # 10 routers, 10 router_clients
        nodes[node_id] = _make_raw_node(
            i,
            with_position=(i < 200),  # 50 nodes without GPS
            with_metrics=True,
            with_env=(i < 5),
            with_neighbors=(i < 30),
            role=role,
            hops_away=(i // 50) if i < 200 else None,
            stale=(i >= 240),  # last 10 are stale
        )
    return nodes


# ---------------------------------------------------------------------------
# Mock meshtastic interface
# ---------------------------------------------------------------------------

def _make_mock_interface(node_id="!ba33ff38"):
    """Create a mock meshtastic interface with realistic attributes."""
    iface = MagicMock()
    iface.getMyNodeInfo.return_value = {
        "user": {
            "id": node_id,
            "longName": "Matt's Pager",
            "shortName": "MATT",
            "hwModel": "T_LORA_PAGER",
            "macaddr": "ba:33:ff:38:00:01",
        }
    }
    iface.nodes = _make_250_nodes()
    iface.close.return_value = None
    iface.sendText.return_value = None

    # Metadata
    metadata = MagicMock()
    metadata.firmware_version = "2.7.19.bb3d6d5"
    metadata.has_wifi = False
    metadata.has_bluetooth = True
    metadata.has_ethernet = False
    metadata.role = 0
    iface.metadata = metadata

    # Local config
    local_config = MagicMock()
    local_config.lora.region = 1  # US
    local_config.lora.modem_preset = 3  # LONG_FAST
    local_config.lora.tx_power = 27
    local_config.lora.hop_limit = 3
    local_config.device.role = 0
    local_config.position.gps_mode = 1
    local_config.network.wifi_enabled = False
    local_config.network.wifi_ssid = ""
    local_config.network.wifi_psk = ""
    local_config.bluetooth.enabled = True
    local_config.display.screen_on_secs = 60
    local_config.display.gps_format = 0
    local_config.display.auto_screen_carousel_secs = 0
    local_config.display.flip_screen = False
    local_config.display.units = 0
    local_config.power.is_power_saving = False
    local_config.power.on_battery_shutdown_after_secs = 0
    iface.localConfig = local_config

    # Module config
    module_config = MagicMock()
    module_config.mqtt.enabled = False
    module_config.mqtt.address = ""
    module_config.mqtt.username = ""
    module_config.mqtt.password = ""
    module_config.mqtt.encryption_enabled = False
    module_config.mqtt.json_enabled = False
    module_config.telemetry.device_update_interval = 900
    module_config.telemetry.environment_measurement_enabled = False
    module_config.telemetry.environment_update_interval = 900
    iface.moduleConfig = module_config

    # Local node
    local_node = MagicMock()
    local_node.channels = [MagicMock(), MagicMock(), MagicMock()]
    for idx, ch in enumerate(local_node.channels):
        ch.role = 1 if idx == 0 else (2 if idx == 1 else 0)
        ch.settings = MagicMock()
        ch.settings.name = "Primary" if idx == 0 else (f"Ch{idx}" if idx == 1 else "")
        ch.settings.psk = b"\x01" if idx == 0 else b""
        ch.settings.uplink_enabled = False
        ch.settings.downlink_enabled = False
    local_node.localConfig = local_config
    local_node.moduleConfig = module_config
    local_node.getURL.return_value = "https://meshtastic.org/e/#CgMSAQEKBxIFAQAAAA"
    local_node.setOwner.return_value = None
    local_node.setFixedPosition.return_value = None
    local_node.writeConfig.return_value = None
    local_node.writeChannel.return_value = None
    local_node.reboot.return_value = None
    local_node.factoryReset.return_value = None
    local_node.shutdown.return_value = None
    local_node.setURL.return_value = None
    local_node.beginSettingsTransaction.return_value = None
    local_node.commitSettingsTransaction.return_value = None
    iface.localNode = local_node

    return iface


# ===================================================================
# CONNECTION LIFECYCLE TESTS
# ===================================================================

class TestConnectionLifecycle:
    """Tests for ConnectionManager connect/disconnect across transports."""

    def setup_method(self):
        self.event_bus = MagicMock()
        self.node_manager = MagicMock()
        self.conn = ConnectionManager(
            node_manager=self.node_manager,
            event_bus=self.event_bus,
        )

    # -- Serial --

    @pytest.mark.asyncio
    async def test_connect_serial_success(self, tmp_path):
        """Serial connect with a valid port should succeed."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        mock_iface = _make_mock_interface()
        with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        assert self.conn.is_connected is True
        assert self.conn.transport_type == "serial"
        assert self.conn.port == str(fake_port)
        assert self.conn.interface is mock_iface
        assert self.conn.device_info.get("long_name") == "Matt's Pager"

    @pytest.mark.asyncio
    async def test_connect_serial_port_not_found(self):
        """Serial connect to nonexistent port should fail gracefully."""
        await self.conn.connect_serial("/dev/no_such_port", timeout=2.0, retries=0)
        assert self.conn.is_connected is False
        assert self.conn.interface is None

    @pytest.mark.asyncio
    async def test_connect_serial_timeout(self, tmp_path):
        """Serial connect that times out should fail gracefully."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        import threading

        def _block_forever(*args, **kwargs):
            # Block the executor thread long enough to trigger asyncio.wait_for timeout
            threading.Event().wait(timeout=10)
            raise RuntimeError("should have timed out")

        with patch("meshtastic.serial_interface.SerialInterface", side_effect=_block_forever):
            await self.conn.connect_serial(str(fake_port), timeout=0.2, retries=0)

        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_serial_exception(self, tmp_path):
        """Serial connect that throws should fail gracefully."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        with patch("meshtastic.serial_interface.SerialInterface", side_effect=RuntimeError("device busy")):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_serial_import_error(self, tmp_path):
        """Serial connect when meshtastic not installed should fail gracefully."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        with patch("meshtastic.serial_interface.SerialInterface", side_effect=ImportError("no module")):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_serial_retry(self, tmp_path):
        """Serial connect should retry on failure."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        call_count = 0
        mock_iface = _make_mock_interface()

        def _flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("busy")
            return mock_iface

        with patch("meshtastic.serial_interface.SerialInterface", side_effect=_flaky):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=1)

        assert self.conn.is_connected is True
        assert call_count == 2

    # -- BLE --

    @pytest.mark.asyncio
    async def test_connect_ble_success(self):
        """BLE connect should succeed with valid address."""
        mock_iface = _make_mock_interface()
        with patch("meshtastic.ble_interface.BLEInterface", return_value=mock_iface):
            await self.conn.connect_ble("AA:BB:CC:DD:EE:FF", timeout=5.0)

        assert self.conn.is_connected is True
        assert self.conn.transport_type == "ble"
        assert self.conn.port == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_connect_ble_failure(self):
        """BLE connect that throws should fail gracefully."""
        with patch("meshtastic.ble_interface.BLEInterface", side_effect=RuntimeError("BLE scan failed")):
            await self.conn.connect_ble("AA:BB:CC:DD:EE:FF", timeout=5.0)

        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_ble_import_error(self):
        """BLE connect when bleak not installed should fail gracefully."""
        import sys
        # Temporarily make import fail
        with patch.dict(sys.modules, {"meshtastic.ble_interface": None}):
            with patch("builtins.__import__", side_effect=ImportError("no bleak")):
                # Reset to test import path
                conn = ConnectionManager()
                await conn.connect_ble("AA:BB:CC:DD:EE:FF")
                assert conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_ble_auto_discover(self):
        """BLE connect without address should auto-discover."""
        mock_iface = _make_mock_interface()
        with patch("meshtastic.ble_interface.BLEInterface", return_value=mock_iface):
            await self.conn.connect_ble("", timeout=5.0)

        assert self.conn.is_connected is True
        assert self.conn.port == "auto"

    # -- TCP --

    @pytest.mark.asyncio
    async def test_connect_tcp_success(self):
        """TCP connect should succeed."""
        mock_iface = _make_mock_interface()
        with patch("meshtastic.tcp_interface.TCPInterface", return_value=mock_iface):
            await self.conn.connect_tcp("192.168.1.100", port=4403, timeout=5.0)

        assert self.conn.is_connected is True
        assert self.conn.transport_type == "tcp"
        assert self.conn.port == "192.168.1.100:4403"

    @pytest.mark.asyncio
    async def test_connect_tcp_timeout(self):
        """TCP connect that times out should fail."""
        with patch("meshtastic.tcp_interface.TCPInterface", side_effect=asyncio.TimeoutError()):
            await self.conn.connect_tcp("192.168.1.100", timeout=0.1)

        assert self.conn.is_connected is False

    # -- MQTT --

    @pytest.mark.asyncio
    async def test_connect_mqtt_success(self):
        """MQTT connect should succeed."""
        import sys
        import types

        mock_iface = MagicMock()
        # Create a fake meshtastic.mqtt_interface module with MQTTInterface
        mqtt_mod = types.ModuleType("meshtastic.mqtt_interface")
        mqtt_mod.MQTTInterface = MagicMock(return_value=mock_iface)

        # Insert into sys.modules so `import meshtastic.mqtt_interface` resolves
        # Also set as attribute on the meshtastic package
        import meshtastic
        had_attr = hasattr(meshtastic, "mqtt_interface")
        old_attr = getattr(meshtastic, "mqtt_interface", None)
        old_mod = sys.modules.get("meshtastic.mqtt_interface")

        try:
            sys.modules["meshtastic.mqtt_interface"] = mqtt_mod
            meshtastic.mqtt_interface = mqtt_mod

            await self.conn.connect_mqtt(
                host="mqtt.meshtastic.org", port=1883,
                topic="msh/US/2/e/#", username="meshdev", password="large4cats",
                timeout=5.0,
            )
        finally:
            # Restore
            if old_mod is not None:
                sys.modules["meshtastic.mqtt_interface"] = old_mod
            else:
                sys.modules.pop("meshtastic.mqtt_interface", None)
            if had_attr:
                meshtastic.mqtt_interface = old_attr
            elif hasattr(meshtastic, "mqtt_interface"):
                delattr(meshtastic, "mqtt_interface")

        assert self.conn.is_connected is True
        assert self.conn.transport_type == "mqtt"
        assert self.conn.port == "mqtt.meshtastic.org:1883"
        assert self.conn.device_info["mqtt_topic"] == "msh/US/2/e/#"

    # -- Disconnect --

    @pytest.mark.asyncio
    async def test_disconnect_while_connected(self, tmp_path):
        """Disconnect should clear all state."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()
        mock_iface = _make_mock_interface()
        with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        assert self.conn.is_connected is True
        await self.conn.disconnect()

        assert self.conn.is_connected is False
        assert self.conn.transport_type == "none"
        assert self.conn.port == ""
        assert self.conn.interface is None
        mock_iface.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_while_not_connected(self):
        """Disconnect when not connected should not raise."""
        await self.conn.disconnect()
        assert self.conn.is_connected is False

    # -- Reconnect / Switch --

    @pytest.mark.asyncio
    async def test_reconnect_same_port(self, tmp_path):
        """Connecting to the same port again should reuse the connection."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()
        mock_iface = _make_mock_interface()
        with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)
            # Second connect to same port
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        assert self.conn.is_connected is True
        assert self.conn.interface is mock_iface

    @pytest.mark.asyncio
    async def test_switch_port(self, tmp_path):
        """Switching from one port to another should close the old connection."""
        port_a = tmp_path / "ttyACM0"
        port_b = tmp_path / "ttyACM1"
        port_a.touch()
        port_b.touch()
        mock_iface_a = _make_mock_interface()
        mock_iface_b = _make_mock_interface("!ba33ff39")

        with patch("meshtastic.serial_interface.SerialInterface", side_effect=[mock_iface_a, mock_iface_b]):
            await self.conn.connect_serial(str(port_a), timeout=5.0, retries=0)
            assert self.conn.port == str(port_a)

            await self.conn.connect_serial(str(port_b), timeout=5.0, retries=0)
            assert self.conn.port == str(port_b)

        mock_iface_a.close.assert_called()

    # -- Auto-connect --

    @pytest.mark.asyncio
    async def test_auto_connect_env_var(self, tmp_path):
        """auto_connect should try the MESHTASTIC_SERIAL_PORT env var first."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()
        mock_iface = _make_mock_interface()

        with patch.dict("os.environ", {"MESHTASTIC_SERIAL_PORT": str(fake_port)}):
            with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
                await self.conn.auto_connect()

        assert self.conn.is_connected is True

    @pytest.mark.asyncio
    async def test_auto_connect_no_devices(self):
        """auto_connect with no devices should end in disconnected mode."""
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(self.conn, "_find_serial_device", return_value=None):
                await self.conn.auto_connect()

        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_auto_connect_tcp_fallback(self):
        """auto_connect should try TCP if serial fails and env var set."""
        mock_iface = _make_mock_interface()
        with patch.dict("os.environ", {"MESHTASTIC_TCP_HOST": "192.168.1.100"}):
            with patch.object(self.conn, "_find_serial_device", return_value=None):
                with patch("meshtastic.tcp_interface.TCPInterface", return_value=mock_iface):
                    await self.conn.auto_connect()

        assert self.conn.is_connected is True
        assert self.conn.transport_type == "tcp"

    # -- send_text --

    @pytest.mark.asyncio
    async def test_send_text_broadcast(self, tmp_path):
        """send_text should work for broadcast."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()
        mock_iface = _make_mock_interface()
        with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        ok = await self.conn.send_text("Hello mesh!")
        assert ok is True
        mock_iface.sendText.assert_called_once_with("Hello mesh!")

    @pytest.mark.asyncio
    async def test_send_text_not_connected(self):
        """send_text when not connected should return False."""
        ok = await self.conn.send_text("Hello")
        assert ok is False

    # -- get_nodes --

    @pytest.mark.asyncio
    async def test_get_nodes(self, tmp_path):
        """get_nodes should return interface nodes."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()
        mock_iface = _make_mock_interface()
        with patch("meshtastic.serial_interface.SerialInterface", return_value=mock_iface):
            await self.conn.connect_serial(str(fake_port), timeout=5.0, retries=0)

        nodes = await self.conn.get_nodes()
        assert len(nodes) == 250


# ===================================================================
# NODE MANAGEMENT TESTS
# ===================================================================

class TestNodeManager:
    """Tests for NodeManager parsing, targets, stats, links, hops."""

    def setup_method(self):
        self.event_bus = MagicMock()
        self.target_tracker = MagicMock()
        self.nm = NodeManager(
            event_bus=self.event_bus,
            target_tracker=self.target_tracker,
        )

    def test_update_nodes_250(self):
        """update_nodes with 250 realistic nodes should parse all."""
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)
        assert len(self.nm.nodes) == 250

    def test_parse_node_integer_position(self):
        """Nodes with latitudeI/longitudeI should be converted to float."""
        raw = {
            _make_node_id(0): {
                "num": 0xba330000,
                "user": {"id": _make_node_id(0), "longName": "Test", "shortName": "T", "hwModel": "T_LORA_PAGER", "role": 0},
                "position": {"latitudeI": 377490000, "longitudeI": -1222300000, "altitude": 100},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(0)]
        assert abs(node["lat"] - 37.749) < 0.001
        assert abs(node["lng"] - (-122.23)) < 0.001
        assert node["altitude"] == 100

    def test_parse_node_float_position(self):
        """Nodes with float latitude/longitude should be used directly."""
        raw = {
            _make_node_id(1): {
                "num": 0xba330001,
                "user": {"id": _make_node_id(1), "longName": "FloatNode", "shortName": "FN", "hwModel": "HELTEC_V3", "role": 0},
                "position": {"latitude": 37.7749, "longitude": -122.4194, "altitude": 50},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(1)]
        assert abs(node["lat"] - 37.7749) < 0.0001
        assert abs(node["lng"] - (-122.4194)) < 0.0001

    def test_parse_node_zero_position(self):
        """Nodes with lat=0, lng=0 float position should be treated as no position."""
        raw = {
            _make_node_id(2): {
                "num": 0xba330002,
                "user": {"id": _make_node_id(2), "longName": "ZeroNode", "shortName": "ZN", "hwModel": "TBEAM_V1", "role": 0},
                "position": {"latitude": 0.0, "longitude": 0.0, "altitude": 0},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(2)]
        assert "lat" not in node
        assert "lng" not in node

    def test_parse_node_no_position(self):
        """Nodes with no position data should have no lat/lng."""
        raw = {
            _make_node_id(3): {
                "num": 0xba330003,
                "user": {"id": _make_node_id(3), "longName": "NoGPS", "shortName": "NG", "hwModel": "RAK4631", "role": 0},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(3)]
        assert "lat" not in node
        assert "lng" not in node

    def test_parse_node_all_fields(self):
        """Node with all field types: battery, SNR, role, hopsAway, env, neighbors."""
        raw = {
            "!ba33ff38": _make_raw_node(
                0, with_position=True, with_metrics=True,
                with_env=True, with_neighbors=True, role=2,
                hops_away=1,
            )
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes["!ba33ff38"]

        # All fields present
        assert "lat" in node
        assert "lng" in node
        assert "altitude" in node
        assert "battery" in node
        assert "voltage" in node
        assert "channel_util" in node
        assert "air_util" in node
        assert "uptime" in node
        assert "temperature" in node
        assert "humidity" in node
        assert "pressure" in node
        assert "snr" in node
        assert "hops_away" in node and node["hops_away"] == 1
        assert node["role"] == "ROUTER"
        assert len(node["neighbors"]) >= 2
        assert isinstance(node["neighbor_snr"], dict)

    def test_parse_node_environment_metrics(self):
        """Environment metrics (temperature, humidity, pressure) should be parsed."""
        raw = {
            _make_node_id(4): _make_raw_node(4, with_env=True)
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(4)]
        assert "temperature" in node
        assert isinstance(node["temperature"], float)
        assert "humidity" in node
        assert "pressure" in node

    def test_parse_node_gps_extras(self):
        """GPS PDOP and satellite count should be parsed."""
        raw = {
            _make_node_id(5): {
                "num": 0xba330005,
                "user": {"id": _make_node_id(5), "longName": "GPSNode", "shortName": "GP", "hwModel": "TBEAM_V1", "role": 0},
                "position": {
                    "latitudeI": 377490000, "longitudeI": -1222300000,
                    "altitude": 50, "time": int(time.time()),
                    "PDOP": 150, "satsInView": 12,
                },
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(5)]
        assert node["gps_pdop"] == 150
        assert node["gps_sats"] == 12

    def test_parse_node_neighbor_numeric_ids(self):
        """Numeric neighbor IDs should be converted to hex string format."""
        raw = {
            _make_node_id(6): {
                "num": 0xba330006,
                "user": {"id": _make_node_id(6), "longName": "NeighborNode", "shortName": "NB", "hwModel": "HELTEC_V3", "role": 0},
                "lastHeard": int(time.time()),
                "neighborInfo": {
                    "neighbors": [
                        {"nodeId": 0xba330007, "snr": 8.5},
                        {"nodeId": 0xba330008, "snr": 3.2},
                    ]
                },
            }
        }
        self.nm.update_nodes(raw)
        node = self.nm.nodes[_make_node_id(6)]
        assert "!ba330007" in node["neighbors"]
        assert "!ba330008" in node["neighbors"]
        assert node["neighbor_snr"]["!ba330007"] == 8.5

    def test_parse_node_roles(self):
        """All ROLE_NAMES should map correctly."""
        for role_num, role_name in ROLE_NAMES.items():
            raw = {
                _make_node_id(100 + role_num): {
                    "num": 0xba330064 + role_num,
                    "user": {"id": _make_node_id(100 + role_num), "longName": f"Role{role_num}", "hwModel": "T_LORA_PAGER", "role": role_num},
                    "lastHeard": int(time.time()),
                }
            }
            self.nm.update_nodes(raw)
            node = self.nm.nodes[_make_node_id(100 + role_num)]
            assert node["role"] == role_name

    def test_stale_node_detection(self):
        """Nodes older than 600s should be marked stale in targets."""
        raw = {
            _make_node_id(10): {
                "num": 0xba33000a,
                "user": {"id": _make_node_id(10), "longName": "StaleNode", "hwModel": "T_LORA_PAGER", "role": 0},
                "lastHeard": int(time.time() - 700),  # 700s ago
            }
        }
        self.nm.update_nodes(raw)
        targets = self.nm.get_targets()
        stale_target = [t for t in targets if "ba33000a" in t["target_id"]][0]
        assert stale_target["stale"] is True

    def test_fresh_node_not_stale(self):
        """Recently heard nodes should not be stale."""
        raw = {
            _make_node_id(11): {
                "num": 0xba33000b,
                "user": {"id": _make_node_id(11), "longName": "FreshNode", "hwModel": "T_LORA_PAGER", "role": 0},
                "lastHeard": int(time.time() - 10),  # 10s ago
            }
        }
        self.nm.update_nodes(raw)
        targets = self.nm.get_targets()
        fresh_target = [t for t in targets if "ba33000b" in t["target_id"]][0]
        assert fresh_target["stale"] is False

    # -- get_targets --

    def test_get_targets_format(self):
        """Targets should have the correct Tritium target format."""
        raw = {
            "!ba33ff38": _make_raw_node(0, with_position=True, with_metrics=True, role=2)
        }
        self.nm.update_nodes(raw)
        targets = self.nm.get_targets()
        assert len(targets) == 1
        t = targets[0]

        assert t["target_id"] == "mesh_ba33ff38"  # ! stripped
        assert t["source"] == "mesh"
        assert t["asset_type"] == "mesh_radio"
        assert t["alliance"] == "friendly"
        assert "lat" in t
        assert "lng" in t
        assert "position" in t
        assert t["position"]["x"] == t["lng"]
        assert t["position"]["y"] == t["lat"]
        assert t["role"] == "ROUTER"
        assert t["is_router"] is True
        assert 0 <= t["battery"] <= 1.0  # normalized

    def test_get_targets_battery_normalization(self):
        """Battery should be normalized to 0-1 range."""
        raw = {
            _make_node_id(20): {
                "num": 0xba330014,
                "user": {"id": _make_node_id(20), "longName": "BattNode", "hwModel": "T_LORA_PAGER", "role": 0},
                "deviceMetrics": {"batteryLevel": 75, "voltage": 3.85},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        targets = self.nm.get_targets()
        t = [t for t in targets if "ba330014" in t["target_id"]][0]
        assert t["battery"] == 0.75

    def test_get_targets_no_position(self):
        """Targets without position should not have lat/lng/position keys."""
        raw = {
            _make_node_id(21): {
                "num": 0xba330015,
                "user": {"id": _make_node_id(21), "longName": "NoPosNode", "hwModel": "T_LORA_PAGER", "role": 0},
                "lastHeard": int(time.time()),
            }
        }
        self.nm.update_nodes(raw)
        targets = self.nm.get_targets()
        t = [t for t in targets if "ba330015" in t["target_id"]][0]
        assert "lat" not in t
        assert "position" not in t

    # -- get_stats --

    def test_get_stats_accuracy(self):
        """get_stats should correctly count online, GPS, routers, averages."""
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)
        stats = self.nm.get_stats()

        assert stats["total_nodes"] == 250
        assert stats["with_gps"] == 200  # first 200 have GPS
        assert stats["routers"] == 20  # 10 ROUTER + 10 ROUTER_CLIENT
        assert stats["online_nodes"] > 0
        assert stats["offline_nodes"] >= 0
        assert stats["avg_snr"] is not None
        assert stats["avg_battery"] is not None
        assert stats["link_count"] >= 0
        assert stats["last_update"] > 0

    def test_get_stats_empty(self):
        """get_stats with no nodes should return zeros."""
        stats = self.nm.get_stats()
        assert stats["total_nodes"] == 0
        assert stats["online_nodes"] == 0
        assert stats["avg_snr"] is None
        assert stats["avg_battery"] is None

    # -- get_links --

    def test_get_links_from_neighbors(self):
        """get_links should extract deduplicated links from neighbor data."""
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)
        links = self.nm.get_links()

        assert len(links) > 0
        # Verify no duplicate pairs
        pairs = set()
        for link in links:
            pair = tuple(sorted([link["from"], link["to"]]))
            assert pair not in pairs, f"Duplicate link: {pair}"
            pairs.add(pair)

    def test_get_links_empty(self):
        """get_links with no nodes should return empty list."""
        assert self.nm.get_links() == []

    # -- hop count BFS --

    def test_hop_count_bfs(self):
        """Hop count BFS should estimate distances from local node."""
        # Create a simple chain: A -> B -> C
        self.nm.set_local_node("!a")
        self.nm.nodes = {
            "!a": {"neighbors": ["!b"], "neighbor_snr": {"!b": 10}},
            "!b": {"neighbors": ["!a", "!c"], "neighbor_snr": {"!a": 10, "!c": 8}},
            "!c": {"neighbors": ["!b"], "neighbor_snr": {"!b": 8}},
        }
        self.nm._estimate_hops()

        assert self.nm._hop_counts["!a"] == 0
        assert self.nm._hop_counts["!b"] == 1
        assert self.nm._hop_counts["!c"] == 2

    def test_hop_count_snr_fallback(self):
        """Nodes not in neighbor graph should get SNR-based hop estimate."""
        self.nm.set_local_node("!a")
        self.nm.nodes = {
            "!a": {"neighbors": [], "snr": 12},
            "!d": {"snr": 8},  # good SNR, likely 1 hop
            "!e": {"snr": -2},  # medium SNR, likely 2 hops
            "!f": {"snr": -8},  # bad SNR, likely 3 hops
        }
        self.nm._estimate_hops()

        assert self.nm._hop_counts.get("!d") == 1
        assert self.nm._hop_counts.get("!e") == 2
        assert self.nm._hop_counts.get("!f") == 3

    # -- get_node --

    def test_get_node_exists(self):
        """get_node should return node data."""
        self.nm.nodes["!test"] = {"long_name": "Test"}
        assert self.nm.get_node("!test") == {"long_name": "Test"}

    def test_get_node_not_found(self):
        """get_node for unknown ID should return None."""
        assert self.nm.get_node("!nonexistent") is None

    # -- Event bus integration --

    def test_node_discovered_event(self):
        """First time a node is seen should fire node_discovered event."""
        raw = {
            _make_node_id(0): _make_raw_node(0)
        }
        self.nm.update_nodes(raw)
        self.event_bus.publish.assert_any_call(
            "meshtastic:node_discovered",
            {"node_id": _make_node_id(0), "name": "Node-000"},
        )

    def test_nodes_updated_event(self):
        """update_nodes should fire nodes_updated event."""
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)
        self.event_bus.publish.assert_any_call(
            "meshtastic:nodes_updated",
            {"count": 250, "total": 250},
        )

    def test_target_tracker_integration(self):
        """update_nodes should push targets to target_tracker."""
        raw = {_make_node_id(0): _make_raw_node(0, with_position=True)}
        self.nm.update_nodes(raw)
        self.target_tracker.update_from_mesh.assert_called()


# ===================================================================
# MESSAGE BRIDGE TESTS
# ===================================================================

class TestMessageBridge:
    """Tests for MessageBridge receive/send/history."""

    def setup_method(self):
        self.conn = MagicMock()
        self.conn.is_connected = True
        self.conn.interface = MagicMock()
        self.conn.send_text = AsyncMock(return_value=True)
        self.nm = NodeManager()
        self.event_bus = MagicMock()
        self.mqtt_bridge = MagicMock()
        self.bridge = MessageBridge(
            connection=self.conn,
            node_manager=self.nm,
            event_bus=self.event_bus,
            mqtt_bridge=self.mqtt_bridge,
            site_id="bayarea",
        )

    # -- Receive text message --

    def test_receive_text_message(self):
        """Incoming text message should be stored and emitted."""
        packet = {
            "fromId": "!ba33ff38",
            "toId": "!ffffffff",
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": "Hello from the mesh!",
            },
        }
        self.bridge._on_receive(packet)

        assert self.bridge.messages_received == 1
        assert len(self.bridge._messages) == 1
        msg = self.bridge._messages[0]
        assert msg.text == "Hello from the mesh!"
        assert msg.type == MessageType.TEXT
        assert msg.sender_id == "!ba33ff38"

    # -- Receive position --

    def test_receive_position_message(self):
        """Position report should update node manager and store."""
        self.nm.nodes["!ba33ff38"] = {"long_name": "Matt's Pager"}
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {
                    "latitudeI": 377490000,
                    "longitudeI": -1222300000,
                    "altitude": 50,
                    "groundSpeed": 2,
                    "groundTrack": 18000000,  # 180 degrees in 1e-5 units
                },
            },
        }
        self.bridge._on_receive(packet)

        assert self.bridge.position_reports == 1
        node = self.nm.nodes["!ba33ff38"]
        assert abs(node["lat"] - 37.749) < 0.001
        assert abs(node["lng"] - (-122.23)) < 0.001

    def test_receive_position_float(self):
        """Position with float lat/lng should work."""
        self.nm.nodes["!ba33ff39"] = {"long_name": "Float Node"}
        packet = {
            "fromId": "!ba33ff39",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                    "altitude": 30,
                },
            },
        }
        self.bridge._on_receive(packet)
        assert self.bridge.position_reports == 1

    def test_receive_position_no_coords(self):
        """Position with no coordinates should be ignored."""
        packet = {
            "fromId": "!ba33ff39",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {},
            },
        }
        self.bridge._on_receive(packet)
        assert self.bridge.position_reports == 0

    # -- Receive telemetry --

    def test_receive_telemetry_message(self):
        """Telemetry should update node manager and store."""
        self.nm.nodes["!ba33ff38"] = {"long_name": "Matt's Pager"}
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {
                "portnum": "TELEMETRY_APP",
                "telemetry": {
                    "deviceMetrics": {
                        "batteryLevel": 85,
                        "voltage": 3.95,
                        "channelUtilization": 5.2,
                        "airUtilTx": 1.3,
                        "uptimeSeconds": 3600,
                    },
                },
            },
        }
        self.bridge._on_receive(packet)

        assert self.bridge.telemetry_reports == 1
        node = self.nm.nodes["!ba33ff38"]
        assert node["battery"] == 85
        assert node["voltage"] == 3.95
        assert node["uptime"] == 3600

    def test_receive_telemetry_device_portnum(self):
        """DEVICE_TELEMETRY_APP should also be handled."""
        self.nm.nodes["!ba33ff38"] = {"long_name": "Matt's Pager"}
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {
                "portnum": "DEVICE_TELEMETRY_APP",
                "telemetry": {
                    "deviceMetrics": {
                        "batteryLevel": 50,
                    },
                },
            },
        }
        self.bridge._on_receive(packet)
        assert self.bridge.telemetry_reports == 1

    # -- Receive nodeinfo --

    def test_receive_nodeinfo(self):
        """Nodeinfo should update the node manager."""
        self.nm.nodes["!ba33ff38"] = {"long_name": "Old Name"}
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {
                "portnum": "NODEINFO_APP",
                "user": {
                    "longName": "New Name",
                    "shortName": "NN",
                    "hwModel": "T_LORA_PAGER",
                },
            },
        }
        self.bridge._on_receive(packet)
        assert self.nm.nodes["!ba33ff38"]["long_name"] == "New Name"
        assert self.nm.nodes["!ba33ff38"]["short_name"] == "NN"

    # -- Null packet --

    def test_receive_null_packet(self):
        """Null packet should be silently ignored."""
        self.bridge._on_receive(None)
        assert self.bridge.messages_received == 0

    # -- Send text --

    @pytest.mark.asyncio
    async def test_send_text_broadcast(self):
        """Send text broadcast should work."""
        ok = await self.bridge.send_text("Hello mesh!")
        assert ok is True
        assert self.bridge.messages_sent == 1
        self.conn.send_text.assert_awaited_once_with("Hello mesh!", destination=None)

    @pytest.mark.asyncio
    async def test_send_text_to_specific_node(self):
        """Send text to specific node should pass destination."""
        ok = await self.bridge.send_text("Hi Matt", destination="!ba33ff38")
        assert ok is True
        self.conn.send_text.assert_awaited_once_with("Hi Matt", destination="!ba33ff38")

    @pytest.mark.asyncio
    async def test_send_text_on_channel(self):
        """Send text should record channel in history."""
        ok = await self.bridge.send_text("Channel msg", channel=1)
        assert ok is True
        msg = self.bridge._messages[-1]
        assert msg.channel == 1

    @pytest.mark.asyncio
    async def test_send_text_no_connection(self):
        """Send without connection should return False."""
        bridge = MessageBridge(connection=None)
        ok = await bridge.send_text("Hello")
        assert ok is False

    # -- Message history --

    def test_message_history_limit(self):
        """get_messages with limit should respect the limit."""
        for i in range(20):
            self.bridge._messages.append(MeshMessage(
                sender_id=f"!node{i}", sender_name=f"Node{i}",
                text=f"Message {i}", timestamp=time.time() + i,
                type=MessageType.TEXT,
            ))

        msgs = self.bridge.get_messages(limit=5)
        assert len(msgs) == 5

    def test_message_history_filter_by_type(self):
        """get_messages should filter by type."""
        self.bridge._messages.append(MeshMessage(
            sender_id="!a", sender_name="A", text="Hello",
            timestamp=time.time(), type=MessageType.TEXT,
        ))
        self.bridge._messages.append(MeshMessage(
            sender_id="!b", sender_name="B", text="Pos",
            timestamp=time.time(), type=MessageType.POSITION,
        ))

        text_msgs = self.bridge.get_messages(msg_type="text")
        assert len(text_msgs) == 1
        assert text_msgs[0]["type"] == "text"

    def test_message_history_filter_by_since(self):
        """get_messages should filter by timestamp."""
        now = time.time()
        self.bridge._messages.append(MeshMessage(
            sender_id="!old", sender_name="Old", text="Old",
            timestamp=now - 100, type=MessageType.TEXT,
        ))
        self.bridge._messages.append(MeshMessage(
            sender_id="!new", sender_name="New", text="New",
            timestamp=now, type=MessageType.TEXT,
        ))

        msgs = self.bridge.get_messages(since=now - 50)
        assert len(msgs) == 1
        assert msgs[0]["sender_id"] == "!new"

    def test_message_history_cap(self):
        """Message history should be capped at MAX_MESSAGE_HISTORY."""
        for i in range(MAX_MESSAGE_HISTORY + 50):
            self.bridge._messages.append(MeshMessage(
                sender_id=f"!n{i}", sender_name=f"N{i}",
                text=f"Msg {i}", timestamp=time.time(),
                type=MessageType.TEXT,
            ))

        assert len(self.bridge._messages) == MAX_MESSAGE_HISTORY

    # -- Bridge stats --

    def test_bridge_stats(self):
        """get_stats should return accurate counts."""
        self.bridge.messages_received = 42
        self.bridge.messages_sent = 7
        self.bridge.position_reports = 15
        self.bridge.telemetry_reports = 10

        stats = self.bridge.get_stats()
        assert stats["messages_received"] == 42
        assert stats["messages_sent"] == 7
        assert stats["position_reports"] == 15
        assert stats["telemetry_reports"] == 10

    # -- Event bus / MQTT publishing --

    def test_text_message_emits_event(self):
        """Text message should publish to event bus."""
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Test"},
        }
        self.bridge._on_receive(packet)
        self.event_bus.publish.assert_any_call(
            "meshtastic:message_received",
            self.bridge._messages[0].to_dict(),
        )

    def test_text_message_publishes_mqtt(self):
        """Text message should publish to MQTT bridge."""
        packet = {
            "fromId": "!ba33ff38",
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Test"},
        }
        self.bridge._on_receive(packet)
        self.mqtt_bridge.publish.assert_called()

    # -- MeshMessage serialization --

    def test_mesh_message_to_dict(self):
        """MeshMessage.to_dict should include all non-None fields."""
        msg = MeshMessage(
            sender_id="!ba33ff38", sender_name="Matt",
            text="Hello", timestamp=1234567890.0,
            channel=1, type=MessageType.TEXT,
            destination="!ffffffff",
            lat=37.7749, lng=-122.4194,
            altitude=50, speed=2.5, heading=180.0,
            battery=85, voltage=3.95,
            channel_util=5.2, air_util=1.3, uptime=3600,
        )
        d = msg.to_dict()
        assert d["sender_id"] == "!ba33ff38"
        assert d["lat"] == 37.7749
        assert d["altitude"] == 50
        assert d["speed"] == 2.5
        assert d["battery"] == 85
        assert d["uptime"] == 3600

    def test_mesh_message_to_dict_minimal(self):
        """MeshMessage.to_dict should omit None fields."""
        msg = MeshMessage(
            sender_id="!a", sender_name="A",
            text="Hi", timestamp=1234567890.0,
        )
        d = msg.to_dict()
        assert "lat" not in d
        assert "battery" not in d
        assert "altitude" not in d

    # -- Name resolution --

    def test_resolve_node_name(self):
        """Node name resolution should use node_manager."""
        self.nm.nodes["!ba33ff38"] = {"long_name": "Matt's Pager", "short_name": "MATT"}
        name = self.bridge._resolve_node_name("!ba33ff38")
        assert name == "Matt's Pager"

    def test_resolve_node_name_fallback(self):
        """Unknown node ID should return the ID as-is."""
        name = self.bridge._resolve_node_name("!unknown")
        assert name == "!unknown"


# ===================================================================
# DEVICE MANAGER TESTS
# ===================================================================

class TestDeviceManager:
    """Tests for DeviceManager: config, firmware, channels, control."""

    def setup_method(self):
        self.conn = MagicMock()
        self.conn.is_connected = True
        self.conn.port = "/dev/ttyACM0"
        self.conn.interface = _make_mock_interface()
        self.dm = DeviceManager(self.conn)

    # -- set_owner --

    @pytest.mark.asyncio
    async def test_set_owner(self):
        """set_owner should call setOwner on localNode."""
        ok = await self.dm.set_owner("Matt's Pager", "MATT")
        assert ok is True
        self.conn.interface.localNode.setOwner.assert_called_once_with(
            long_name="Matt's Pager", short_name="MATT"
        )

    @pytest.mark.asyncio
    async def test_set_owner_long_only(self):
        """set_owner without short_name should only pass long_name."""
        ok = await self.dm.set_owner("Matt's Pager")
        assert ok is True
        self.conn.interface.localNode.setOwner.assert_called_once_with(
            long_name="Matt's Pager"
        )

    @pytest.mark.asyncio
    async def test_set_owner_not_connected(self):
        """set_owner when not connected should return False."""
        self.conn.is_connected = False
        ok = await self.dm.set_owner("Test")
        assert ok is False

    # -- set_role --

    @pytest.mark.asyncio
    async def test_set_role_all_values(self):
        """set_role should accept all 13 DeviceRole values."""
        for role in DeviceRole:
            self.conn.is_connected = True
            # Mock the protobuf import path
            with patch("meshtastic.protobuf.config_pb2.Config") as mock_config:
                mock_config.DeviceConfig.Role.Value.return_value = 0
                ok = await self.dm.set_role(role.value)
                assert ok is True, f"set_role({role.value}) should succeed"

    @pytest.mark.asyncio
    async def test_set_role_invalid(self):
        """set_role with invalid role should return False."""
        ok = await self.dm.set_role("INVALID_ROLE")
        assert ok is False

    # -- set_lora_config --

    @pytest.mark.asyncio
    async def test_set_lora_config(self):
        """set_lora_config with region, modem_preset, tx_power."""
        with patch("meshtastic.protobuf.config_pb2.Config") as mock_config:
            mock_config.LoRaConfig.RegionCode.Value.return_value = 1
            mock_config.LoRaConfig.ModemPreset.Value.return_value = 3
            ok = await self.dm.set_lora_config(
                region="US", modem_preset="LONG_FAST", tx_power=27
            )
            assert ok is True

    @pytest.mark.asyncio
    async def test_set_lora_config_empty(self):
        """set_lora_config with no params should return True (no-op)."""
        ok = await self.dm.set_lora_config()
        assert ok is True

    # -- set_position --

    @pytest.mark.asyncio
    async def test_set_position(self):
        """set_position should call setFixedPosition."""
        ok = await self.dm.set_position(lat=37.7749, lng=-122.4194, altitude=50)
        assert ok is True
        self.conn.interface.localNode.setFixedPosition.assert_called_once_with(
            37.7749, -122.4194, 50
        )

    @pytest.mark.asyncio
    async def test_set_position_with_gps_mode(self):
        """set_position with gps_mode should set GPS mode."""
        with patch("meshtastic.protobuf.config_pb2.Config") as mock_config:
            mock_config.PositionConfig.GpsMode.Value.return_value = 1
            ok = await self.dm.set_position(gps_mode="ENABLED")
            assert ok is True

    # -- set_wifi --

    @pytest.mark.asyncio
    async def test_set_wifi_enable(self):
        """set_wifi enable should set credentials."""
        ok = await self.dm.set_wifi(enabled=True, ssid="TestNet", password="secret")
        assert ok is True
        node = self.conn.interface.localNode
        node.writeConfig.assert_called_with("network")

    @pytest.mark.asyncio
    async def test_set_wifi_disable(self):
        """set_wifi disable should work."""
        ok = await self.dm.set_wifi(enabled=False)
        assert ok is True

    # -- set_bluetooth --

    @pytest.mark.asyncio
    async def test_set_bluetooth_enable(self):
        """set_bluetooth enable should work."""
        ok = await self.dm.set_bluetooth(enabled=True)
        assert ok is True

    @pytest.mark.asyncio
    async def test_set_bluetooth_disable(self):
        """set_bluetooth disable should work."""
        ok = await self.dm.set_bluetooth(enabled=False)
        assert ok is True

    # -- set_display_config --

    @pytest.mark.asyncio
    async def test_set_display_config(self):
        """set_display_config should set all display params."""
        with patch("meshtastic.protobuf.config_pb2.Config") as mock_config:
            mock_config.DisplayConfig.DisplayUnits.Value.return_value = 1
            ok = await self.dm.set_display_config(
                screen_on_secs=120, gps_format=0,
                auto_screen_carousel_secs=10, flip_screen=True,
                units="IMPERIAL",
            )
            assert ok is True

    # -- set_power_config --

    @pytest.mark.asyncio
    async def test_set_power_config(self):
        """set_power_config should set power saving and shutdown timer."""
        ok = await self.dm.set_power_config(
            is_power_saving=True, on_battery_shutdown_after_secs=3600
        )
        assert ok is True

    # -- set_mqtt_config --

    @pytest.mark.asyncio
    async def test_set_mqtt_config(self):
        """set_mqtt_config should set all MQTT params."""
        ok = await self.dm.set_mqtt_config(
            enabled=True, address="mqtt.local:1883",
            username="user", password="pass",
            encryption_enabled=True, json_enabled=True,
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_set_mqtt_config_empty(self):
        """set_mqtt_config with no params should return True (no-op)."""
        ok = await self.dm.set_mqtt_config()
        assert ok is True

    # -- set_telemetry_config --

    @pytest.mark.asyncio
    async def test_set_telemetry_config(self):
        """set_telemetry_config should set intervals and enable env."""
        ok = await self.dm.set_telemetry_config(
            device_update_interval=300,
            environment_measurement_enabled=True,
            environment_update_interval=600,
        )
        assert ok is True

    # -- configure_channel --

    @pytest.mark.asyncio
    async def test_configure_channel_secondary(self):
        """configure_channel should set name, PSK, role, uplink on channel 1."""
        with patch("meshtastic.protobuf.channel_pb2") as mock_ch_pb:
            mock_ch_pb.Channel.Role.PRIMARY = 1
            mock_ch_pb.Channel.Role.SECONDARY = 2
            mock_ch_pb.Channel.Role.DISABLED = 0
            ok = await self.dm.configure_channel(
                index=1, name="Tritium", psk="random",
                role="SECONDARY", uplink_enabled=True,
            )
            assert ok is True

    @pytest.mark.asyncio
    async def test_configure_channel_psk_default(self):
        """configure_channel with psk='default' should use default key."""
        with patch("meshtastic.protobuf.channel_pb2"):
            ok = await self.dm.configure_channel(index=0, psk="default")
            assert ok is True

    @pytest.mark.asyncio
    async def test_configure_channel_psk_none(self):
        """configure_channel with psk='none' should clear encryption."""
        with patch("meshtastic.protobuf.channel_pb2"):
            ok = await self.dm.configure_channel(index=0, psk="none")
            assert ok is True

    @pytest.mark.asyncio
    async def test_configure_channel_psk_base64(self):
        """configure_channel with base64 PSK should decode it."""
        psk_b64 = base64.b64encode(b"\x01\x02\x03\x04" * 8).decode()
        with patch("meshtastic.protobuf.channel_pb2"):
            ok = await self.dm.configure_channel(index=1, psk=psk_b64)
            assert ok is True

    @pytest.mark.asyncio
    async def test_configure_channel_out_of_range(self):
        """configure_channel with index > 7 should fail."""
        ok = await self.dm.configure_channel(index=8)
        assert ok is False

    @pytest.mark.asyncio
    async def test_configure_channel_negative_index(self):
        """configure_channel with negative index should fail."""
        ok = await self.dm.configure_channel(index=-1)
        assert ok is False

    # -- remove_channel --

    @pytest.mark.asyncio
    async def test_remove_channel_index_0_fails(self):
        """remove_channel on primary channel (index 0) should fail."""
        ok = await self.dm.remove_channel(0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_remove_channel_secondary(self):
        """remove_channel on index 1+ should set role to DISABLED."""
        with patch("meshtastic.protobuf.channel_pb2") as mock_ch_pb:
            mock_ch_pb.Channel.Role.DISABLED = 0
            mock_ch_pb.Channel.Role.PRIMARY = 1
            mock_ch_pb.Channel.Role.SECONDARY = 2
            ok = await self.dm.remove_channel(1)
            assert ok is True

    # -- channel URL --

    @pytest.mark.asyncio
    async def test_get_channel_url(self):
        """get_channel_url should return the URL from localNode."""
        url = await self.dm.get_channel_url()
        assert url.startswith("https://meshtastic.org/e/")

    @pytest.mark.asyncio
    async def test_set_channel_url(self):
        """set_channel_url should call setURL."""
        ok = await self.dm.set_channel_url("https://meshtastic.org/e/#CgMSAQE")
        assert ok is True
        self.conn.interface.localNode.setURL.assert_called_once_with(
            "https://meshtastic.org/e/#CgMSAQE"
        )

    @pytest.mark.asyncio
    async def test_get_channel_url_not_connected(self):
        """get_channel_url when not connected should return empty string."""
        self.conn.is_connected = False
        url = await self.dm.get_channel_url()
        assert url == ""

    # -- export_config / import_config roundtrip --

    @pytest.mark.asyncio
    async def test_export_config(self):
        """export_config should return a dict with config sections."""
        # Mock _proto_to_dict to avoid real protobuf
        with patch("meshtastic_addon.device_manager._proto_to_dict", return_value={"key": "value"}):
            config = await self.dm.export_config()

        assert isinstance(config, dict)
        # Should have at least channels and channel_url
        assert "channels" in config
        assert "channel_url" in config

    @pytest.mark.asyncio
    async def test_import_config(self):
        """import_config should apply config sections."""
        config = {
            "device": {"role": 0},
            "lora": {"tx_power": 27},
            "channel_url": "https://meshtastic.org/e/#CgMSAQE",
        }
        with patch("meshtastic.protobuf.config_pb2.Config"):
            results = await self.dm.import_config(config)

        assert isinstance(results, dict)
        # channel_url should be applied
        assert "channels" in results

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self):
        """export then import should not raise."""
        with patch("meshtastic_addon.device_manager._proto_to_dict", return_value={"key": "value"}):
            config = await self.dm.export_config()

        with patch("meshtastic.protobuf.config_pb2.Config"):
            results = await self.dm.import_config(config)

        assert isinstance(results, dict)

    @pytest.mark.asyncio
    async def test_export_config_not_connected(self):
        """export_config when not connected should return empty dict."""
        self.conn.is_connected = False
        config = await self.dm.export_config()
        assert config == {}

    @pytest.mark.asyncio
    async def test_import_config_not_connected(self):
        """import_config when not connected should return empty dict."""
        self.conn.is_connected = False
        results = await self.dm.import_config({"device": {"role": 0}})
        assert results == {}

    # -- Firmware --

    @pytest.mark.asyncio
    async def test_get_firmware_info(self):
        """get_firmware_info should report current version and update status."""
        fw = await self.dm.get_firmware_info()
        assert isinstance(fw, FirmwareInfo)
        assert fw.current_version == "2.7.19.bb3d6d5"
        assert fw.hw_model == "T_LORA_PAGER"
        # 2.7.19 is not in KNOWN_FIRMWARE_VERSIONS, so update_available should be True
        assert fw.update_available is True
        assert fw.latest_version == LATEST_STABLE

    @pytest.mark.asyncio
    async def test_get_firmware_info_not_connected(self):
        """get_firmware_info when not connected should return empty."""
        self.conn.is_connected = False
        fw = await self.dm.get_firmware_info()
        assert fw.current_version == ""
        assert fw.update_available is False

    @pytest.mark.asyncio
    async def test_detect_device_with_flasher(self):
        """detect_device should use flasher if available."""
        mock_flasher = MagicMock()
        mock_detection = MagicMock()
        mock_detection.to_dict.return_value = {"chip": "ESP32-S3", "board": "T_LORA_PAGER"}
        mock_flasher.detect = AsyncMock(return_value=mock_detection)

        with patch.object(self.dm, "_get_flasher", return_value=mock_flasher):
            result = await self.dm.detect_device()
            assert result["chip"] == "ESP32-S3"

    @pytest.mark.asyncio
    async def test_detect_device_no_flasher(self):
        """detect_device without flasher should return error."""
        with patch.object(self.dm, "_get_flasher", return_value=None):
            result = await self.dm.detect_device()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_flash_firmware_with_path(self):
        """flash_firmware with a path should pass it to flasher."""
        # flash_firmware disconnects first, so mock disconnect as async
        self.conn.disconnect = AsyncMock()
        mock_flasher = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"success": True}
        mock_flasher.flash = AsyncMock(return_value=mock_result)

        with patch.object(self.dm, "_get_flasher", return_value=mock_flasher):
            result = await self.dm.flash_firmware("/tmp/firmware.bin")
            assert result["success"] is True
            mock_flasher.flash.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flash_latest(self):
        """flash_latest should call flash_firmware with no path."""
        self.conn.disconnect = AsyncMock()
        mock_flasher = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"success": True}
        mock_flasher.flash_latest = AsyncMock(return_value=mock_result)

        with patch.object(self.dm, "_get_flasher", return_value=mock_flasher):
            result = await self.dm.flash_latest()
            assert result["success"] is True

    # -- Device control --

    @pytest.mark.asyncio
    async def test_reboot(self):
        """reboot should send reboot command."""
        ok = await self.dm.reboot(seconds=3)
        assert ok is True
        self.conn.interface.localNode.reboot.assert_called_once_with(3)
        assert self.conn.is_connected is False

    @pytest.mark.asyncio
    async def test_factory_reset(self):
        """factory_reset should send reset command."""
        ok = await self.dm.factory_reset()
        assert ok is True
        self.conn.interface.localNode.factoryReset.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """shutdown should send shutdown command."""
        ok = await self.dm.shutdown()
        assert ok is True
        self.conn.interface.localNode.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_reboot_not_connected(self):
        """reboot when not connected should return False."""
        self.conn.is_connected = False
        ok = await self.dm.reboot()
        assert ok is False

    # -- get_device_info --

    @pytest.mark.asyncio
    async def test_get_device_info(self):
        """get_device_info should return DeviceInfo with all fields."""
        # Need to mock the protobuf imports inside _read_device_info_sync
        with patch("meshtastic.protobuf.config_pb2.Config") as mock_config:
            mock_config.DeviceConfig.Role.Name.return_value = "CLIENT"
            mock_config.LoRaConfig.RegionCode.Name.return_value = "US"
            mock_config.LoRaConfig.ModemPreset.Name.return_value = "LONG_FAST"
            with patch("meshtastic.protobuf.channel_pb2.Channel") as mock_ch:
                mock_ch.Role.Name.return_value = "PRIMARY"
                info = await self.dm.get_device_info()

        assert isinstance(info, DeviceInfo)
        assert info.long_name == "Matt's Pager"
        assert info.short_name == "MATT"
        assert info.hw_model == "T_LORA_PAGER"
        assert info.firmware_version == "2.7.19.bb3d6d5"

    @pytest.mark.asyncio
    async def test_get_device_info_not_connected(self):
        """get_device_info when not connected should return empty DeviceInfo."""
        self.conn.is_connected = False
        info = await self.dm.get_device_info()
        assert info.node_id == ""
        assert info.long_name == ""

    # -- get_channels --

    @pytest.mark.asyncio
    async def test_get_channels(self):
        """get_channels should return list of ChannelInfo."""
        with patch("meshtastic.protobuf.channel_pb2.Channel") as mock_ch:
            mock_ch.Role.Name.side_effect = lambda v: {1: "PRIMARY", 2: "SECONDARY", 0: "DISABLED"}.get(v, str(v))
            channels = await self.dm.get_channels()

        assert len(channels) == 3
        assert isinstance(channels[0], ChannelInfo)

    @pytest.mark.asyncio
    async def test_get_channels_not_connected(self):
        """get_channels when not connected should return empty list."""
        self.conn.is_connected = False
        channels = await self.dm.get_channels()
        assert channels == []


# ===================================================================
# DATA CLASS TESTS
# ===================================================================

class TestDataClasses:
    """Tests for ChannelInfo, DeviceInfo, FirmwareInfo serialization."""

    def test_channel_info_to_dict(self):
        ch = ChannelInfo(index=0, name="Primary", role="PRIMARY", psk="AQAAAA==")
        d = ch.to_dict()
        assert d["index"] == 0
        assert d["name"] == "Primary"
        assert d["role"] == "PRIMARY"

    def test_device_info_to_dict(self):
        info = DeviceInfo(
            node_id="!ba33ff38", long_name="Matt's Pager",
            short_name="MATT", hw_model="T_LORA_PAGER",
            firmware_version="2.7.19.bb3d6d5",
            channels=[ChannelInfo(index=0, name="Primary", role="PRIMARY")],
        )
        d = info.to_dict()
        assert d["node_id"] == "!ba33ff38"
        assert len(d["channels"]) == 1

    def test_firmware_info_to_dict(self):
        fw = FirmwareInfo(
            current_version="2.7.19.bb3d6d5",
            latest_version=LATEST_STABLE,
            update_available=True,
            hw_model="T_LORA_PAGER",
            esptool_available=True,
            meshtastic_cli_available=True,
        )
        d = fw.to_dict()
        assert d["current_version"] == "2.7.19.bb3d6d5"
        assert d["update_available"] is True

    def test_device_role_enum(self):
        """All 13 DeviceRole values should be valid."""
        assert len(DeviceRole) == 13
        for role in DeviceRole:
            assert role.value == role.name  # str enum: value == name

    def test_message_type_enum(self):
        """MessageType values should be lowercase strings."""
        assert MessageType.TEXT == "text"
        assert MessageType.POSITION == "position"
        assert MessageType.TELEMETRY == "telemetry"
        assert MessageType.NODEINFO == "nodeinfo"
        assert MessageType.ROUTING == "routing"
        assert MessageType.ADMIN == "admin"

    def test_known_firmware_versions(self):
        """KNOWN_FIRMWARE_VERSIONS should be a non-empty list of version strings."""
        assert len(KNOWN_FIRMWARE_VERSIONS) > 0
        assert LATEST_STABLE in KNOWN_FIRMWARE_VERSIONS


# ===================================================================
# ROUTER TESTS (FastAPI endpoints)
# ===================================================================

class TestRouter:
    """Tests for the FastAPI router endpoints."""

    def setup_method(self):
        self.conn = MagicMock()
        self.conn.is_connected = True
        self.conn.interface = _make_mock_interface()
        self.conn.transport_type = "serial"
        self.conn.port = "/dev/ttyACM0"
        self.conn.device_info = {
            "node_id": "!ba33ff38",
            "long_name": "Matt's Pager",
            "short_name": "MATT",
            "hw_model": "T_LORA_PAGER",
        }

        self.nm = NodeManager()
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)

        self.bridge = MagicMock()
        self.bridge.get_messages.return_value = [
            {"sender_id": "!a", "text": "Hello", "timestamp": time.time(), "type": "text"}
        ]
        self.bridge.get_stats.return_value = {
            "messages_received": 10, "messages_sent": 2,
            "position_reports": 5, "telemetry_reports": 3,
            "history_size": 10, "registered": True,
        }
        self.bridge.send_text = AsyncMock(return_value=True)

        self.router = create_router(self.conn, self.nm, self.bridge)

    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        """GET /status should return connection info."""
        # Find the status route handler
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/status":
                resp = await route.endpoint()
                assert resp["connected"] is True
                assert resp["transport"] == "serial"
                assert resp["node_count"] == 250
                break

    @pytest.mark.asyncio
    async def test_nodes_endpoint(self):
        """GET /nodes should return all 250 nodes."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/nodes":
                resp = await route.endpoint()
                assert resp["count"] == 250
                assert len(resp["nodes"]) == 250
                break

    @pytest.mark.asyncio
    async def test_targets_endpoint(self):
        """GET /targets should return Tritium targets."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/targets":
                resp = await route.endpoint()
                assert len(resp["targets"]) == 250
                break

    @pytest.mark.asyncio
    async def test_links_endpoint(self):
        """GET /links should return mesh links."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/links":
                resp = await route.endpoint()
                assert "links" in resp
                break

    @pytest.mark.asyncio
    async def test_stats_endpoint(self):
        """GET /stats should return network stats."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/stats":
                resp = await route.endpoint()
                assert resp["total_nodes"] == 250
                break

    @pytest.mark.asyncio
    async def test_messages_endpoint(self):
        """GET /messages should return message history."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/messages":
                resp = await route.endpoint(limit=100, type=None, since=None)
                assert resp["count"] == 1
                break

    @pytest.mark.asyncio
    async def test_send_endpoint(self):
        """POST /send should send a message."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/send":
                resp = await route.endpoint({"text": "Hello mesh!"})
                assert resp["sent"] is True
                break

    @pytest.mark.asyncio
    async def test_send_empty_message(self):
        """POST /send with empty text should return error."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/send":
                resp = await route.endpoint({"text": ""})
                assert resp["error"] == "empty_message"
                break

    @pytest.mark.asyncio
    async def test_bridge_stats_endpoint(self):
        """GET /bridge/stats should return bridge stats."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/bridge/stats":
                resp = await route.endpoint()
                assert resp["messages_received"] == 10
                break

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """GET /health should return health status."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/health":
                resp = await route.endpoint()
                assert resp["status"] == "ok"
                assert resp["connected"] is True
                break

    @pytest.mark.asyncio
    async def test_disconnect_endpoint(self):
        """POST /disconnect should disconnect."""
        self.conn.disconnect = AsyncMock()
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/disconnect":
                resp = await route.endpoint()
                assert resp["connected"] is False
                break

    @pytest.mark.asyncio
    async def test_single_node_endpoint(self):
        """GET /nodes/{node_id} should return a single node."""
        node_id = _make_node_id(0)
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/nodes/{node_id}":
                resp = await route.endpoint(node_id)
                assert "long_name" in resp
                break

    @pytest.mark.asyncio
    async def test_single_node_not_found(self):
        """GET /nodes/{node_id} for unknown node should return error."""
        for route in self.router.routes:
            if hasattr(route, "path") and route.path == "/nodes/{node_id}":
                resp = await route.endpoint("!nonexistent")
                assert resp.get("error") == "not_found"
                break


class TestCompatRouter:
    """Tests for the backward-compatible router."""

    def setup_method(self):
        self.conn = MagicMock()
        self.conn.is_connected = True
        self.nm = NodeManager()
        raw = _make_250_nodes()
        self.nm.update_nodes(raw)
        self.compat = create_compat_router(self.conn, self.nm)

    @pytest.mark.asyncio
    async def test_compat_nodes(self):
        """Compat /nodes should return nodes in legacy format."""
        for route in self.compat.routes:
            if hasattr(route, "path") and route.path == "/nodes":
                resp = await route.endpoint(has_gps=False)
                assert resp["count"] == 250
                node = resp["nodes"][0]
                assert "user" in node
                assert "position" in node or "deviceMetrics" in node
                break

    @pytest.mark.asyncio
    async def test_compat_nodes_gps_filter(self):
        """Compat /nodes?has_gps=true should filter GPS-less nodes."""
        for route in self.compat.routes:
            if hasattr(route, "path") and route.path == "/nodes":
                resp = await route.endpoint(has_gps=True)
                # Only nodes with GPS (200 of 250 have positions)
                assert resp["count"] == 200
                break

    @pytest.mark.asyncio
    async def test_compat_status(self):
        """Compat /status should return basic status."""
        for route in self.compat.routes:
            if hasattr(route, "path") and route.path == "/status":
                resp = await route.endpoint()
                assert resp["connected"] is True
                assert resp["node_count"] == 250
                break


# ===================================================================
# EDGE CASE & INTEGRATION TESTS
# ===================================================================

class TestEdgeCases:
    """Edge cases and integration scenarios."""

    def test_node_manager_handles_missing_user(self):
        """Nodes with no user field should still parse."""
        nm = NodeManager()
        raw = {
            "!test": {
                "num": 12345,
                "lastHeard": int(time.time()),
            }
        }
        nm.update_nodes(raw)
        node = nm.nodes.get("!test")
        assert node is not None
        assert node["long_name"] == "!test"  # falls back to node_id

    def test_node_manager_handles_unknown_role(self):
        """Nodes with unknown role number should get UNKNOWN(n) name."""
        nm = NodeManager()
        raw = {
            "!test": {
                "num": 12345,
                "user": {"id": "!test", "role": 99},
                "lastHeard": int(time.time()),
            }
        }
        nm.update_nodes(raw)
        assert nm.nodes["!test"]["role"] == "UNKNOWN(99)"

    def test_message_bridge_legacy_callback(self):
        """_on_receive_legacy should delegate to _on_receive."""
        bridge = MessageBridge()
        bridge._on_receive = MagicMock()
        packet = {"decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Hi"}}
        bridge._on_receive_legacy(packet)
        bridge._on_receive.assert_called_once_with(packet)

    def test_very_old_last_heard(self):
        """Very old last_heard should result in stale=True and age calculation."""
        nm = NodeManager()
        raw = {
            "!ancient": {
                "num": 1,
                "user": {"id": "!ancient", "role": 0},
                "lastHeard": 1000000,  # ~1970
            }
        }
        nm.update_nodes(raw)
        targets = nm.get_targets()
        assert targets[0]["stale"] is True

    def test_last_heard_zero(self):
        """last_heard=0 should result in infinite age (stale)."""
        nm = NodeManager()
        raw = {
            "!zero": {
                "num": 1,
                "user": {"id": "!zero", "role": 0},
                "lastHeard": 0,
            }
        }
        nm.update_nodes(raw)
        targets = nm.get_targets()
        assert targets[0]["stale"] is True

    def test_router_null_components(self):
        """Router with None components should not crash."""
        router = create_router(None, None, None)
        assert router is not None

    @pytest.mark.asyncio
    async def test_router_null_status(self):
        """Status endpoint with None connection should return disconnected."""
        router = create_router(None, None, None)
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/status":
                resp = await route.endpoint()
                assert resp["connected"] is False
                assert resp["node_count"] == 0
                break

    @pytest.mark.asyncio
    async def test_router_null_send(self):
        """Send endpoint with no bridge or connection should return error."""
        router = create_router(None, None, None)
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/send":
                resp = await route.endpoint({"text": "Hello"})
                assert "error" in resp
                break

    def test_position_integer_scale(self):
        """Position integers near Bay Area should scale correctly."""
        nm = NodeManager()
        # San Francisco: 37.7749 N, -122.4194 W
        raw = {
            "!sf": {
                "num": 1,
                "user": {"id": "!sf", "role": 0},
                "position": {
                    "latitudeI": 377749000,
                    "longitudeI": -1224194000,
                    "altitude": 16,
                },
                "lastHeard": int(time.time()),
            }
        }
        nm.update_nodes(raw)
        node = nm.nodes["!sf"]
        assert abs(node["lat"] - 37.7749) < 0.0001
        assert abs(node["lng"] - (-122.4194)) < 0.0001

    def test_heading_conversion(self):
        """groundTrack in 1e-5 degree units should be converted."""
        bridge = MessageBridge(node_manager=NodeManager())
        packet = {
            "fromId": "!test",
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {
                    "latitudeI": 377490000,
                    "longitudeI": -1222300000,
                    "groundTrack": 18000000,  # 180.0 degrees
                },
            },
        }
        bridge._on_receive(packet)
        msg = bridge._messages[0]
        assert abs(msg.heading - 180.0) < 0.01

    def test_250_nodes_performance(self):
        """Parsing 250 nodes should complete in under 1 second."""
        nm = NodeManager()
        raw = _make_250_nodes()
        start = time.time()
        nm.update_nodes(raw)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"250 nodes took {elapsed:.2f}s (should be < 1s)"
        targets = nm.get_targets()
        assert len(targets) == 250
        stats = nm.get_stats()
        assert stats["total_nodes"] == 250
