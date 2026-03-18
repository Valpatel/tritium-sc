# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Meshtastic MQTT bridge — auto-discovery and node ingestion."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tritium_lib.sdk import DeviceRegistry, DeviceState

from meshtastic_addon.mqtt_bridge import MeshtasticMQTTBridge
from meshtastic_addon.node_manager import NodeManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mqtt_msg(topic: str, payload: dict | list) -> SimpleNamespace:
    """Create a mock MQTT message."""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


def make_bridge(site_id: str = "home") -> tuple[MeshtasticMQTTBridge, DeviceRegistry, dict]:
    """Create a bridge with fresh registry and node_managers dict."""
    registry = DeviceRegistry("meshtastic")
    node_managers: dict[str, NodeManager] = {}
    bridge = MeshtasticMQTTBridge(registry, node_managers, site_id=site_id)
    return bridge, registry, node_managers


def sample_nodes_dict() -> dict:
    """Standard meshtastic interface.nodes format."""
    return {
        "!abcd1234": {
            "num": 0xABCD1234,
            "user": {
                "longName": "Node Alpha",
                "shortName": "NA",
                "hwModel": "TLORA_V2_1_1P6",
            },
            "position": {
                "latitude": 30.2672,
                "longitude": -97.7431,
                "altitude": 150,
            },
            "lastHeard": int(time.time()),
            "snr": 8.5,
        },
        "!dead5678": {
            "num": 0xDEAD5678,
            "user": {
                "longName": "Node Bravo",
                "shortName": "NB",
                "hwModel": "HELTEC_V3",
            },
            "position": {},
            "lastHeard": int(time.time()) - 60,
            "snr": 3.0,
        },
    }


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_subscribes(self):
        bridge, *_ = make_bridge()
        client = MagicMock()
        bridge.start(client)

        assert bridge.is_running
        assert client.subscribe.call_count == 2
        topics = [call.args[0] for call in client.subscribe.call_args_list]
        assert "tritium/home/meshtastic/+/status" in topics
        assert "tritium/home/meshtastic/+/nodes" in topics

    def test_stop_unsubscribes(self):
        bridge, *_ = make_bridge()
        client = MagicMock()
        bridge.start(client)
        bridge.stop()

        assert not bridge.is_running
        assert client.unsubscribe.call_count == 2

    def test_custom_site_id(self):
        bridge, *_ = make_bridge(site_id="warehouse")
        client = MagicMock()
        bridge.start(client)

        topics = [call.args[0] for call in client.subscribe.call_args_list]
        assert "tritium/warehouse/meshtastic/+/status" in topics


# ---------------------------------------------------------------------------
# Auto-discovery from status messages
# ---------------------------------------------------------------------------

class TestAutoDiscovery:
    def test_new_radio_online(self):
        bridge, registry, node_managers = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {
            "online": True,
            "firmware": "2.5.6",
            "hw_model": "TLORA_V2_1_1P6",
        })
        bridge._on_message(None, None, msg)

        assert "mesh-rpi01" in registry
        dev = registry.get_device("mesh-rpi01")
        assert dev.device_type == "meshtastic"
        assert dev.transport_type == "mqtt"
        assert dev.state == DeviceState.CONNECTED
        assert dev.metadata["firmware"] == "2.5.6"
        assert dev.metadata["remote"] is True

    def test_new_radio_creates_node_manager(self):
        bridge, _, node_managers = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        assert "mesh-rpi01" in node_managers
        assert isinstance(node_managers["mesh-rpi01"], NodeManager)

    def test_radio_goes_offline(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)
        assert registry.get_device("mesh-rpi01").state == DeviceState.CONNECTED

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": False})
        bridge._on_message(None, None, msg)
        assert registry.get_device("mesh-rpi01").state == DeviceState.DISCONNECTED

    def test_duplicate_registration_safe(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)
        bridge._on_message(None, None, msg)

        assert registry.device_count == 1

    def test_metadata_updated(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {
            "online": True,
            "firmware": "2.5.5",
        })
        bridge._on_message(None, None, msg)

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {
            "online": True,
            "firmware": "2.5.6",
            "region": "US",
        })
        bridge._on_message(None, None, msg)

        dev = registry.get_device("mesh-rpi01")
        assert dev.metadata["firmware"] == "2.5.6"
        assert dev.metadata["region"] == "US"


# ---------------------------------------------------------------------------
# Node data ingestion
# ---------------------------------------------------------------------------

