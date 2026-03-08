# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for FleetBridge — fleet server WebSocket/REST bridge.

Tests WebSocket message parsing (heartbeat, registered, offline, OTA events),
BLE presence extraction from heartbeats, REST polling (devices, BLE presence,
node diagnostics), stats property, and device tracking.
"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.event_bus import EventBus
from engine.comms.fleet_bridge import FleetBridge


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_bridge(ws_url="ws://192.168.86.9:8080/ws", rest_url=None, **kw):
    bus = EventBus()
    bridge = FleetBridge(bus, ws_url=ws_url, rest_url=rest_url, **kw)
    return bridge, bus


def _collect_events(bus: EventBus):
    """Subscribe to the bus and return a helper to drain published events."""
    q = bus.subscribe()

    def drain():
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        return msgs

    return drain


# ── REST URL derivation ─────────────────────────────────────────────────

@pytest.mark.unit
class TestRestUrlDerivation:

    def test_default_rest_url_from_ws(self):
        bridge, _ = _make_bridge(ws_url="ws://10.0.0.1:8080/ws")
        assert bridge.rest_url == "http://10.0.0.1:8080"

    def test_default_rest_url_from_wss(self):
        bridge, _ = _make_bridge(ws_url="wss://fleet.example.com/ws")
        assert bridge.rest_url == "https://fleet.example.com"

    def test_explicit_rest_url(self):
        bridge, _ = _make_bridge(rest_url="http://custom:9090/")
        assert bridge.rest_url == "http://custom:9090"

    def test_rest_url_strips_trailing_slash(self):
        bridge, _ = _make_bridge(rest_url="http://host:80/")
        assert bridge.rest_url == "http://host:80"


# ── Stats property ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestStatsProperty:

    def test_initial_stats(self):
        bridge, _ = _make_bridge()
        s = bridge.stats
        assert s["connected"] is False
        assert s["messages_received"] == 0
        assert s["devices_tracked"] == 0
        assert s["device_ids"] == []
        assert s["ws_url"] == "ws://192.168.86.9:8080/ws"
        assert s["last_error"] == ""

    def test_stats_after_heartbeat(self):
        bridge, bus = _make_bridge()
        msg = json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "node-1", "board": "esp32"},
            "timestamp": "2026-01-01T00:00:00Z",
        })
        bridge._on_message(None, msg)
        s = bridge.stats
        assert s["messages_received"] == 1
        assert s["devices_tracked"] == 1
        assert "node-1" in s["device_ids"]


# ── WebSocket message parsing ────────────────────────────────────────────

@pytest.mark.unit
class TestWebSocketHeartbeat:

    def test_heartbeat_publishes_fleet_heartbeat(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        msg = json.dumps({
            "type": "device_heartbeat",
            "data": {
                "device_id": "node-alpha",
                "board": "touch-lcd-35bc",
                "version": "1.2.3",
                "ip": "192.168.1.50",
                "mac": "AA:BB:CC:DD:EE:FF",
                "rssi": -45,
                "free_heap": 200000,
                "uptime_s": 3600,
                "capabilities": ["ble", "camera"],
                "sensors": {},
            },
            "timestamp": "2026-01-01T00:00:00Z",
        })
        bridge._on_message(None, msg)
        events = drain()
        hb = [e for e in events if e["type"] == "fleet.heartbeat"]
        assert len(hb) == 1
        d = hb[0]["data"]
        assert d["device_id"] == "node-alpha"
        assert d["board"] == "touch-lcd-35bc"
        assert d["version"] == "1.2.3"
        assert d["ip"] == "192.168.1.50"
        assert d["rssi"] == -45
        assert d["free_heap"] == 200000
        assert d["uptime_s"] == 3600
        assert d["online"] is True
        assert d["capabilities"] == ["ble", "camera"]
        assert d["server_timestamp"] == "2026-01-01T00:00:00Z"

    def test_heartbeat_tracks_device(self):
        bridge, _ = _make_bridge()
        msg = json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "node-1", "board": "esp32"},
            "timestamp": "",
        })
        bridge._on_message(None, msg)
        assert "node-1" in bridge.devices
        assert bridge.devices["node-1"]["board"] == "esp32"

    def test_heartbeat_increments_message_count(self):
        bridge, _ = _make_bridge()
        for i in range(3):
            bridge._on_message(None, json.dumps({
                "type": "device_heartbeat",
                "data": {"device_id": f"n-{i}"},
                "timestamp": "",
            }))
        assert bridge._messages_received == 3

    def test_heartbeat_default_fields(self):
        """Missing fields should fall back to 'unknown' or defaults."""
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {},
            "timestamp": "",
        }))
        events = drain()
        hb = [e for e in events if e["type"] == "fleet.heartbeat"][0]["data"]
        assert hb["device_id"] == "unknown"
        assert hb["board"] == "unknown"
        assert hb["version"] == "unknown"


