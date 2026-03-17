# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Meshtastic addon.

Tests the addon structure, node parsing, target conversion, and API routes.
Does NOT require a connected Meshtastic device — uses mock data.
"""

import asyncio
import pytest
from pathlib import Path

from tritium_lib.sdk import AddonInfo, SensorAddon
from tritium_lib.sdk.manifest import load_manifest, validate_manifest


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_loads(self):
        manifest_path = Path(__file__).parent.parent / "tritium_addon.toml"
        m = load_manifest(manifest_path)
        assert m.id == "meshtastic"
        assert m.name == "Meshtastic LoRa Mesh"
        assert m.version == "1.0.0"

    def test_manifest_valid(self):
        manifest_path = Path(__file__).parent.parent / "tritium_addon.toml"
        m = load_manifest(manifest_path)
        errors = validate_manifest(m)
        assert errors == [], f"Manifest errors: {errors}"

    def test_manifest_has_panels(self):
        m = load_manifest(Path(__file__).parent.parent / "tritium_addon.toml")
        assert len(m.panels) == 4
        ids = [p["id"] for p in m.panels]
        assert "mesh-network" in ids
        assert "mesh-nodes" in ids

    def test_manifest_has_layers(self):
        m = load_manifest(Path(__file__).parent.parent / "tritium_addon.toml")
        assert len(m.layers) == 3

    def test_manifest_category(self):
        m = load_manifest(Path(__file__).parent.parent / "tritium_addon.toml")
        assert m.category_window == "radio"

    def test_manifest_permissions(self):
        m = load_manifest(Path(__file__).parent.parent / "tritium_addon.toml")
        assert m.perm_serial is True
        assert m.perm_network is True
        assert m.perm_mqtt is True

    def test_manifest_hardware(self):
        m = load_manifest(Path(__file__).parent.parent / "tritium_addon.toml")
        assert m.auto_detect is True
        assert "303a:1001" in m.serial_vid_pid


# ---------------------------------------------------------------------------
# Addon class tests
# ---------------------------------------------------------------------------

class TestAddonClass:
    def test_import(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        assert addon.info.id == "meshtastic"

    def test_is_sensor(self):
        from meshtastic_addon import MeshtasticAddon
        assert issubclass(MeshtasticAddon, SensorAddon)

    def test_get_panels(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        panels = addon.get_panels()
        assert len(panels) == 4

    def test_get_layers(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        layers = addon.get_layers()
        assert len(layers) == 3

    def test_health_check_disconnected(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        h = addon.health_check()
        assert h["status"] == "degraded"
        assert h["connected"] is False


# ---------------------------------------------------------------------------
# Node manager tests
# ---------------------------------------------------------------------------

class TestNodeManager:
    def test_create(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        assert len(nm.nodes) == 0

    def test_parse_node(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        raw = {
            "!ba33ff38": {
                "num": 3123969848,
                "user": {
                    "id": "!ba33ff38",
                    "longName": "Meshtastic ff38",
                    "shortName": "ff38",
                    "hwModel": "T_LORA_PAGER",
                    "macaddr": "10:20:ba:33:ff:38",
                },
                "position": {
                    "latitudeI": 377490000,
                    "longitudeI": -1224194000,
                    "altitude": 16,
                },
                "lastHeard": 1773706063,
                "deviceMetrics": {
                    "batteryLevel": 101,
                    "voltage": 4.239,
                    "channelUtilization": 2.98,
                    "airUtilTx": 1.54,
                    "uptimeSeconds": 18289,
                },
            }
        }
        nm.update_nodes(raw)
        assert len(nm.nodes) == 1
        assert "!ba33ff38" in nm.nodes

    def test_node_has_position(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        nm.update_nodes({
            "!test": {
                "user": {"longName": "Test"},
                "position": {"latitudeI": 377490000, "longitudeI": -1224194000, "altitude": 16},
                "lastHeard": 1000,
            }
        })
        node = nm.nodes["!test"]
        assert abs(node["lat"] - 37.749) < 0.001
        assert abs(node["lng"] - (-122.4194)) < 0.001

    def test_node_has_battery(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        nm.update_nodes({
            "!test": {
                "user": {"longName": "Test"},
                "position": {},
                "lastHeard": 1000,
                "deviceMetrics": {"batteryLevel": 85, "voltage": 3.9},
            }
        })
        assert nm.nodes["!test"]["battery"] == 85
        assert nm.nodes["!test"]["voltage"] == 3.9

    def test_get_targets(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        nm.update_nodes({
            "!node1": {
                "user": {"longName": "Node One", "shortName": "N1", "hwModel": "T_BEAM"},
                "position": {"latitudeI": 377490000, "longitudeI": -1224194000},
                "lastHeard": 2000,
                "deviceMetrics": {"batteryLevel": 90, "voltage": 4.0},
            },
            "!node2": {
                "user": {"longName": "Node Two"},
                "position": {},
                "lastHeard": 1000,
            },
        })
        targets = nm.get_targets()
        assert len(targets) == 2

        t1 = next(t for t in targets if t["target_id"] == "mesh_node1")
        assert t1["name"] == "Node One"
        assert t1["source"] == "mesh"
        assert t1["asset_type"] == "mesh_radio"
        assert t1["alliance"] == "friendly"
        assert t1["lat"] is not None
        assert abs(t1["battery"] - 0.9) < 0.01

    def test_get_targets_no_position(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        nm.update_nodes({
            "!nopos": {
                "user": {"longName": "No GPS"},
                "position": {},
                "lastHeard": 500,
            }
        })
        targets = nm.get_targets()
        assert len(targets) == 1
        assert "lat" not in targets[0]

    def test_many_nodes(self):
        from meshtastic_addon.node_manager import NodeManager
        nm = NodeManager()
        raw = {}
        for i in range(250):
            raw[f"!node{i:04d}"] = {
                "user": {"longName": f"Node {i}"},
                "position": {"latitudeI": 377490000 + i * 100, "longitudeI": -1224194000 + i * 100},
                "lastHeard": 1000 + i,
            }
        nm.update_nodes(raw)
        assert len(nm.nodes) == 250
        targets = nm.get_targets()
        assert len(targets) == 250


# ---------------------------------------------------------------------------
# Connection manager tests (no hardware needed)
# ---------------------------------------------------------------------------

class TestConnection:
    def test_create(self):
        from meshtastic_addon.connection import ConnectionManager
        cm = ConnectionManager()
        assert not cm.is_connected
        assert cm.transport_type == "none"

    def test_disconnect_when_not_connected(self):
        from meshtastic_addon.connection import ConnectionManager
        cm = ConnectionManager()
        asyncio.run(cm.disconnect())
        assert not cm.is_connected
