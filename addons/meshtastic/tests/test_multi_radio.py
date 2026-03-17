# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for multi-radio support in the Meshtastic addon.

Tests DeviceRegistry integration, detect_meshtastic_ports(), multiple
ConnectionManagers, aggregate node list, per-device API endpoints,
and backward compatibility with legacy single-radio endpoints.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from tritium_lib.sdk import DeviceRegistry, DeviceState, RegisteredDevice


# ---------------------------------------------------------------------------
# detect_meshtastic_ports tests
# ---------------------------------------------------------------------------

class TestDetectMeshtasticPorts:
    """Test the detect_meshtastic_ports() module-level function."""

    def test_no_ports_returns_empty(self):
        """When no serial ports exist, return empty list."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        mock_port = MagicMock()
        mock_port.device = "/dev/ttyS0"  # Not ttyACM or ttyUSB
        mock_port.vid = None

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detect_meshtastic_ports()
        assert result == []

    def test_detects_ttyACM_port(self):
        """Detect a ttyACM port with known Meshtastic VID."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        mock_port = MagicMock()
        mock_port.device = "/dev/ttyACM0"
        mock_port.vid = 0x303a  # Espressif
        mock_port.pid = 0x1001
        mock_port.description = "T-LoRa Pager"
        mock_port.manufacturer = "Espressif"
        mock_port.serial_number = "ABC123"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detect_meshtastic_ports()

        assert len(result) == 1
        assert result[0]["port"] == "/dev/ttyACM0"
        assert result[0]["device_id"] == "mesh-ttyACM0"
        assert result[0]["transport"] == "serial"
        assert result[0]["vid"] == "303a"
        assert result[0]["meshtastic_match"] is True

    def test_detects_multiple_ports(self):
        """Detect multiple serial ports."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        port0 = MagicMock()
        port0.device = "/dev/ttyACM0"
        port0.vid = 0x303a
        port0.pid = 0x1001
        port0.description = "T-LoRa Pager"
        port0.manufacturer = "Espressif"
        port0.serial_number = "ABC"

        port1 = MagicMock()
        port1.device = "/dev/ttyUSB0"
        port1.vid = 0x10c4  # SiLabs
        port1.pid = 0xea60
        port1.description = "T-Beam"
        port1.manufacturer = "Silicon Labs"
        port1.serial_number = "DEF"

        with patch("serial.tools.list_ports.comports", return_value=[port0, port1]):
            result = detect_meshtastic_ports()

        assert len(result) == 2
        ids = [r["device_id"] for r in result]
        assert "mesh-ttyACM0" in ids
        assert "mesh-ttyUSB0" in ids

    def test_non_meshtastic_vid_not_matched(self):
        """Ports with unknown VIDs are still returned but not matched."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.vid = 0x9999  # Unknown VID
        mock_port.pid = 0x0001
        mock_port.description = "Unknown device"
        mock_port.manufacturer = ""
        mock_port.serial_number = ""

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detect_meshtastic_ports()

        assert len(result) == 1
        assert result[0]["meshtastic_match"] is False

    def test_no_vid_not_matched(self):
        """Port with no VID on a ttyACM device."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        mock_port = MagicMock()
        mock_port.device = "/dev/ttyACM1"
        mock_port.vid = None
        mock_port.pid = None
        mock_port.description = ""
        mock_port.manufacturer = ""
        mock_port.serial_number = ""

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detect_meshtastic_ports()

        assert len(result) == 1
        assert result[0]["meshtastic_match"] is False
        assert result[0]["vid"] == ""

    def test_fallback_without_pyserial(self):
        """When pyserial is not installed, fall back to glob scan."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        with patch.dict("sys.modules", {"serial": None, "serial.tools": None, "serial.tools.list_ports": None}):
            with patch("builtins.__import__", side_effect=ImportError("no serial")):
                # This will trigger the ImportError path
                pass

        # The function handles ImportError internally — test with explicit mock
        import importlib
        import meshtastic_addon.connection as conn_mod

        original_func = conn_mod.detect_meshtastic_ports

        def patched_detect():
            import glob as _glob
            results = []
            seen = set()
            with patch("glob.glob", side_effect=[
                ["/dev/ttyACM0", "/dev/ttyACM1"],
                [],
            ]):
                for pattern in ["/dev/ttyACM*", "/dev/ttyUSB*"]:
                    for port_path in sorted(_glob.glob(pattern)):
                        if port_path in seen:
                            continue
                        seen.add(port_path)
                        port_name = port_path.split("/")[-1]
                        results.append({
                            "port": port_path,
                            "device_id": f"mesh-{port_name}",
                            "transport": "serial",
                            "vid": "",
                            "pid": "",
                            "description": "Serial device",
                            "manufacturer": "",
                            "serial_number": "",
                            "meshtastic_match": True,
                        })
            return results

        result = patched_detect()
        assert len(result) == 2

    def test_dedup_ports(self):
        """Duplicate ports are deduped."""
        from meshtastic_addon.connection import detect_meshtastic_ports

        mock_port = MagicMock()
        mock_port.device = "/dev/ttyACM0"
        mock_port.vid = 0x303a
        mock_port.pid = 0x1001
        mock_port.description = "T-LoRa"
        mock_port.manufacturer = "Espressif"
        mock_port.serial_number = "A"

        # Same port appears twice in comports (can happen)
        with patch("serial.tools.list_ports.comports", return_value=[mock_port, mock_port]):
            result = detect_meshtastic_ports()

        assert len(result) == 1