@pytest.mark.unit
class TestWebSocketBlePresence:

    def test_ble_devices_emit_fleet_ble_presence(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        msg = json.dumps({
            "type": "device_heartbeat",
            "data": {
                "device_id": "scanner-1",
                "sensors": {
                    "ble_scanner": {
                        "devices": [
                            {"addr": "AA:BB:CC:DD:EE:01", "name": "Phone", "rssi": -60, "type": "phone"},
                            {"addr": "AA:BB:CC:DD:EE:02", "name": "", "rssi": -80, "type": "unknown"},
                        ],
                    },
                },
            },
            "timestamp": "2026-01-01T00:00:00Z",
        })
        bridge._on_message(None, msg)
        events = drain()
        ble_events = [e for e in events if e["type"] == "fleet.ble_presence"]
        assert len(ble_events) == 2
        assert ble_events[0]["data"]["reporter_id"] == "scanner-1"
        assert ble_events[0]["data"]["ble_addr"] == "AA:BB:CC:DD:EE:01"
        assert ble_events[0]["data"]["ble_name"] == "Phone"
        assert ble_events[0]["data"]["rssi"] == -60
        assert ble_events[1]["data"]["ble_addr"] == "AA:BB:CC:DD:EE:02"

    def test_no_ble_devices_no_ble_events(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "node-1", "sensors": {}},
            "timestamp": "",
        }))
        events = drain()
        ble_events = [e for e in events if e["type"] == "fleet.ble_presence"]
        assert len(ble_events) == 0

    def test_non_ble_sensors_emit_fleet_sensor(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {
                "device_id": "node-1",
                "sensors": {
                    "temperature": {"value": 23.5, "unit": "C"},
                    "ble_scanner": {"devices": []},
                },
            },
            "timestamp": "t1",
        }))
        events = drain()
        sensor_events = [e for e in events if e["type"] == "fleet.sensor"]
        assert len(sensor_events) == 1
        assert sensor_events[0]["data"]["sensor_type"] == "temperature"
        assert sensor_events[0]["data"]["data"]["value"] == 23.5


@pytest.mark.unit
class TestWebSocketRegistered:

    def test_registered_publishes_event(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({
            "type": "device_registered",
            "data": {"device_id": "new-node", "board": "amoled-191m", "mac": "11:22:33:44:55:66", "tags": ["beta"]},
            "timestamp": "t1",
        }))
        events = drain()
        reg = [e for e in events if e["type"] == "fleet.registered"]
        assert len(reg) == 1
        d = reg[0]["data"]
        assert d["device_id"] == "new-node"
        assert d["board"] == "amoled-191m"
        assert d["mac"] == "11:22:33:44:55:66"
        assert d["tags"] == ["beta"]

    def test_registered_tracks_device(self):
        bridge, _ = _make_bridge()
        bridge._on_message(None, json.dumps({
            "type": "device_registered",
            "data": {"device_id": "new-node", "board": "x"},
            "timestamp": "",
        }))
        assert "new-node" in bridge.devices


