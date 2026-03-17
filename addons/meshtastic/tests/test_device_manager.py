# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Meshtastic device manager.

All tests use mock objects — no real Meshtastic hardware required.
"""

import asyncio
import base64
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

from meshtastic_addon.device_manager import (
    DeviceManager,
    DeviceInfo,
    DeviceRole,
    ChannelInfo,
    FirmwareInfo,
    KNOWN_FIRMWARE_VERSIONS,
    LATEST_STABLE,
    create_device_routes,
    _bytes_to_base64,
    _proto_to_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeConnection:
    """Mock ConnectionManager with a fake meshtastic interface."""

    def __init__(self, connected: bool = True):
        self.is_connected = connected
        self.transport_type = "serial" if connected else "none"
        self.port = "/dev/ttyACM0" if connected else ""
        self.interface = self._make_interface() if connected else None

    def _make_interface(self):
        """Build a fake meshtastic interface object."""
        iface = MagicMock()

        # getMyNodeInfo
        iface.getMyNodeInfo.return_value = {
            "user": {
                "id": "!aabbccdd",
                "longName": "TestNode Alpha",
                "shortName": "TNA",
                "hwModel": "HELTEC_V3",
                "macaddr": "aa:bb:cc:dd:ee:ff",
            },
        }

        # getMetadata
        metadata = SimpleNamespace(
            firmware_version="2.5.18.e787254",
            has_wifi=True,
            has_bluetooth=True,
            has_ethernet=False,
            role="CLIENT",
            reboot_count=3,
        )
        iface.getMetadata.return_value = metadata
        iface.metadata = metadata  # Code reads cached attribute directly

        # localConfig with lora sub-config (use protobuf enum ints like real device)
        lora = SimpleNamespace(
            region=1,          # 1 = US in Config.LoRaConfig.RegionCode
            modem_preset=0,    # 0 = LONG_FAST in Config.LoRaConfig.ModemPreset
            tx_power=27,
        )
        iface.localConfig = SimpleNamespace(lora=lora)

        # localNode with channels
        ch0_settings = SimpleNamespace(
            name="primary",
            psk=b"\x01",
            uplink_enabled=False,
            downlink_enabled=False,
        )
        ch0 = SimpleNamespace(role="PRIMARY", settings=ch0_settings)

        ch1_settings = SimpleNamespace(
            name="admin",
            psk=b"\xab\xcd",
            uplink_enabled=True,
            downlink_enabled=False,
        )
        ch1 = SimpleNamespace(role="SECONDARY", settings=ch1_settings)

        local_node = MagicMock()
        local_node.channels = [ch0, ch1]
        # localConfig on localNode — used by _sync config methods
        local_node.localConfig = SimpleNamespace(
            device=SimpleNamespace(role=0),
            lora=SimpleNamespace(region=1, modem_preset=0, tx_power=27),
            position=SimpleNamespace(gps_mode=1),
            network=SimpleNamespace(wifi_enabled=False, wifi_ssid="", wifi_psk=""),
            bluetooth=SimpleNamespace(enabled=True),
            display=SimpleNamespace(
                screen_on_secs=0, gps_format=0,
                auto_screen_carousel_secs=0, flip_screen=False, units=0,
            ),
            power=SimpleNamespace(is_power_saving=False, on_battery_shutdown_after_secs=0),
        )
        # moduleConfig on localNode — used by MQTT/telemetry config methods
        local_node.moduleConfig = SimpleNamespace(
            mqtt=SimpleNamespace(
                enabled=False, address="", username="", password="",
                encryption_enabled=True, json_enabled=False,
            ),
            telemetry=SimpleNamespace(
                device_update_interval=900,
                environment_measurement_enabled=False,
                environment_update_interval=900,
            ),
        )
        iface.localNode = local_node

        # moduleConfig
        telemetry = SimpleNamespace()
        telemetry.DESCRIPTOR = SimpleNamespace(
            fields=[
                SimpleNamespace(name="device_update_interval"),
                SimpleNamespace(name="environment_update_interval"),
            ]
        )
        telemetry.device_update_interval = 900
        telemetry.environment_update_interval = 900
        iface.moduleConfig = SimpleNamespace(
            telemetry=telemetry,
            range_test=None,
            store_forward=None,
            serial=None,
            external_notification=None,
            canned_message=None,
            audio=None,
            remote_hardware=None,
            neighbor_info=None,
            detection_sensor=None,
            paxcounter=None,
            ambient_lighting=None,
        )

        return iface

    async def disconnect(self):
        self.is_connected = False
        self.interface = None


@pytest.fixture
def connected_dm():
    """DeviceManager with a connected fake device."""
    conn = FakeConnection(connected=True)
    return DeviceManager(conn)


@pytest.fixture
def disconnected_dm():
    """DeviceManager with no connected device."""
    conn = FakeConnection(connected=False)
    return DeviceManager(conn)


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_device_info_defaults(self):
        info = DeviceInfo()
        assert info.node_id == ""
        assert info.firmware_version == ""
        assert info.has_wifi is False
        assert info.channels == []

    def test_device_info_to_dict(self):
        info = DeviceInfo(
            node_id="!test",
            long_name="Test Node",
            firmware_version="2.5.18",
            channels=[ChannelInfo(index=0, name="primary", role="PRIMARY")],
        )
        d = info.to_dict()
        assert d["node_id"] == "!test"
        assert d["long_name"] == "Test Node"
        assert len(d["channels"]) == 1
        assert d["channels"][0]["name"] == "primary"

    def test_channel_info_to_dict(self):
        ch = ChannelInfo(index=1, name="admin", role="SECONDARY", psk="abc=")
        d = ch.to_dict()
        assert d["index"] == 1
        assert d["name"] == "admin"
        assert d["psk"] == "abc="

    def test_firmware_info_to_dict(self):
        fw = FirmwareInfo(
            current_version="2.5.18.e787254",
            latest_version="2.5.19.5f8df68",
            update_available=True,
            hw_model="HELTEC_V3",
        )
        d = fw.to_dict()
        assert d["update_available"] is True
        assert d["latest_version"] == "2.5.19.5f8df68"


class TestDeviceRole:
    def test_all_roles_are_strings(self):
        for role in DeviceRole:
            assert isinstance(role.value, str)

    def test_known_roles(self):
        assert DeviceRole.CLIENT.value == "CLIENT"
        assert DeviceRole.ROUTER.value == "ROUTER"
        assert DeviceRole.REPEATER.value == "REPEATER"
        assert DeviceRole.TRACKER.value == "TRACKER"

    def test_role_count(self):
        assert len(DeviceRole) == 13


# ---------------------------------------------------------------------------
# DeviceManager — device info reading
# ---------------------------------------------------------------------------

class TestGetDeviceInfo:
    def test_connected(self, connected_dm):
        info = asyncio.run(connected_dm.get_device_info())
        assert info.node_id == "!aabbccdd"
        assert info.long_name == "TestNode Alpha"
        assert info.short_name == "TNA"
        assert info.hw_model == "HELTEC_V3"
        assert info.firmware_version == "2.5.18.e787254"
        assert info.has_wifi is True
        assert info.has_bluetooth is True
        assert info.role == "CLIENT"
        assert info.region == "US"
        assert info.tx_power == 27

    def test_disconnected_returns_empty(self, disconnected_dm):
        info = asyncio.run(disconnected_dm.get_device_info())
        assert info.node_id == ""
        assert info.firmware_version == ""

    def test_channels_read(self, connected_dm):
        info = asyncio.run(connected_dm.get_device_info())
        assert info.num_channels == 2
        assert info.channels[0].name == "primary"
        assert info.channels[0].role == "PRIMARY"
        assert info.channels[1].name == "admin"
        assert info.channels[1].role == "SECONDARY"

    def test_handles_exception(self):
        """Interface that throws on getMyNodeInfo should return empty info."""
        conn = FakeConnection(connected=True)
        conn.interface.getMyNodeInfo.side_effect = RuntimeError("device disconnected")
        dm = DeviceManager(conn)
        info = asyncio.run(dm.get_device_info())
        assert info.node_id == ""


class TestGetChannels:
    def test_channels(self, connected_dm):
        channels = asyncio.run(connected_dm.get_channels())
        assert len(channels) == 2
        assert channels[0].index == 0
        assert channels[1].index == 1
        assert channels[1].uplink_enabled is True

    def test_disconnected(self, disconnected_dm):
        channels = asyncio.run(disconnected_dm.get_channels())
        assert channels == []


class TestGetModuleConfig:
    def test_reads_telemetry(self, connected_dm):
        modules = asyncio.run(connected_dm.get_module_config())
        assert "telemetry" in modules

    def test_disconnected(self, disconnected_dm):
        modules = asyncio.run(disconnected_dm.get_module_config())
        assert modules == {}


# ---------------------------------------------------------------------------
# DeviceManager — configuration
# ---------------------------------------------------------------------------

class TestSetOwner:
    def test_set_owner(self, connected_dm):
        ok = asyncio.run(connected_dm.set_owner("New Name", "NN"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.setOwner.assert_called_once_with(long_name="New Name", short_name="NN")

    def test_set_owner_long_only(self, connected_dm):
        ok = asyncio.run(connected_dm.set_owner("Just Long"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.setOwner.assert_called_once_with(long_name="Just Long")

    def test_set_owner_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_owner("X"))
        assert ok is False


class TestSetRole:
    def test_set_role_valid(self, connected_dm):
        ok = asyncio.run(connected_dm.set_role("ROUTER"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        # New pattern: sets field on localConfig then calls writeConfig
        assert node.localConfig.device.role == 2  # ROUTER = 2
        node.writeConfig.assert_called_with("device")

    def test_set_role_case_insensitive(self, connected_dm):
        ok = asyncio.run(connected_dm.set_role("tracker"))
        assert ok is True

    def test_set_role_invalid(self, connected_dm):
        ok = asyncio.run(connected_dm.set_role("INVALID_ROLE"))
        assert ok is False

    def test_set_role_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_role("CLIENT"))
        assert ok is False


class TestConfigureChannel:
    def test_configure_name(self, connected_dm):
        ok = asyncio.run(connected_dm.configure_channel(0, name="test-channel"))
        assert ok is True

    def test_invalid_index(self, connected_dm):
        ok = asyncio.run(connected_dm.configure_channel(8))
        assert ok is False
        ok = asyncio.run(connected_dm.configure_channel(-1))
        assert ok is False

    def test_remove_channel(self, connected_dm):
        # Removing channel 0 should fail
        ok = asyncio.run(connected_dm.remove_channel(0))
        assert ok is False

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.configure_channel(0, name="x"))
        assert ok is False


class TestSetLoraConfig:
    def test_set_tx_power(self, connected_dm):
        ok = asyncio.run(connected_dm.set_lora_config(tx_power=20))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.lora.tx_power == 20
        node.writeConfig.assert_called_with("lora")

    def test_set_region(self, connected_dm):
        ok = asyncio.run(connected_dm.set_lora_config(region="EU_868"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.lora.region == 3  # EU_868 = 3

    def test_set_nothing(self, connected_dm):
        ok = asyncio.run(connected_dm.set_lora_config())
        assert ok is True  # No-op is fine

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_lora_config(tx_power=10))
        assert ok is False


class TestSetPosition:
    def test_set_fixed_position(self, connected_dm):
        ok = asyncio.run(connected_dm.set_position(lat=37.749, lng=-122.419, altitude=16))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.setFixedPosition.assert_called_once_with(37.749, -122.419, 16)

    def test_set_gps_mode(self, connected_dm):
        ok = asyncio.run(connected_dm.set_position(gps_mode="DISABLED"))
        assert ok is True

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_position(lat=0, lng=0))
        assert ok is False


class TestSetWifi:
    def test_enable_wifi(self, connected_dm):
        ok = asyncio.run(connected_dm.set_wifi(enabled=True, ssid="MyNet", password="secret"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.network.wifi_enabled is True
        assert node.localConfig.network.wifi_ssid == "MyNet"
        assert node.localConfig.network.wifi_psk == "secret"
        node.writeConfig.assert_called_with("network")

    def test_disable_wifi(self, connected_dm):
        ok = asyncio.run(connected_dm.set_wifi(enabled=False))
        assert ok is True


class TestSetBluetooth:
    def test_enable(self, connected_dm):
        ok = asyncio.run(connected_dm.set_bluetooth(enabled=True))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.bluetooth.enabled is True
        node.writeConfig.assert_called_with("bluetooth")

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_bluetooth(enabled=True))
        assert ok is False


# ---------------------------------------------------------------------------
# DeviceManager — device control
# ---------------------------------------------------------------------------

class TestReboot:
    def test_reboot(self, connected_dm):
        ok = asyncio.run(connected_dm.reboot(seconds=3))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.reboot.assert_called_once_with(3)
        # Connection should be marked disconnected after reboot
        assert connected_dm.connection.is_connected is False

    def test_reboot_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.reboot())
        assert ok is False


class TestFactoryReset:
    def test_factory_reset(self, connected_dm):
        ok = asyncio.run(connected_dm.factory_reset())
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.factoryReset.assert_called_once()

    def test_factory_reset_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.factory_reset())
        assert ok is False


# ---------------------------------------------------------------------------
# DeviceManager — firmware
# ---------------------------------------------------------------------------

class TestFirmwareInfo:
    def test_firmware_info_connected(self, connected_dm):
        fw = asyncio.run(connected_dm.get_firmware_info())
        assert fw.current_version == "2.5.18.e787254"
        assert fw.hw_model == "HELTEC_V3"
        assert fw.latest_version == LATEST_STABLE
        # 2.5.18 is at index 1, LATEST (2.5.19) is at index 0 — update available
        assert fw.update_available is True

    def test_firmware_info_disconnected(self, disconnected_dm):
        fw = asyncio.run(disconnected_dm.get_firmware_info())
        assert fw.current_version == ""
        assert fw.update_available is False

    def test_firmware_tools_check(self, connected_dm):
        with patch("shutil.which", return_value=None):
            with patch("pathlib.Path.exists", return_value=False):
                fw = asyncio.run(connected_dm.get_firmware_info())
                assert fw.esptool_available is False
                assert fw.meshtastic_cli_available is False

    def test_firmware_tools_available(self, connected_dm):
        def fake_which(name):
            if name == "meshtastic":
                return "/usr/bin/meshtastic"
            return None
        with patch("shutil.which", side_effect=fake_which):
            fw = asyncio.run(connected_dm.get_firmware_info())
            assert fw.meshtastic_cli_available is True

    def test_unknown_version_marks_update(self):
        """If current version is not in our list, assume update available."""
        conn = FakeConnection(connected=True)
        # Set an unknown firmware version
        metadata = SimpleNamespace(
            firmware_version="1.0.0.unknown",
            has_wifi=False,
            has_bluetooth=False,
            has_ethernet=False,
            role="CLIENT",
            reboot_count=0,
        )
        conn.interface.getMetadata.return_value = metadata
        conn.interface.metadata = metadata
        dm = DeviceManager(conn)
        fw = asyncio.run(dm.get_firmware_info())
        assert fw.update_available is True


class TestFlashFirmware:
    def test_no_port_no_flasher(self):
        """With no flasher and no port, falls back to error."""
        conn = FakeConnection(connected=False)
        conn.port = ""
        dm = DeviceManager(conn)
        with patch.object(dm, "_get_flasher", return_value=None):
            result = asyncio.run(dm.flash_firmware("/tmp/firmware.bin"))
            assert result["success"] is False

    def test_flash_fallback_no_tools(self, connected_dm):
        """Without flasher and without CLI tools, returns error."""
        with patch.object(connected_dm, "_get_flasher", return_value=None):
            with patch("shutil.which", return_value=None):
                result = asyncio.run(connected_dm.flash_firmware("/tmp/firmware.bin"))
                assert result["success"] is False

    def test_flash_fallback_with_meshtastic_cli(self, connected_dm):
        """Falls back to meshtastic CLI when flasher unavailable."""
        with patch.object(connected_dm, "_get_flasher", return_value=None):
            with patch("shutil.which") as mock_which:
                mock_which.side_effect = lambda n: "/usr/bin/meshtastic" if n == "meshtastic" else None
                with patch.object(connected_dm, "_run_subprocess") as mock_sub:
                    mock_sub.return_value = {"success": True, "output": "Done"}
                    result = asyncio.run(connected_dm.flash_firmware("/tmp/fw.bin", port="/dev/ttyUSB0"))
                    assert result["success"] is True
                    mock_sub.assert_called_once()
                    cmd = mock_sub.call_args[0][0]
                    assert cmd[0] == "/usr/bin/meshtastic"
                    assert "--flash-firmware" in cmd

    def test_flash_fallback_with_esptool(self, connected_dm):
        """Falls back to esptool when flasher unavailable."""
        with patch.object(connected_dm, "_get_flasher", return_value=None):
            with patch("shutil.which") as mock_which:
                def which_side(n):
                    if n == "esptool.py":
                        return "/usr/bin/esptool.py"
                    return None
                mock_which.side_effect = which_side
                with patch.object(connected_dm, "_run_subprocess") as mock_sub:
                    mock_sub.return_value = {"success": True, "output": "Done"}
                    result = asyncio.run(connected_dm.flash_firmware("/tmp/fw.bin"))
                    assert result["success"] is True
                    cmd = mock_sub.call_args[0][0]
                    assert cmd[0] == "/usr/bin/esptool.py"
                    assert "write_flash" in cmd


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_bytes_to_base64(self):
        assert _bytes_to_base64(b"\x01") == "AQ=="
        assert _bytes_to_base64(b"") == ""
        assert _bytes_to_base64(b"\xab\xcd") == "q80="

    def test_proto_to_dict_fallback(self):
        """Test the fallback dict conversion for non-protobuf objects."""
        obj = SimpleNamespace()
        obj.DESCRIPTOR = SimpleNamespace(
            fields=[
                SimpleNamespace(name="foo"),
                SimpleNamespace(name="bar"),
            ]
        )
        obj.foo = 42
        obj.bar = "hello"
        result = _proto_to_dict(obj)
        assert result["foo"] == 42
        assert result["bar"] == "hello"


# ---------------------------------------------------------------------------
# API routes (using FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestDeviceRoutes:
    """Test the FastAPI route factory with mock DeviceManager."""

    @pytest.fixture
    def client(self, connected_dm):
        """Create a FastAPI TestClient with device routes mounted."""
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not available")

        app = FastAPI()
        router = create_device_routes(connected_dm)
        app.include_router(router, prefix="/api/addons/meshtastic")
        return TestClient(app)

    def test_get_info(self, client):
        resp = client.get("/api/addons/meshtastic/device/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "!aabbccdd"
        assert data["long_name"] == "TestNode Alpha"
        assert data["firmware_version"] == "2.5.18.e787254"

    def test_get_channels(self, client):
        resp = client.get("/api/addons/meshtastic/device/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["channels"]) == 2

    def test_get_firmware(self, client):
        resp = client.get("/api/addons/meshtastic/device/firmware")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_version" in data
        assert "update_available" in data

    def test_get_modules(self, client):
        resp = client.get("/api/addons/meshtastic/device/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert "modules" in data

    def test_post_config_owner(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "long_name": "NewName",
            "short_name": "NN",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "owner" in data["results"]

    def test_post_config_role(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "role": "ROUTER",
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["role"] is True

    def test_post_config_wifi(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "wifi_enabled": True,
            "wifi_ssid": "TestNet",
            "wifi_password": "pass123",
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["wifi"] is True

    def test_post_config_bluetooth(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "bluetooth_enabled": False,
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["bluetooth"] is True

    def test_post_config_position(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "lat": 37.749,
            "lng": -122.419,
            "altitude": 16,
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["position"] is True

    def test_post_config_lora(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "tx_power": 20,
            "region": "EU_868",
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["lora"] is True

    def test_post_config_empty_body(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={})
        assert resp.status_code == 400

    def test_post_config_channel(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "channel": {"index": 0, "name": "new-primary"},
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["channel"] is True

    def test_post_config_channel_missing_index(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "channel": {"name": "no-index"},
        })
        assert resp.status_code == 400

    def test_reboot(self, client):
        resp = client.post("/api/addons/meshtastic/device/reboot", json={"delay": 3})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_reboot_default_delay(self, client):
        resp = client.post("/api/addons/meshtastic/device/reboot")
        assert resp.status_code == 200

    def test_factory_reset(self, client):
        resp = client.post("/api/addons/meshtastic/device/factory-reset")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_flash_empty_body(self, client):
        """Empty body triggers flash_latest which fails without device."""
        resp = client.post("/api/addons/meshtastic/device/flash", json={})
        # Fails gracefully (500 because no device, not 400)
        assert resp.status_code == 500

    def test_post_display_config(self, client):
        resp = client.post("/api/addons/meshtastic/device/display", json={
            "screen_on_secs": 60,
            "flip_screen": True,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_post_power_config(self, client):
        resp = client.post("/api/addons/meshtastic/device/power", json={
            "is_power_saving": True,
            "on_battery_shutdown_after_secs": 3600,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_post_mqtt_config(self, client):
        resp = client.post("/api/addons/meshtastic/device/mqtt", json={
            "enabled": True,
            "address": "mqtt.example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_post_telemetry_config(self, client):
        resp = client.post("/api/addons/meshtastic/device/telemetry", json={
            "device_update_interval": 300,
            "environment_measurement_enabled": True,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_channel_url(self, client):
        resp = client.get("/api/addons/meshtastic/device/channel-url")
        assert resp.status_code == 200
        assert "url" in resp.json()

    def test_post_channel_url(self, client):
        resp = client.post("/api/addons/meshtastic/device/channel-url", json={
            "url": "https://meshtastic.org/e/#test",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_post_channel_url_missing(self, client):
        resp = client.post("/api/addons/meshtastic/device/channel-url", json={})
        assert resp.status_code == 400

    def test_shutdown(self, client):
        resp = client.post("/api/addons/meshtastic/device/shutdown")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_export_config(self, client):
        resp = client.get("/api/addons/meshtastic/device/export")
        assert resp.status_code == 200

    def test_post_config_display(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "screen_on_secs": 30,
            "flip_screen": True,
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["display"] is True

    def test_post_config_power(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "is_power_saving": True,
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["power"] is True

    def test_post_config_mqtt(self, client):
        resp = client.post("/api/addons/meshtastic/device/config", json={
            "mqtt_enabled": True,
            "mqtt_address": "mqtt.local",
        })
        assert resp.status_code == 200
        assert resp.json()["results"]["mqtt"] is True


# ---------------------------------------------------------------------------
# DeviceManager — new config methods
# ---------------------------------------------------------------------------

class TestSetDisplayConfig:
    def test_set_display(self, connected_dm):
        ok = asyncio.run(connected_dm.set_display_config(
            screen_on_secs=60, flip_screen=True,
        ))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.display.screen_on_secs == 60
        assert node.localConfig.display.flip_screen is True
        node.writeConfig.assert_called_with("display")

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_display_config(screen_on_secs=30))
        assert ok is False


class TestSetPowerConfig:
    def test_set_power(self, connected_dm):
        ok = asyncio.run(connected_dm.set_power_config(
            is_power_saving=True, on_battery_shutdown_after_secs=3600,
        ))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig.power.is_power_saving is True
        assert node.localConfig.power.on_battery_shutdown_after_secs == 3600
        node.writeConfig.assert_called_with("power")

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_power_config(is_power_saving=True))
        assert ok is False


class TestSetMqttConfig:
    def test_set_mqtt(self, connected_dm):
        ok = asyncio.run(connected_dm.set_mqtt_config(
            enabled=True, address="mqtt.local", json_enabled=True,
        ))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        assert node.localConfig is not None
        node.writeConfig.assert_called_with("mqtt")

    def test_set_mqtt_nothing(self, connected_dm):
        ok = asyncio.run(connected_dm.set_mqtt_config())
        assert ok is True

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_mqtt_config(enabled=True))
        assert ok is False


class TestSetTelemetryConfig:
    def test_set_telemetry(self, connected_dm):
        ok = asyncio.run(connected_dm.set_telemetry_config(
            device_update_interval=300,
            environment_measurement_enabled=True,
        ))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.writeConfig.assert_called_with("telemetry")

    def test_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_telemetry_config(device_update_interval=300))
        assert ok is False


class TestChannelUrl:
    def test_get_url(self, connected_dm):
        url = asyncio.run(connected_dm.get_channel_url())
        # MagicMock returns a MagicMock by default, just check it doesn't crash
        assert url is not None

    def test_get_url_disconnected(self, disconnected_dm):
        url = asyncio.run(disconnected_dm.get_channel_url())
        assert url == ""

    def test_set_url(self, connected_dm):
        ok = asyncio.run(connected_dm.set_channel_url("https://meshtastic.org/e/#test"))
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.setURL.assert_called_once_with("https://meshtastic.org/e/#test")

    def test_set_url_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.set_channel_url("https://meshtastic.org/e/#test"))
        assert ok is False


class TestShutdown:
    def test_shutdown(self, connected_dm):
        ok = asyncio.run(connected_dm.shutdown())
        assert ok is True
        node = connected_dm.connection.interface.localNode
        node.shutdown.assert_called_once()
        assert connected_dm.connection.is_connected is False

    def test_shutdown_disconnected(self, disconnected_dm):
        ok = asyncio.run(disconnected_dm.shutdown())
        assert ok is False


class TestExportConfig:
    def test_export(self, connected_dm):
        config = asyncio.run(connected_dm.export_config())
        assert isinstance(config, dict)
        assert "channels" in config

    def test_export_disconnected(self, disconnected_dm):
        config = asyncio.run(disconnected_dm.export_config())
        assert config == {}


class TestImportConfig:
    def test_import(self, connected_dm):
        results = asyncio.run(connected_dm.import_config({
            "channel_url": "https://meshtastic.org/e/#test",
        }))
        assert isinstance(results, dict)

    def test_import_disconnected(self, disconnected_dm):
        results = asyncio.run(disconnected_dm.import_config({"device": {}}))
        assert results == {}


class TestNewDeviceRoles:
    def test_router_late(self):
        assert DeviceRole.ROUTER_LATE.value == "ROUTER_LATE"

    def test_client_base(self):
        assert DeviceRole.CLIENT_BASE.value == "CLIENT_BASE"

    def test_set_router_late(self, connected_dm):
        ok = asyncio.run(connected_dm.set_role("ROUTER_LATE"))
        assert ok is True

    def test_set_client_base(self, connected_dm):
        ok = asyncio.run(connected_dm.set_role("CLIENT_BASE"))
        assert ok is True


# ---------------------------------------------------------------------------
# Integration: DeviceManager wired into addon
# ---------------------------------------------------------------------------

class TestAddonIntegration:
    def test_addon_has_device_manager_attr(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert hasattr(addon, "device_manager")

    def test_device_manager_import(self):
        from meshtastic_addon import DeviceManager
        dm = DeviceManager(FakeConnection())
        assert dm is not None