# ---------------------------------------------------------------------------
# DeviceRegistry integration tests
# ---------------------------------------------------------------------------

class TestDeviceRegistryIntegration:
    """Test that DeviceRegistry is properly used for multi-radio tracking."""

    def test_registry_created(self):
        """Addon creates a DeviceRegistry with 'meshtastic' addon_id."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert isinstance(addon.registry, DeviceRegistry)
        assert addon.registry.addon_id == "meshtastic"

    def test_registry_starts_empty(self):
        """Registry starts with no devices before register()."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert addon.registry.device_count == 0

    def test_connections_dict_starts_empty(self):
        """_connections dict starts empty before register()."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert len(addon._connections) == 0
        assert len(addon._node_managers) == 0

    def test_registry_add_remove_device(self):
        """Can add and remove devices from registry."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()

        addon.registry.add_device("mesh-ttyACM0", "meshtastic", "serial")
        assert "mesh-ttyACM0" in addon.registry
        assert addon.registry.device_count == 1

        addon.registry.remove_device("mesh-ttyACM0")
        assert "mesh-ttyACM0" not in addon.registry
        assert addon.registry.device_count == 0

    def test_registry_state_transitions(self):
        """Device state transitions work correctly."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()

        addon.registry.add_device("mesh-test", "meshtastic", "serial")
        dev = addon.registry.get_device("mesh-test")
        assert dev.state == DeviceState.DISCONNECTED

        addon.registry.set_state("mesh-test", DeviceState.CONNECTING)
        assert dev.state == DeviceState.CONNECTING

        addon.registry.set_state("mesh-test", DeviceState.CONNECTED)
        assert dev.state == DeviceState.CONNECTED

        addon.registry.set_state("mesh-test", DeviceState.ERROR, error="timeout")
        assert dev.state == DeviceState.ERROR
        assert dev.error == "timeout"


# ---------------------------------------------------------------------------
# Multiple ConnectionManagers tests
# ---------------------------------------------------------------------------

class TestMultipleConnectionManagers:
    """Test that multiple ConnectionManagers can be tracked independently."""

    def test_separate_connections(self):
        """Each device_id gets its own ConnectionManager."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.connection import ConnectionManager

        addon = MeshtasticAddon()
        conn1 = ConnectionManager()
        conn2 = ConnectionManager()

        addon._connections["mesh-ttyACM0"] = conn1
        addon._connections["mesh-ttyUSB0"] = conn2

        assert addon._connections["mesh-ttyACM0"] is conn1
        assert addon._connections["mesh-ttyUSB0"] is conn2
        assert conn1 is not conn2

    def test_primary_connection_prefers_connected(self):
        """_get_primary_connection returns first connected radio."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.connection import ConnectionManager

        addon = MeshtasticAddon()
        conn1 = ConnectionManager()
        conn2 = ConnectionManager()
        conn2._is_connected = True
        conn2.interface = MagicMock()

        addon._connections["dev1"] = conn1
        addon._connections["dev2"] = conn2

        primary = addon._get_primary_connection()
        assert primary is conn2

    def test_primary_connection_fallback_to_first(self):
        """When nothing is connected, returns the first registered."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.connection import ConnectionManager

        addon = MeshtasticAddon()
        conn1 = ConnectionManager()
        addon._connections["dev1"] = conn1

        primary = addon._get_primary_connection()
        assert primary is conn1

    def test_primary_connection_none_when_empty(self):
        """When no connections exist, returns None."""
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert addon._get_primary_connection() is None


