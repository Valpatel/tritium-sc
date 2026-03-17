# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ConnectionManager — serial, TCP, BLE, and MQTT transports.

All tests mock the meshtastic library so no hardware is needed.
"""

import asyncio
import sys
import types
from unittest.mock import MagicMock, patch
import pytest

from meshtastic_addon.connection import (
    ConnectionManager,
    DEFAULT_SERIAL_TIMEOUT,
    DEFAULT_TCP_TIMEOUT,
    DEFAULT_BLE_TIMEOUT,
    DEFAULT_MQTT_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers: fake meshtastic modules
# ---------------------------------------------------------------------------

def _make_fake_interface(**kwargs):
    """Create a mock meshtastic interface with reasonable defaults."""
    iface = MagicMock()
    iface.nodes = {}
    iface.metadata = None
    iface.getMyNodeInfo.return_value = {
        "user": {
            "id": "!test1234",
            "longName": "TestNode",
            "shortName": "TN",
            "hwModel": "T_LORA_PAGER",
            "macaddr": "aa:bb:cc:dd:ee:ff",
        }
    }
    for k, v in kwargs.items():
        setattr(iface, k, v)
    return iface


@pytest.fixture(autouse=True)
def _patch_meshtastic_modules():
    """Ensure meshtastic submodules are importable as fakes."""
    # Create the parent meshtastic module if it doesn't exist or is incomplete
    parent = types.ModuleType("meshtastic")
    serial_mod = types.ModuleType("meshtastic.serial_interface")
    serial_mod.SerialInterface = MagicMock(return_value=_make_fake_interface())
    tcp_mod = types.ModuleType("meshtastic.tcp_interface")
    tcp_mod.TCPInterface = MagicMock(return_value=_make_fake_interface())
    ble_mod = types.ModuleType("meshtastic.ble_interface")
    ble_mod.BLEInterface = MagicMock(return_value=_make_fake_interface())
    mqtt_mod = types.ModuleType("meshtastic.mqtt_interface")
    mqtt_mod.MQTTInterface = MagicMock(return_value=_make_fake_interface())

    parent.serial_interface = serial_mod
    parent.tcp_interface = tcp_mod
    parent.ble_interface = ble_mod
    parent.mqtt_interface = mqtt_mod

    saved = {}
    keys = [
        "meshtastic", "meshtastic.serial_interface",
        "meshtastic.tcp_interface", "meshtastic.ble_interface",
        "meshtastic.mqtt_interface",
    ]
    for k in keys:
        saved[k] = sys.modules.get(k)

    sys.modules["meshtastic"] = parent
    sys.modules["meshtastic.serial_interface"] = serial_mod
    sys.modules["meshtastic.tcp_interface"] = tcp_mod
    sys.modules["meshtastic.ble_interface"] = ble_mod
    sys.modules["meshtastic.mqtt_interface"] = mqtt_mod

    yield {
        "serial": serial_mod,
        "tcp": tcp_mod,
        "ble": ble_mod,
        "mqtt": mqtt_mod,
        "parent": parent,
    }

    # Restore
    for k in keys:
        if saved[k] is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = saved[k]


def _get_serial_mock():
    return sys.modules["meshtastic.serial_interface"].SerialInterface


def _get_tcp_mock():
    return sys.modules["meshtastic.tcp_interface"].TCPInterface


def _get_ble_mock():
    return sys.modules["meshtastic.ble_interface"].BLEInterface


def _get_mqtt_mock():
    return sys.modules["meshtastic.mqtt_interface"].MQTTInterface


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:
    def test_create_defaults(self):
        cm = ConnectionManager()
        assert not cm.is_connected
        assert cm.transport_type == "none"
        assert cm.port == ""
        assert cm.interface is None
        assert cm.device_info == {}

    def test_disconnect_noop(self):
        cm = ConnectionManager()
        asyncio.run(cm.disconnect())
        assert not cm.is_connected
        assert cm.transport_type == "none"

    def test_get_nodes_when_disconnected(self):
        cm = ConnectionManager()
        nodes = asyncio.run(cm.get_nodes())
        assert nodes == {}

    def test_send_text_when_disconnected(self):
        cm = ConnectionManager()
        ok = asyncio.run(cm.send_text("hello"))
        assert ok is False


# ---------------------------------------------------------------------------
# Default timeout constants
# ---------------------------------------------------------------------------

class TestTimeoutDefaults:
    def test_serial_timeout_is_60s(self):
        assert DEFAULT_SERIAL_TIMEOUT == 60.0

    def test_tcp_timeout_is_30s(self):
        assert DEFAULT_TCP_TIMEOUT == 30.0

    def test_ble_timeout_is_45s(self):
        assert DEFAULT_BLE_TIMEOUT == 45.0

    def test_mqtt_timeout_is_15s(self):
        assert DEFAULT_MQTT_TIMEOUT == 15.0


# ---------------------------------------------------------------------------
# Serial transport
# ---------------------------------------------------------------------------

class TestSerialConnect:
    def test_serial_nonexistent_port(self):
        cm = ConnectionManager()
        asyncio.run(cm.connect_serial("/dev/ttyNONEXISTENT"))
        assert not cm.is_connected

    def test_serial_connect_success(self, tmp_path):
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_serial(str(fake_port), timeout=10))

        assert cm.is_connected
        assert cm.transport_type == "serial"
        assert cm.port == str(fake_port)
        assert cm.device_info["long_name"] == "TestNode"

    def test_serial_passes_noNodes(self, tmp_path):
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_serial(str(fake_port), timeout=10, noNodes=True))

        assert cm.is_connected
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("noNodes") is True

    def test_serial_passes_timeout_kwarg(self, tmp_path):
        """SerialInterface receives timeout kwarg (the correct param name per meshtastic lib)."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_serial(str(fake_port), timeout=60))

        call_kwargs = mock_cls.call_args.kwargs
        assert "timeout" in call_kwargs

    def test_serial_disconnect_cleans_up(self, tmp_path):
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_serial(str(fake_port), timeout=10))
        assert cm.is_connected

        asyncio.run(cm.disconnect())
        assert not cm.is_connected
        assert cm.interface is None
        iface.close.assert_called()

    def test_serial_retries_on_failure(self, tmp_path):
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()

        call_count = 0

        def fail_then_succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first attempt fails")
            return iface

        mock_cls.side_effect = fail_then_succeed

        cm = ConnectionManager()
        asyncio.run(cm.connect_serial(str(fake_port), timeout=10, retries=1))
        assert cm.is_connected
        assert call_count == 2

    def test_serial_emits_event(self, tmp_path):
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        bus = MagicMock()
        cm = ConnectionManager(event_bus=bus)
        asyncio.run(cm.connect_serial(str(fake_port), timeout=10))
        assert cm.is_connected
        bus.publish.assert_called_once()
        args = bus.publish.call_args
        assert args[0][0] == "meshtastic:connected"
        assert args[0][1]["transport"] == "serial"