class TestNodeIngestion:
    def test_ingest_dict_format(self):
        bridge, registry, node_managers = make_bridge()

        # Register device first
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        # Send nodes
        nodes = sample_nodes_dict()
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/nodes", nodes)
        bridge._on_message(None, None, msg)

        nm = node_managers["mesh-rpi01"]
        assert len(nm.nodes) == 2
        assert "!abcd1234" in nm.nodes
        assert "!dead5678" in nm.nodes

    def test_bridge_id_stamped(self):
        bridge, _, node_managers = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        nodes = sample_nodes_dict()
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/nodes", nodes)
        bridge._on_message(None, None, msg)

        nm = node_managers["mesh-rpi01"]
        for node_id, node_data in nm.nodes.items():
            assert node_data.get("bridge_id") == "mesh-rpi01"

    def test_ingest_flat_list_format(self):
        bridge, _, node_managers = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        flat_nodes = [
            {"node_id": "!aaa11111", "long_name": "Flat Node A", "lat": 30.0, "lng": -97.0},
            {"node_id": "!bbb22222", "long_name": "Flat Node B", "lat": 30.1, "lng": -97.1},
        ]
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/nodes", flat_nodes)
        bridge._on_message(None, None, msg)

        nm = node_managers["mesh-rpi01"]
        assert "!aaa11111" in nm.nodes
        assert "!bbb22222" in nm.nodes
        assert nm.nodes["!aaa11111"]["bridge_id"] == "mesh-rpi01"

    def test_auto_register_on_nodes(self):
        """Nodes from unknown device should auto-register it."""
        bridge, registry, node_managers = make_bridge()

        nodes = sample_nodes_dict()
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-new/nodes", nodes)
        bridge._on_message(None, None, msg)

        assert "mesh-new" in registry
        assert "mesh-new" in node_managers
        assert len(node_managers["mesh-new"].nodes) == 2

    def test_node_data_parsed_correctly(self):
        bridge, _, node_managers = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        nodes = sample_nodes_dict()
        msg = make_mqtt_msg("tritium/home/meshtastic/mesh-rpi01/nodes", nodes)
        bridge._on_message(None, None, msg)

        nm = node_managers["mesh-rpi01"]
        node_a = nm.nodes["!abcd1234"]
        assert node_a["long_name"] == "Node Alpha"
        assert node_a["short_name"] == "NA"
        assert node_a["hw_model"] == "TLORA_V2_1_1P6"


# ---------------------------------------------------------------------------
# Topic parsing
# ---------------------------------------------------------------------------

class TestTopicParsing:
    def test_extracts_device_id_from_status(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/my-radio-42/status", {"online": True})
        bridge._on_message(None, None, msg)

        assert "my-radio-42" in registry

    def test_extracts_device_id_from_nodes(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic/remote-radio-7/nodes", sample_nodes_dict())
        bridge._on_message(None, None, msg)

        assert "remote-radio-7" in registry

    def test_short_topic_ignored(self):
        bridge, registry, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/meshtastic", {"online": True})
        bridge._on_message(None, None, msg)

        assert registry.device_count == 0

    def test_invalid_json_ignored(self):
        bridge, registry, _ = make_bridge()

        msg = SimpleNamespace(topic="tritium/home/meshtastic/dev/status", payload=b"not json")
        bridge._on_message(None, None, msg)

        assert registry.device_count == 0


# ---------------------------------------------------------------------------
# ingest_remote_nodes standalone
# ---------------------------------------------------------------------------

class TestIngestRemoteNodes:
    def test_returns_count(self):
        bridge, *_ = make_bridge()
        nm = NodeManager()

        nodes = sample_nodes_dict()
        count = bridge.ingest_remote_nodes(nm, nodes, bridge_id="test-radio")
        assert count == 2

    def test_stamps_bridge_id(self):
        bridge, *_ = make_bridge()
        nm = NodeManager()

        nodes = sample_nodes_dict()
        bridge.ingest_remote_nodes(nm, nodes, bridge_id="test-radio")

        for node_id, node_data in nm.nodes.items():
            assert node_data["bridge_id"] == "test-radio"

    def test_flat_list_returns_count(self):
        bridge, *_ = make_bridge()
        nm = NodeManager()

        flat = [
            {"node_id": "!aaa", "long_name": "A"},
            {"node_id": "!bbb", "long_name": "B"},
            {"node_id": "!ccc", "long_name": "C"},
        ]
        count = bridge.ingest_remote_nodes(nm, flat, bridge_id="remote")
        assert count == 3
