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
        assert "/api/fleet/health-summary" in paths
        assert "/api/fleet/lifecycle" in paths
        assert "/api/fleet/devices/{device_id}/state" in paths
        assert "/api/fleet/devices/{device_id}/lifecycle" in paths


@pytest.mark.unit
class TestFleetHealthSummary:
    """Verify fleet health summary aggregation."""

    def test_empty_fleet_health(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        health = plugin.get_health_summary()
        assert health["total_devices"] == 0
        assert health["online"] == 0
        assert health["avg_battery_pct"] is None
        assert health["sensor_health"]["ble"] == 0

    def test_health_with_devices(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "node-1",
            "battery_pct": 80,
            "ble_count": 10,
            "wifi_count": 5,
        })
        plugin._on_heartbeat({
            "device_id": "node-2",
            "battery_pct": 60,
            "ble_count": 0,
            "wifi_count": 3,
        })
        health = plugin.get_health_summary()
        assert health["total_devices"] == 2
        assert health["online"] == 2
        assert health["avg_battery_pct"] == 70.0
        assert health["total_ble_sightings"] == 10
        assert health["total_wifi_sightings"] == 8
        assert health["sensor_health"]["ble"] == 1  # Only node-1 has BLE
        assert health["sensor_health"]["wifi"] == 2  # Both have WiFi

    def test_health_low_battery_count(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "low-bat", "battery_pct": 15})
        plugin._on_heartbeat({"device_id": "ok-bat", "battery_pct": 80})
        health = plugin.get_health_summary()
        assert health["low_battery_count"] == 1

    def test_health_lifecycle_counts(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({"device_id": "node-1"})
        plugin._on_heartbeat({"device_id": "node-2"})
        plugin.set_device_state("node-1", "active")
        # Must go provisioning -> active -> maintenance
        plugin.set_device_state("node-2", "active")
        plugin.set_device_state("node-2", "maintenance", reason="firmware update")
        health = plugin.get_health_summary()
        # node-1 set to active via lifecycle, node-2 set to maintenance
        assert health["lifecycle"]["active"] >= 1
        assert health["lifecycle"]["maintenance"] == 1


@pytest.mark.unit
class TestDeviceLifecycle:
    """Verify device lifecycle state management."""

    def test_set_device_state(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        result = plugin.set_device_state("dev-1", "active")
        assert result["state"] == "active"
        assert result["device_id"] == "dev-1"

    def test_valid_transition(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "active")
        result = plugin.set_device_state("dev-1", "maintenance", reason="scheduled")
        assert result["state"] == "maintenance"
        assert result["transition_count"] == 2  # provisioning->active, active->maintenance

    def test_invalid_transition(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "active")
        result = plugin.set_device_state("dev-1", "provisioning")
        assert "error" in result

    def test_invalid_state(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        result = plugin.set_device_state("dev-1", "bogus")
        assert "error" in result

    def test_lifecycle_history(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "active")
        plugin.set_device_state("dev-1", "maintenance")
        lc = plugin.get_device_lifecycle("dev-1")
        assert len(lc["history"]) == 2
        assert lc["history"][0]["from_state"] == "provisioning"
        assert lc["history"][0]["to_state"] == "active"
        assert lc["history"][1]["from_state"] == "active"
        assert lc["history"][1]["to_state"] == "maintenance"

    def test_get_all_lifecycle(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "active")
        plugin.set_device_state("dev-2", "active")
        states = plugin.get_all_lifecycle_states()
        assert len(states) == 2

    def test_heartbeat_with_lifecycle_state(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin._on_heartbeat({
            "device_id": "edge-01",
            "lifecycle_state": "active",
        })
        lc = plugin.get_device_lifecycle("edge-01")
        assert lc is not None
        assert lc["state"] == "active"

    def test_same_state_noop(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "active")
        result = plugin.set_device_state("dev-1", "active")
        assert result["state"] == "active"
        assert result["transition_count"] == 1  # Only the initial transition

    def test_error_to_maintenance(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "error")
        result = plugin.set_device_state("dev-1", "maintenance")
        assert result["state"] == "maintenance"

    def test_retired_to_provisioning(self):
        from plugins.fleet_dashboard.plugin import FleetDashboardPlugin
        plugin = FleetDashboardPlugin()
        plugin.set_device_state("dev-1", "retired")
        result = plugin.set_device_state("dev-1", "provisioning")
        assert result["state"] == "provisioning"