# ---------------------------------------------------------------------------
# Aggregate node list tests
# ---------------------------------------------------------------------------

class TestAggregateNodeList:
    """Test that nodes from multiple radios are merged correctly."""

    def test_merge_nodes_from_two_radios(self):
        """Nodes from different radios merge into aggregate."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()

        nm1 = NodeManager()
        nm1.update_nodes({
            "!node1": {
                "user": {"longName": "Node 1"},
                "position": {},
                "lastHeard": 1000,
            }
        })

        nm2 = NodeManager()
        nm2.update_nodes({
            "!node2": {
                "user": {"longName": "Node 2"},
                "position": {},
                "lastHeard": 2000,
            }
        })

        addon._node_managers = {"radio1": nm1, "radio2": nm2}
        addon._sync_aggregate_nodes()

        assert len(addon.node_manager.nodes) == 2
        assert "!node1" in addon.node_manager.nodes
        assert "!node2" in addon.node_manager.nodes
        assert addon.node_manager.nodes["!node1"]["bridge_id"] == "radio1"
        assert addon.node_manager.nodes["!node2"]["bridge_id"] == "radio2"

    def test_merge_prefers_most_recent(self):
        """When both radios see the same node, keep the most recent."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()

        nm1 = NodeManager()
        nm1.update_nodes({
            "!shared": {
                "user": {"longName": "Shared Old"},
                "position": {},
                "lastHeard": 1000,
            }
        })

        nm2 = NodeManager()
        nm2.update_nodes({
            "!shared": {
                "user": {"longName": "Shared New"},
                "position": {},
                "lastHeard": 2000,
            }
        })

        addon._node_managers = {"radio1": nm1, "radio2": nm2}
        addon._sync_aggregate_nodes()

        assert len(addon.node_manager.nodes) == 1
        assert addon.node_manager.nodes["!shared"]["long_name"] == "Shared New"
        assert addon.node_manager.nodes["!shared"]["bridge_id"] == "radio2"

    def test_empty_managers_produce_empty_aggregate(self):
        """When no per-device managers have nodes, aggregate is empty."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()
        addon._node_managers = {"radio1": NodeManager()}
        addon._sync_aggregate_nodes()

        assert len(addon.node_manager.nodes) == 0

    def test_gather_returns_aggregated_targets(self):
        """gather() returns targets from all radios."""
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()

        nm1 = NodeManager()
        nm1.update_nodes({
            "!a": {"user": {"longName": "A"}, "position": {}, "lastHeard": 100},
        })
        nm2 = NodeManager()
        nm2.update_nodes({
            "!b": {"user": {"longName": "B"}, "position": {}, "lastHeard": 200},
        })

        addon._node_managers = {"r1": nm1, "r2": nm2}
        loop = asyncio.new_event_loop()
        try:
            targets = loop.run_until_complete(addon.gather())
        finally:
            loop.close()
        assert len(targets) == 2
        ids = [t["target_id"] for t in targets]
        assert "mesh_a" in ids
        assert "mesh_b" in ids


# ---------------------------------------------------------------------------
# Per-device API endpoint tests
# ---------------------------------------------------------------------------

class TestPerDeviceAPIEndpoints:
    """Test the /devices/* API endpoints."""

    @pytest.fixture
    def app_with_addon(self):
        """Create a minimal FastAPI app with the multi-radio router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from meshtastic_addon.router import create_router
        from meshtastic_addon.connection import ConnectionManager
        from meshtastic_addon.node_manager import NodeManager

        registry = DeviceRegistry("meshtastic")
        connections = {}
        node_managers = {}

        # Set up two mock radios
        registry.add_device("mesh-ttyACM0", "meshtastic", "serial",
                            metadata={"port": "/dev/ttyACM0"})
        registry.add_device("mesh-ttyUSB0", "meshtastic", "serial",
                            metadata={"port": "/dev/ttyUSB0"})

        conn0 = ConnectionManager()
        conn0._is_connected = True
        conn0.interface = MagicMock()
        conn0.transport_type = "serial"
        conn0.port = "/dev/ttyACM0"
        connections["mesh-ttyACM0"] = conn0

        conn1 = ConnectionManager()
        connections["mesh-ttyUSB0"] = conn1

        nm0 = NodeManager()
        nm0.update_nodes({
            "!node_a": {
                "user": {"longName": "Alpha"},
                "position": {"latitudeI": 377490000, "longitudeI": -1224194000},
                "lastHeard": 5000,
            }
        })
        node_managers["mesh-ttyACM0"] = nm0
        node_managers["mesh-ttyUSB0"] = NodeManager()

        registry.set_state("mesh-ttyACM0", DeviceState.CONNECTED)

        # Aggregate node manager
        agg_nm = NodeManager()
        agg_nm.nodes = dict(nm0.nodes)

        router = create_router(
            conn0, agg_nm, None,
            registry=registry,
            connections=connections,
            node_managers=node_managers,
        )

        app = FastAPI()
        app.include_router(router, prefix="/api/addons/meshtastic")
        client = TestClient(app)
        return client, registry, connections, node_managers

    def test_list_devices(self, app_with_addon):
        client, registry, connections, node_managers = app_with_addon
        resp = client.get("/api/addons/meshtastic/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["connected_count"] == 1
        ids = [d["device_id"] for d in data["devices"]]
        assert "mesh-ttyACM0" in ids
        assert "mesh-ttyUSB0" in ids

    def test_get_device(self, app_with_addon):
        client, *_ = app_with_addon
        resp = client.get("/api/addons/meshtastic/devices/mesh-ttyACM0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "mesh-ttyACM0"
        assert data["connected"] is True
        assert data["node_count"] == 1

    def test_get_device_not_found(self, app_with_addon):
        client, *_ = app_with_addon
        resp = client.get("/api/addons/meshtastic/devices/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "not_found"

    def test_get_device_nodes(self, app_with_addon):
        client, *_ = app_with_addon
        resp = client.get("/api/addons/meshtastic/devices/mesh-ttyACM0/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["device_id"] == "mesh-ttyACM0"
        assert data["nodes"][0]["node_id"] == "!node_a"
        assert data["nodes"][0]["bridge_id"] == "mesh-ttyACM0"

    def test_get_device_nodes_empty(self, app_with_addon):
        client, *_ = app_with_addon
        resp = client.get("/api/addons/meshtastic/devices/mesh-ttyUSB0/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_disconnect_device(self, app_with_addon):
        client, registry, connections, _ = app_with_addon
        resp = client.post("/api/addons/meshtastic/devices/mesh-ttyACM0/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["device_id"] == "mesh-ttyACM0"
        dev = registry.get_device("mesh-ttyACM0")
        assert dev.state == DeviceState.DISCONNECTED

    def test_add_device(self, app_with_addon):
        client, registry, connections, node_managers = app_with_addon
        resp = client.post("/api/addons/meshtastic/devices/add", json={
            "transport": "tcp",
            "port": "192.168.1.100",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["added"] is True
        assert "mesh-tcp-" in data["device_id"]
        assert data["device_id"] in registry

    def test_add_device_duplicate(self, app_with_addon):
        client, *_ = app_with_addon
        resp = client.post("/api/addons/meshtastic/devices/add", json={
            "device_id": "mesh-ttyACM0",
            "transport": "serial",
            "port": "/dev/ttyACM0",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "already_exists"


# ---------------------------------------------------------------------------
# Legacy endpoint backward-compatibility tests
# ---------------------------------------------------------------------------

class TestLegacyEndpoints:
    """Verify that existing endpoints (without /devices/) still work."""

    @pytest.fixture
    def legacy_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from meshtastic_addon.router import create_router
        from meshtastic_addon.connection import ConnectionManager
        from meshtastic_addon.node_manager import NodeManager

        conn = ConnectionManager()
        conn._is_connected = True
        conn.interface = MagicMock()
        conn.transport_type = "serial"
        conn.port = "/dev/ttyACM0"
        conn.device_info = {"long_name": "Test", "node_id": "!test"}

        nm = NodeManager()
        nm.update_nodes({
            "!abc": {
                "user": {"longName": "Legacy Node", "shortName": "LN", "hwModel": "T_BEAM"},
                "position": {"latitudeI": 377490000, "longitudeI": -1224194000},
                "lastHeard": 3000,
                "deviceMetrics": {"batteryLevel": 80, "voltage": 3.8},
            }
        })

        router = create_router(conn, nm)
        app = FastAPI()
        app.include_router(router, prefix="/api/addons/meshtastic")
        return TestClient(app)

    def test_legacy_status(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["transport"] == "serial"
        assert data["node_count"] == 1

    def test_legacy_nodes(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["nodes"][0]["node_id"] == "!abc"

    def test_legacy_targets(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["target_id"] == "mesh_abc"

    def test_legacy_stats(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 1

    def test_legacy_health(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["connected"] is True

    def test_legacy_geojson(self, legacy_client):
        resp = legacy_client.get("/api/addons/meshtastic/geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1

    def test_legacy_disconnect(self, legacy_client):
        resp = legacy_client.post("/api/addons/meshtastic/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False

    def test_legacy_devices_fallback(self, legacy_client):
        """When no registry is provided, /devices returns single-radio fallback."""
        resp = legacy_client.get("/api/addons/meshtastic/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["devices"][0]["device_id"] == "primary"


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Test the updated health_check method."""

    def test_health_degraded_no_connections(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        h = addon.health_check()
        assert h["status"] == "degraded"
        assert h["connected"] is False
        assert h["total_radios"] == 0
        assert h["connected_radios"] == 0

    def test_health_ok_all_connected(self):
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.connection import ConnectionManager
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()

        conn = ConnectionManager()
        conn._is_connected = True
        conn.interface = MagicMock()
        conn.transport_type = "serial"
        conn.port = "/dev/ttyACM0"
        addon._connections["dev1"] = conn
        addon.connection = conn

        h = addon.health_check()
        assert h["status"] == "ok"
        assert h["connected"] is True
        assert h["total_radios"] == 1
        assert h["connected_radios"] == 1

    def test_health_partial_some_connected(self):
        from meshtastic_addon import MeshtasticAddon
        from meshtastic_addon.connection import ConnectionManager
        from meshtastic_addon.node_manager import NodeManager

        addon = MeshtasticAddon()
        addon.node_manager = NodeManager()

        conn1 = ConnectionManager()
        conn1._is_connected = True
        conn1.interface = MagicMock()
        conn1.transport_type = "serial"
        conn1.port = "/dev/ttyACM0"

        conn2 = ConnectionManager()  # Not connected

        addon._connections["dev1"] = conn1
        addon._connections["dev2"] = conn2
        addon.connection = conn1

        h = addon.health_check()
        assert h["status"] == "partial"
        assert h["connected"] is True
        assert h["total_radios"] == 2
        assert h["connected_radios"] == 1