@pytest.mark.unit
class TestWebSocketOffline:

    def test_offline_publishes_event(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        # First register the device
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "node-x"},
            "timestamp": "",
        }))
        # Then mark offline
        bridge._on_message(None, json.dumps({
            "type": "device_offline",
            "data": {"device_id": "node-x"},
            "timestamp": "t2",
        }))
        events = drain()
        offline = [e for e in events if e["type"] == "fleet.offline"]
        assert len(offline) == 1
        assert offline[0]["data"]["device_id"] == "node-x"

    def test_offline_marks_device_offline(self):
        bridge, _ = _make_bridge()
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "node-x"},
            "timestamp": "",
        }))
        bridge._on_message(None, json.dumps({
            "type": "device_offline",
            "data": {"device_id": "node-x"},
            "timestamp": "",
        }))
        assert bridge.devices["node-x"]["_online"] is False


@pytest.mark.unit
class TestWebSocketOtaAndForwarding:

    @pytest.mark.parametrize("event_type", [
        "ota_started", "ota_result", "ota_scheduled",
        "command_sent", "firmware_uploaded",
    ])
    def test_forwarded_events(self, event_type):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({
            "type": event_type,
            "data": {"info": "test"},
            "timestamp": "ts",
        }))
        events = drain()
        forwarded = [e for e in events if e["type"] == f"fleet.{event_type}"]
        assert len(forwarded) == 1
        assert forwarded[0]["data"]["info"] == "test"
        assert forwarded[0]["data"]["server_timestamp"] == "ts"

    def test_pong_ignored(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({"type": "pong", "data": {}, "timestamp": ""}))
        events = drain()
        assert len(events) == 0

    def test_unknown_event_no_crash(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({"type": "alien_signal", "data": {}, "timestamp": ""}))
        events = drain()
        assert len(events) == 0