# ---------------------------------------------------------------------------
# TCP transport
# ---------------------------------------------------------------------------

class TestTCPConnect:
    def test_tcp_connect_success(self):
        iface = _make_fake_interface()
        mock_cls = _get_tcp_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_tcp("192.168.1.100", timeout=10))

        assert cm.is_connected
        assert cm.transport_type == "tcp"
        assert cm.port == "192.168.1.100:4403"

    def test_tcp_passes_timeout_kwarg(self):
        iface = _make_fake_interface()
        mock_cls = _get_tcp_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_tcp("192.168.1.100", timeout=10))

        call_kwargs = mock_cls.call_args.kwargs
        assert "timeout" in call_kwargs

    def test_tcp_failure_stays_disconnected(self):
        mock_cls = _get_tcp_mock()
        mock_cls.reset_mock()
        mock_cls.side_effect = ConnectionRefusedError("refused")

        cm = ConnectionManager()
        asyncio.run(cm.connect_tcp("192.168.1.100", timeout=5))
        assert not cm.is_connected


# ---------------------------------------------------------------------------
# BLE transport
# ---------------------------------------------------------------------------

class TestBLEConnect:
    def test_ble_connect_with_address(self):
        iface = _make_fake_interface()
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=10))

        assert cm.is_connected
        assert cm.transport_type == "ble"
        assert cm.port == "AA:BB:CC:DD:EE:FF"
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["address"] == "AA:BB:CC:DD:EE:FF"
        assert call_kwargs["noNodes"] is False

    def test_ble_connect_auto_discover(self):
        iface = _make_fake_interface()
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_ble("", timeout=10))

        assert cm.is_connected
        assert cm.transport_type == "ble"
        assert cm.port == "auto"
        call_kwargs = mock_cls.call_args.kwargs
        assert "address" not in call_kwargs

    def test_ble_connect_with_noNodes(self):
        iface = _make_fake_interface()
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=10, noNodes=True))

        assert cm.is_connected
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["noNodes"] is True

    def test_ble_import_error(self):
        """BLE should gracefully fail if bleak is not installed."""
        # Temporarily make ble_interface unimportable
        saved = sys.modules.get("meshtastic.ble_interface")
        sys.modules["meshtastic.ble_interface"] = None
        try:
            # Need to also remove it from the parent module attribute
            parent = sys.modules["meshtastic"]
            parent.ble_interface = None
            cm = ConnectionManager()
            asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=5))
            assert not cm.is_connected
        finally:
            sys.modules["meshtastic.ble_interface"] = saved
            if saved:
                sys.modules["meshtastic"].ble_interface = saved

    def test_ble_timeout(self):
        import time as _time

        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()

        def slow_connect(**kwargs):
            _time.sleep(5)
            return _make_fake_interface()

        mock_cls.side_effect = slow_connect
        cm = ConnectionManager()
        asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=0.5))
        assert not cm.is_connected

    def test_ble_failure(self):
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.side_effect = RuntimeError("BLE scan failed")

        cm = ConnectionManager()
        asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=5))
        assert not cm.is_connected

    def test_ble_emits_event(self):
        iface = _make_fake_interface()
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        bus = MagicMock()
        cm = ConnectionManager(event_bus=bus)
        asyncio.run(cm.connect_ble("AA:BB:CC:DD:EE:FF", timeout=10))
        assert cm.is_connected
        bus.publish.assert_called_once()
        args = bus.publish.call_args
        assert args[0][0] == "meshtastic:connected"
        assert args[0][1]["transport"] == "ble"


