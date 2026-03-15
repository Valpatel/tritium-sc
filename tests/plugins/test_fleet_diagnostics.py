# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for FleetDashboard remote diagnostics feature."""

import time

import pytest
from unittest.mock import MagicMock

# Ensure plugins dir is on sys.path (conftest handles this)
from fleet_dashboard.plugin import FleetDashboardPlugin


class FakeEventBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, data=None, **kwargs):
        self.published.append((topic, data))

    def subscribe(self, *args, **kwargs):
        pass


class FakeApp:
    def include_router(self, router):
        pass


@pytest.fixture
def plugin():
    """Create a FleetDashboardPlugin configured for testing."""
    p = FleetDashboardPlugin()
    p._event_bus = FakeEventBus()
    p._app = FakeApp()
    p._logger = MagicMock()
    p._running = True

    # Add a test device
    p._devices["test-device-1"] = {
        "device_id": "test-device-1",
        "name": "Test Node Alpha",
        "ip": "192.168.1.100",
        "battery": 85,
        "last_seen": time.time(),
        "ble_count": 5,
        "wifi_count": 3,
    }
    return p


class TestRequestDiagnostics:
    def test_request_known_device(self, plugin):
        result = plugin.request_diagnostics("test-device-1")
        assert result["status"] == "requested"
        assert result["device_id"] == "test-device-1"
        assert "heap" in result["sections"]

    def test_request_unknown_device(self, plugin):
        result = plugin.request_diagnostics("nonexistent-device")
        assert "error" in result

    def test_request_publishes_event(self, plugin):
        plugin.request_diagnostics("test-device-1")
        events = plugin._event_bus.published
        assert len(events) >= 1
        topic, data = events[-1]
        assert topic == "fleet.command"
        assert data["data"]["command_type"] == "diag_dump"

    def test_request_custom_sections(self, plugin):
        result = plugin.request_diagnostics("test-device-1", sections=["heap", "wifi"])
        assert result["sections"] == ["heap", "wifi"]


class TestOnDiagResponse:
    def test_stores_diagnostic_data(self, plugin):
        diag_data = {
            "device_id": "test-device-1",
            "free_heap": 120000,
            "min_free_heap": 80000,
            "free_psram": 4000000,
            "largest_free_block": 100000,
            "wifi_connected": True,
            "wifi_ssid": "TritiumNet",
            "wifi_rssi": -52,
            "ip": "192.168.1.100",
            "wifi_channel": 6,
            "ble_enabled": False,
            "ble_devices_found": 0,
            "i2c_devices_found": 3,
            "i2c_errors": 0,
            "nvs_free_entries": 200,
            "nvs_used_entries": 50,
            "nvs_total_entries": 250,
            "uptime_s": 7200,
            "firmware": "1.5.0",
            "board_type": "touch-lcd-43c",
            "reboot_count": 1,
            "loop_time_us": 1500,
        }
        plugin._on_diag_response(diag_data)

        stored = plugin.get_diagnostics("test-device-1")
        assert stored is not None
        assert stored["status"] == "received"
        assert stored["heap"]["free_heap"] == 120000
        assert stored["wifi"]["connected"] is True
        assert stored["wifi"]["ssid"] == "TritiumNet"
        assert stored["ble"]["enabled"] is False
        assert stored["i2c"]["devices_found"] == 3
        assert stored["nvs"]["used_entries"] == 50
        assert stored["system"]["firmware"] == "1.5.0"
        assert stored["system"]["uptime_s"] == 7200

    def test_no_device_id_ignored(self, plugin):
        plugin._on_diag_response({"free_heap": 100000})
        assert plugin.get_diagnostics("") is None


class TestGetDiagnostics:
    def test_no_data(self, plugin):
        assert plugin.get_diagnostics("test-device-1") is None

    def test_after_response(self, plugin):
        plugin._on_diag_response({
            "device_id": "test-device-1",
            "free_heap": 100000,
        })
        diag = plugin.get_diagnostics("test-device-1")
        assert diag is not None
        assert diag["heap"]["free_heap"] == 100000


class TestGetAllDiagnostics:
    def test_empty(self, plugin):
        assert plugin.get_all_diagnostics() == {}

    def test_multiple_devices(self, plugin):
        plugin._on_diag_response({"device_id": "dev-a", "free_heap": 100000})
        plugin._on_diag_response({"device_id": "dev-b", "free_heap": 80000})
        all_diag = plugin.get_all_diagnostics()
        assert len(all_diag) == 2
        assert "dev-a" in all_diag
        assert "dev-b" in all_diag


class TestDiagEventHandling:
    def test_diag_response_event_handled(self, plugin):
        """Verify the _handle_event method routes fleet.diag_response events."""
        event = {
            "type": "fleet.diag_response",
            "data": {
                "device_id": "test-device-1",
                "free_heap": 90000,
                "wifi_connected": True,
            },
        }
        plugin._handle_event(event)

        diag = plugin.get_diagnostics("test-device-1")
        assert diag is not None
        assert diag["heap"]["free_heap"] == 90000