@pytest.mark.unit
class TestWebSocketMalformedPayloads:

    def test_invalid_json_skipped(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, "not valid json {{{")
        events = drain()
        assert len(events) == 0
        assert bridge._messages_received == 1

    def test_empty_string(self):
        bridge, _ = _make_bridge()
        bridge._on_message(None, "")
        assert bridge._messages_received == 1

    def test_missing_type_field(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_message(None, json.dumps({"data": {"x": 1}}))
        events = drain()
        assert len(events) == 0


# ── WebSocket callbacks ──────────────────────────────────────────────────

@pytest.mark.unit
class TestWebSocketCallbacks:

    def test_on_open_sets_connected(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        bridge._on_open(None)
        assert bridge.connected is True
        events = drain()
        conn = [e for e in events if e["type"] == "fleet.connected"]
        assert len(conn) == 1

    def test_on_close_clears_connected(self):
        bridge, bus = _make_bridge()
        bridge._on_open(None)
        drain = _collect_events(bus)
        bridge._on_close(None, 1000, "normal")
        assert bridge.connected is False
        events = drain()
        disc = [e for e in events if e["type"] == "fleet.disconnected"]
        assert len(disc) == 1
        assert disc[0]["data"]["code"] == 1000

    def test_on_error_records_last_error(self):
        bridge, _ = _make_bridge()
        bridge._on_error(None, RuntimeError("test error"))
        assert "test error" in bridge._last_error


# ── REST polling ─────────────────────────────────────────────────────────

def _mock_urlopen(data_bytes, status=200):
    """Create a mock context manager that returns data_bytes on read()."""
    resp = MagicMock()
    resp.read.return_value = data_bytes
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.mark.unit
class TestPollDevices:

    def test_poll_devices_list_format(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        devices = [
            {"device_id": "n1", "board": "a"},
            {"device_id": "n2", "board": "b"},
        ]
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(devices).encode())
        bridge._poll_devices(request_mod, error_mod)

        assert "n1" in bridge.devices
        assert "n2" in bridge.devices
        events = drain()
        update = [e for e in events if e["type"] == "fleet.device_update"]
        assert len(update) == 1
        assert update[0]["data"]["count"] == 2

    def test_poll_devices_dict_format(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        payload = {"devices": [{"id": "d1", "board": "c"}]}
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(payload).encode())
        bridge._poll_devices(request_mod, error_mod)

        assert "d1" in bridge.devices
        events = drain()
        update = [e for e in events if e["type"] == "fleet.device_update"]
        assert update[0]["data"]["count"] == 1

    def test_poll_devices_url_error(self):
        """URLError should not crash the bridge."""
        bridge, _ = _make_bridge()
        request_mod = MagicMock()
        error_mod = MagicMock()
        import urllib.error
        error_mod.URLError = urllib.error.URLError
        request_mod.urlopen.side_effect = urllib.error.URLError("conn refused")
        bridge._poll_devices(request_mod, error_mod)
        assert bridge.stats["devices_tracked"] == 0


@pytest.mark.unit
class TestPollBlePresence:

    def test_poll_ble_presence(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        ble_data = [{"addr": "AA:BB", "rssi": -55}]
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(ble_data).encode())
        bridge._poll_ble_presence(request_mod, error_mod)

        assert bridge.ble_presence == ble_data
        events = drain()
        ble = [e for e in events if e["type"] == "fleet.ble_presence"]
        assert len(ble) == 1
        assert ble[0]["data"]["count"] == 1

    def test_poll_ble_presence_url_error_silent(self):
        """BLE endpoint may not exist — URLError should be silently ignored."""
        bridge, _ = _make_bridge()
        request_mod = MagicMock()
        error_mod = MagicMock()
        import urllib.error
        error_mod.URLError = urllib.error.URLError
        request_mod.urlopen.side_effect = urllib.error.URLError("not found")
        bridge._poll_ble_presence(request_mod, error_mod)
        assert bridge.ble_presence == []


@pytest.mark.unit
class TestPollNodeDiagnostics:

    def test_poll_node_diagnostics_emits_events(self):
        bridge, bus = _make_bridge()
        # Pre-populate a device with an IP
        bridge._devices["node-1"] = {"ip": "10.0.0.5", "port": 80}
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        diag_data = {
            "health": {"cpu_temp_c": 45.2, "min_free_heap": 100000},
            "anomalies": [
                {"subsystem": "i2c", "description": "timeout", "severity_score": 0.7},
            ],
        }
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(diag_data).encode())
        bridge._poll_node_diagnostics(request_mod, error_mod)

        events = drain()
        diag = [e for e in events if e["type"] == "fleet.node_diag"]
        assert len(diag) == 1
        assert diag[0]["data"]["device_id"] == "node-1"
        assert diag[0]["data"]["diagnostics"]["health"]["cpu_temp_c"] == 45.2

        anomaly = [e for e in events if e["type"] == "fleet.node_anomaly"]
        assert len(anomaly) == 1
        assert anomaly[0]["data"]["count"] == 1
        assert anomaly[0]["data"]["anomalies"][0]["subsystem"] == "i2c"

    def test_poll_node_diagnostics_no_anomalies(self):
        bridge, bus = _make_bridge()
        bridge._devices["node-2"] = {"ip": "10.0.0.6"}
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        diag_data = {"health": {"cpu_temp_c": 30.0}, "anomalies": []}
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(diag_data).encode())
        bridge._poll_node_diagnostics(request_mod, error_mod)

        events = drain()
        diag = [e for e in events if e["type"] == "fleet.node_diag"]
        assert len(diag) == 1
        anomaly = [e for e in events if e["type"] == "fleet.node_anomaly"]
        assert len(anomaly) == 0

    def test_poll_node_diagnostics_skips_no_ip(self):
        bridge, bus = _make_bridge()
        bridge._devices["no-ip"] = {"board": "test"}
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        bridge._poll_node_diagnostics(request_mod, error_mod)

        events = drain()
        assert len(events) == 0
        request_mod.urlopen.assert_not_called()

    def test_poll_node_diagnostics_offline_node(self):
        """Unreachable nodes should not crash the poll."""
        bridge, _ = _make_bridge()
        bridge._devices["dead-node"] = {"ip": "10.0.0.99"}
        request_mod = MagicMock()
        error_mod = MagicMock()
        import urllib.error
        error_mod.URLError = urllib.error.URLError
        request_mod.urlopen.side_effect = urllib.error.URLError("timeout")
        bridge._poll_node_diagnostics(request_mod, error_mod)
        # No crash is the assertion