# ---------------------------------------------------------------------------
# MQTT transport
# ---------------------------------------------------------------------------

class TestMQTTConnect:
    def test_mqtt_connect_defaults(self):
        iface = _make_fake_interface()
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_mqtt())

        assert cm.is_connected
        assert cm.transport_type == "mqtt"
        assert cm.port == "mqtt.meshtastic.org:1883"
        assert cm.device_info["short_name"] == "MQTT"
        assert "mqtt_topic" in cm.device_info

        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["hostname"] == "mqtt.meshtastic.org"
        assert call_kwargs["port"] == 1883
        assert call_kwargs["root_topic"] == "msh/US/2/e/#"
        assert call_kwargs["username"] == "meshdev"
        assert call_kwargs["password"] == "large4cats"

    def test_mqtt_connect_custom(self):
        iface = _make_fake_interface()
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_mqtt(
            host="my-broker.local",
            port=8883,
            topic="msh/EU/1/e/#",
            username="myuser",
            password="mypass",
        ))

        assert cm.is_connected
        assert cm.port == "my-broker.local:8883"
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["hostname"] == "my-broker.local"
        assert call_kwargs["port"] == 8883
        assert call_kwargs["root_topic"] == "msh/EU/1/e/#"
        assert call_kwargs["username"] == "myuser"
        assert call_kwargs["password"] == "mypass"

    def test_mqtt_import_error(self):
        saved = sys.modules.get("meshtastic.mqtt_interface")
        sys.modules["meshtastic.mqtt_interface"] = None
        try:
            parent = sys.modules["meshtastic"]
            parent.mqtt_interface = None
            cm = ConnectionManager()
            asyncio.run(cm.connect_mqtt(timeout=5))
            assert not cm.is_connected
        finally:
            sys.modules["meshtastic.mqtt_interface"] = saved
            if saved:
                sys.modules["meshtastic"].mqtt_interface = saved

    def test_mqtt_failure(self):
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.side_effect = ConnectionRefusedError("refused")

        cm = ConnectionManager()
        asyncio.run(cm.connect_mqtt(host="bad-host", timeout=5))
        assert not cm.is_connected

    def test_mqtt_timeout(self):
        import time as _time

        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()

        def slow_connect(**kwargs):
            _time.sleep(5)
            return _make_fake_interface()

        mock_cls.side_effect = slow_connect
        cm = ConnectionManager()
        asyncio.run(cm.connect_mqtt(timeout=0.5))
        assert not cm.is_connected

    def test_mqtt_emits_event(self):
        iface = _make_fake_interface()
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        bus = MagicMock()
        cm = ConnectionManager(event_bus=bus)
        asyncio.run(cm.connect_mqtt(timeout=10))
        assert cm.is_connected
        bus.publish.assert_called_once()
        args = bus.publish.call_args
        assert args[0][0] == "meshtastic:connected"
        assert args[0][1]["transport"] == "mqtt"
        assert args[0][1]["topic"] == "msh/US/2/e/#"

    def test_mqtt_disconnect(self):
        iface = _make_fake_interface()
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        asyncio.run(cm.connect_mqtt(timeout=10))
        assert cm.is_connected

        asyncio.run(cm.disconnect())
        assert not cm.is_connected
        assert cm.interface is None
        assert cm.transport_type == "none"


