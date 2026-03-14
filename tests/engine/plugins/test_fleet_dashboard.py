# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Fleet Dashboard plugin."""

import time

import pytest

from engine.plugins.base import PluginInterface


@pytest.mark.unit
class TestFleetDashboardPlugin:
    """Verify Fleet Dashboard plugin interface and device registry."""

    def test_implements_plugin_interface(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_identity(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        assert plugin.plugin_id == "tritium.fleet-dashboard"
        assert plugin.name == "Fleet Dashboard"
        assert plugin.version == "1.0.0"

    def test_capabilities(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        caps = plugin.capabilities
        assert "data_source" in caps
        assert "routes" in caps
        assert "ui" in caps

    def test_devices_start_empty(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        assert plugin.get_devices() == []

    def test_get_device_returns_none_for_unknown(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        assert plugin.get_device("nonexistent") is None

    def test_heartbeat_registers_device(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "tritium-01",
            "name": "Edge Node 1",
            "ip": "192.168.1.10",
            "battery_pct": 85,
            "uptime_s": 3600,
            "ble_count": 5,
            "wifi_count": 3,
        })
        devices = plugin.get_devices()
        assert len(devices) == 1
        dev = devices[0]
        assert dev["device_id"] == "tritium-01"
        assert dev["name"] == "Edge Node 1"
        assert dev["ip"] == "192.168.1.10"
        assert dev["battery"] == 85
        assert dev["uptime"] == 3600
        assert dev["ble_count"] == 5
        assert dev["wifi_count"] == 3
        assert dev["status"] == "online"

    def test_get_device_by_id(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "tritium-02",
            "name": "Node 2",
            "ip": "192.168.1.20",
        })
        dev = plugin.get_device("tritium-02")
        assert dev is not None
        assert dev["device_id"] == "tritium-02"

    def test_heartbeat_updates_existing_device(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "tritium-01",
            "battery_pct": 80,
        })
        plugin._on_heartbeat({
            "device_id": "tritium-01",
            "battery_pct": 75,
        })
        devices = plugin.get_devices()
        assert len(devices) == 1
        assert devices[0]["battery"] == 75

    def test_multiple_devices(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        for i in range(3):
            plugin._on_heartbeat({
                "device_id": f"node-{i}",
                "battery_pct": 90 - i * 10,
            })
        devices = plugin.get_devices()
        assert len(devices) == 3

    def test_summary_counts(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "online-node",
            "battery_pct": 80,
            "ble_count": 10,
            "wifi_count": 5,
        })
        summary = plugin.get_summary()
        assert summary["total"] == 1
        assert summary["online"] == 1
        assert summary["stale"] == 0
        assert summary["offline"] == 0
        assert summary["avg_battery"] == 80.0
        assert summary["total_ble_sightings"] == 10
        assert summary["total_wifi_sightings"] == 5

    def test_summary_no_battery(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "no-bat"})
        summary = plugin.get_summary()
        assert summary["avg_battery"] is None

    def test_stale_device_status(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "stale-node"})
        # Manually set last_seen to 90s ago
        plugin._devices["stale-node"]["last_seen"] = time.time() - 90
        devices = plugin.get_devices()
        assert devices[0]["status"] == "stale"

    def test_offline_device_status(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "offline-node"})
        plugin._devices["offline-node"]["last_seen"] = time.time() - 200
        devices = plugin.get_devices()
        assert devices[0]["status"] == "offline"

    def test_prune_stale_devices(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "old-node"})
        plugin._devices["old-node"]["last_seen"] = time.time() - 400
        plugin._prune_stale()
        assert len(plugin.get_devices()) == 0

    def test_prune_keeps_recent_devices(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "recent-node"})
        plugin._prune_stale()
        assert len(plugin.get_devices()) == 1

    def test_ble_update_updates_count(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "ble-node"})
        plugin._on_ble_update({
            "count": 12,
            "devices": [{"node_id": "ble-node", "mac": "AA:BB:CC:DD:EE:FF"}],
        })
        dev = plugin.get_device("ble-node")
        assert dev["ble_count"] == 12

    def test_heartbeat_without_device_id_ignored(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({})
        assert len(plugin.get_devices()) == 0

    def test_handle_event_dispatches_heartbeat(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._handle_event({
            "type": "fleet.heartbeat",
            "data": {"device_id": "evt-node", "battery_pct": 50},
        })
        assert len(plugin.get_devices()) == 1

    def test_handle_event_dispatches_ble_update(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "ble-evt-node"})
        plugin._handle_event({
            "type": "edge:ble_update",
            "data": {
                "count": 7,
                "devices": [{"node_id": "ble-evt-node"}],
            },
        })
        dev = plugin.get_device("ble-evt-node")
        assert dev["ble_count"] == 7

    def test_healthy_when_running(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._running = True
        assert plugin.healthy is True

    def test_not_healthy_when_stopped(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        assert plugin.healthy is False

    def test_loader_exports_class(self):
        from plugins.fleet_dashboard_loader import FleetDashboardPlugin as Loaded
        assert Loaded is not None
        plugin = Loaded()
        assert plugin.plugin_id == "tritium.fleet-dashboard"


@pytest.mark.unit
class TestFleetDashboardRoutes:
    """Verify Fleet Dashboard API routes."""

    def test_create_router_returns_router(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        from plugins.fleet_dashboard.routes import create_router
        plugin = FleetDashboardPlugin()
        router = create_router(plugin)
        assert router is not None
        assert router.prefix == "/api/fleet"

    def test_router_has_expected_routes(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        from plugins.fleet_dashboard.routes import create_router
        plugin = FleetDashboardPlugin()
        router = create_router(plugin)
        paths = [r.path for r in router.routes]
        assert "/api/fleet/devices" in paths
        assert "/api/fleet/devices/{device_id}" in paths
        assert "/api/fleet/summary" in paths