# ── Device tracking ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestDeviceTracking:

    def test_devices_returns_copy(self):
        bridge, _ = _make_bridge()
        bridge._devices["a"] = {"x": 1}
        devs = bridge.devices
        devs["b"] = {"y": 2}
        assert "b" not in bridge.devices

    def test_ble_presence_returns_copy(self):
        bridge, _ = _make_bridge()
        bridge._ble_presence = [{"addr": "x"}]
        p = bridge.ble_presence
        p.append({"addr": "y"})
        assert len(bridge.ble_presence) == 1

    def test_multiple_heartbeats_update_same_device(self):
        bridge, _ = _make_bridge()
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "n1", "version": "1.0"},
            "timestamp": "",
        }))
        bridge._on_message(None, json.dumps({
            "type": "device_heartbeat",
            "data": {"device_id": "n1", "version": "1.1"},
            "timestamp": "",
        }))
        assert bridge.stats["devices_tracked"] == 1
        assert bridge.devices["n1"]["version"] == "1.1"

    def test_start_without_websocket_module(self):
        """start() should gracefully handle missing websocket-client."""
        bridge, _ = _make_bridge()
        with patch.dict("sys.modules", {"websocket": None}):
            bridge.start()
        assert bridge._running is False or "not installed" in bridge._last_error

    def test_stop_clears_state(self):
        bridge, _ = _make_bridge()
        bridge._connected = True
        bridge.stop()
        assert bridge.connected is False
        assert bridge._running is False

    def test_config_sync_returns_copy(self):
        bridge, _ = _make_bridge()
        bridge._config_sync = {"config_version": "v2"}
        cs = bridge.config_sync
        cs["extra"] = True
        assert "extra" not in bridge.config_sync

    def test_config_sync_initially_empty(self):
        bridge, _ = _make_bridge()
        assert bridge.config_sync == {}


# ── Fleet config polling ────────────────────────────────────────────────