# ---------------------------------------------------------------------------
# Auto-connect logic
# ---------------------------------------------------------------------------

class TestAutoConnect:
    def test_auto_connect_no_devices(self):
        """auto_connect with no devices should end in disconnected mode."""
        cm = ConnectionManager()
        cm._find_serial_device = lambda: None
        with patch("pathlib.Path.exists", return_value=False):
            asyncio.run(cm.auto_connect())
        assert not cm.is_connected

    def test_auto_connect_tries_mqtt_from_env(self, monkeypatch):
        """auto_connect should try MQTT if env var is set."""
        monkeypatch.setenv("MESHTASTIC_MQTT_HOST", "test-broker.local")

        iface = _make_fake_interface()
        mock_cls = _get_mqtt_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        cm._find_serial_device = lambda: None
        with patch("pathlib.Path.exists", return_value=False):
            asyncio.run(cm.auto_connect())

        assert cm.is_connected
        assert cm.transport_type == "mqtt"

    def test_auto_connect_tries_ble_from_env(self, monkeypatch):
        """auto_connect should try BLE if env var is set."""
        monkeypatch.setenv("MESHTASTIC_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")

        iface = _make_fake_interface()
        mock_cls = _get_ble_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        cm._find_serial_device = lambda: None
        with patch("pathlib.Path.exists", return_value=False):
            asyncio.run(cm.auto_connect())

        assert cm.is_connected
        assert cm.transport_type == "ble"

    def test_auto_connect_serial_fast_then_full(self, tmp_path):
        """auto_connect tries noNodes=True first for fast connect."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()
        mock_cls.return_value = iface

        cm = ConnectionManager()
        cm._find_serial_device = lambda: str(fake_port)
        asyncio.run(cm.auto_connect())

        # Should have connected on the first (fast) attempt
        assert cm.is_connected
        assert cm.transport_type == "serial"
        # First call should have noNodes=True
        first_call = mock_cls.call_args_list[0]
        assert first_call.kwargs.get("noNodes") is True

    def test_auto_connect_serial_fast_fails_then_full(self, tmp_path):
        """If fast connect fails, auto_connect retries with full config."""
        fake_port = tmp_path / "ttyACM0"
        fake_port.touch()

        iface = _make_fake_interface()
        mock_cls = _get_serial_mock()
        mock_cls.reset_mock()

        call_count = 0

        def fail_fast_succeed_full(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("noNodes"):
                raise RuntimeError("fast connect failed")
            return iface

        mock_cls.side_effect = fail_fast_succeed_full

        cm = ConnectionManager()
        cm._find_serial_device = lambda: str(fake_port)
        asyncio.run(cm.auto_connect())

        assert cm.is_connected
        assert cm.transport_type == "serial"
        # First call was noNodes=True (failed), subsequent calls were full
        assert call_count >= 2


# ---------------------------------------------------------------------------
# Close interface helper
# ---------------------------------------------------------------------------

class TestCloseInterface:
    def test_close_interface_with_interface(self):
        cm = ConnectionManager()
        cm.interface = MagicMock()
        cm._close_interface()
        assert cm.interface is None

    def test_close_interface_without_interface(self):
        cm = ConnectionManager()
        cm._close_interface()  # should not raise
        assert cm.interface is None

    def test_close_interface_handles_exception(self):
        cm = ConnectionManager()
        iface = MagicMock()
        iface.close.side_effect = RuntimeError("close failed")
        cm.interface = iface
        cm._close_interface()  # should not raise
        assert cm.interface is None