@pytest.mark.unit
class TestPollFleetConfig:

    def test_poll_fleet_config_emits_event(self):
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        config_data = {
            "config_version": "v3",
            "nodes_synced": 4,
            "nodes_total": 5,
            "nodes_pending": ["node-5"],
        }
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(config_data).encode())
        bridge._poll_fleet_config(request_mod, error_mod)

        assert bridge.config_sync["config_version"] == "v3"
        assert bridge.config_sync["nodes_synced"] == 4
        assert bridge.config_sync["nodes_pending"] == ["node-5"]

        events = drain()
        cs_events = [e for e in events if e["type"] == "fleet.config_sync"]
        assert len(cs_events) == 1
        assert cs_events[0]["data"]["config_version"] == "v3"
        assert cs_events[0]["data"]["nodes_synced"] == 4
        assert cs_events[0]["data"]["nodes_total"] == 5
        assert cs_events[0]["data"]["nodes_pending"] == ["node-5"]

    def test_poll_fleet_config_url_error_silent(self):
        """URLError should be silently ignored (endpoint may not exist)."""
        bridge, _ = _make_bridge()
        request_mod = MagicMock()
        error_mod = MagicMock()
        import urllib.error
        error_mod.URLError = urllib.error.URLError
        request_mod.urlopen.side_effect = urllib.error.URLError("not found")
        bridge._poll_fleet_config(request_mod, error_mod)
        assert bridge.config_sync == {}

    def test_poll_fleet_config_non_dict_response(self):
        """Non-dict response should result in empty config_sync."""
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        # Response is a list instead of dict
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps([1, 2, 3]).encode())
        bridge._poll_fleet_config(request_mod, error_mod)
        assert bridge.config_sync == {}
        events = drain()
        # Should still emit event with defaults since data is not a dict
        cs_events = [e for e in events if e["type"] == "fleet.config_sync"]
        assert len(cs_events) == 1
        assert cs_events[0]["data"]["config_version"] == "unknown"

    def test_poll_fleet_config_missing_fields_use_defaults(self):
        """Missing fields in the response should use defaults."""
        bridge, bus = _make_bridge()
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        # Minimal response with only config_version
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps({"config_version": "v1"}).encode())
        bridge._poll_fleet_config(request_mod, error_mod)

        events = drain()
        cs_events = [e for e in events if e["type"] == "fleet.config_sync"]
        assert len(cs_events) == 1
        d = cs_events[0]["data"]
        assert d["config_version"] == "v1"
        assert d["nodes_synced"] == 0
        assert d["nodes_total"] == 0
        assert d["nodes_pending"] == []

    def test_stats_includes_config_sync(self):
        bridge, _ = _make_bridge()
        bridge._config_sync = {"config_version": "v5", "nodes_synced": 3}
        s = bridge.stats
        assert "config_sync" in s
        assert s["config_sync"]["config_version"] == "v5"

    def test_stats_config_sync_empty_when_not_polled(self):
        bridge, _ = _make_bridge()
        s = bridge.stats
        assert s["config_sync"] == {}


# ── Node diagnostics edge cases ──────────────────────────────────────────

@pytest.mark.unit
class TestPollNodeDiagnosticsEdgeCases:

    def test_poll_node_diagnostics_default_port(self):
        """Devices without explicit port should default to 80."""
        bridge, bus = _make_bridge()
        bridge._devices["node-np"] = {"ip": "10.0.0.7"}
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        diag_data = {"health": {"cpu_temp_c": 38.0}, "anomalies": []}
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(diag_data).encode())
        bridge._poll_node_diagnostics(request_mod, error_mod)

        # Verify the URL used port 80
        call_args = request_mod.Request.call_args
        assert ":80/api/diag" in call_args[0][0]

        events = drain()
        diag = [e for e in events if e["type"] == "fleet.node_diag"]
        assert len(diag) == 1

    def test_poll_node_diagnostics_custom_port(self):
        """Devices with explicit port should use that port."""
        bridge, bus = _make_bridge()
        bridge._devices["node-cp"] = {"ip": "10.0.0.8", "port": 8080}
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        diag_data = {"health": {}, "anomalies": []}
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(diag_data).encode())
        bridge._poll_node_diagnostics(request_mod, error_mod)

        call_args = request_mod.Request.call_args
        assert ":8080/api/diag" in call_args[0][0]

    def test_poll_multiple_nodes(self):
        """Should poll all tracked devices with IPs."""
        bridge, bus = _make_bridge()
        bridge._devices["n1"] = {"ip": "10.0.0.1"}
        bridge._devices["n2"] = {"ip": "10.0.0.2"}
        bridge._devices["n3"] = {}  # No IP, should be skipped
        drain = _collect_events(bus)
        request_mod = MagicMock()
        error_mod = MagicMock()
        diag_data = {"health": {}, "anomalies": []}
        request_mod.urlopen.return_value = _mock_urlopen(json.dumps(diag_data).encode())
        bridge._poll_node_diagnostics(request_mod, error_mod)

        events = drain()
        diag = [e for e in events if e["type"] == "fleet.node_diag"]
        assert len(diag) == 2
        device_ids = {e["data"]["device_id"] for e in diag}
        assert device_ids == {"n1", "n2"}
