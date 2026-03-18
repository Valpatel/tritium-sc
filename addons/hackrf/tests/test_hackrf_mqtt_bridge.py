# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for HackRF MQTT bridge — auto-discovery and spectrum ingestion."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tritium_lib.sdk import DeviceRegistry, DeviceState

from hackrf_addon.mqtt_bridge import HackRFMQTTBridge
from hackrf_addon.signal_db import SignalDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mqtt_msg(topic: str, payload: dict) -> SimpleNamespace:
    """Create a mock MQTT message."""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


def make_bridge(site_id: str = "home") -> tuple[HackRFMQTTBridge, DeviceRegistry, dict, dict]:
    """Create a bridge with fresh registry and dicts."""
    registry = DeviceRegistry("hackrf")
    spectrum_instances: dict = {}
    signal_dbs: dict[str, SignalDatabase] = {}
    bridge = HackRFMQTTBridge(registry, spectrum_instances, signal_dbs, site_id=site_id)
    return bridge, registry, spectrum_instances, signal_dbs


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
        assert "tritium/home/sdr/+/status" in topics
        assert "tritium/home/sdr/+/spectrum" in topics

    def test_stop_unsubscribes(self):
        bridge, *_ = make_bridge()
        client = MagicMock()
        bridge.start(client)
        bridge.stop()

        assert not bridge.is_running
        assert client.unsubscribe.call_count == 2

    def test_custom_site_id(self):
        bridge, *_ = make_bridge(site_id="lab")
        client = MagicMock()
        bridge.start(client)

        topics = [call.args[0] for call in client.subscribe.call_args_list]
        assert "tritium/lab/sdr/+/status" in topics
        assert "tritium/lab/sdr/+/spectrum" in topics


# ---------------------------------------------------------------------------
# Auto-discovery from status messages
# ---------------------------------------------------------------------------

class TestAutoDiscovery:
    def test_new_device_online(self):
        bridge, registry, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {
            "online": True,
            "firmware": "2024.02.1",
            "serial": "abc123",
        })
        bridge._on_message(None, None, msg)

        assert "hackrf-rpi01" in registry
        dev = registry.get_device("hackrf-rpi01")
        assert dev.device_type == "hackrf"
        assert dev.transport_type == "mqtt"
        assert dev.state == DeviceState.CONNECTED
        assert dev.metadata["firmware"] == "2024.02.1"
        assert dev.metadata["serial"] == "abc123"
        assert dev.metadata["remote"] is True

    def test_new_device_creates_signal_db(self):
        bridge, _, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        assert "hackrf-rpi01" in signal_dbs
        assert isinstance(signal_dbs["hackrf-rpi01"], SignalDatabase)

    def test_device_goes_offline(self):
        bridge, registry, _, _ = make_bridge()

        # Come online
        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)
        assert registry.get_device("hackrf-rpi01").state == DeviceState.CONNECTED

        # Go offline
        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": False})
        bridge._on_message(None, None, msg)
        assert registry.get_device("hackrf-rpi01").state == DeviceState.DISCONNECTED

    def test_duplicate_registration_safe(self):
        bridge, registry, _, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)
        bridge._on_message(None, None, msg)

        assert registry.device_count == 1

    def test_metadata_updated(self):
        bridge, registry, _, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {
            "online": True,
            "firmware": "1.0",
        })
        bridge._on_message(None, None, msg)

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {
            "online": True,
            "firmware": "2.0",
            "hw_revision": "r9",
        })
        bridge._on_message(None, None, msg)

        dev = registry.get_device("hackrf-rpi01")
        assert dev.metadata["firmware"] == "2.0"
        assert dev.metadata["hw_revision"] == "r9"


# ---------------------------------------------------------------------------
# Spectrum data ingestion
# ---------------------------------------------------------------------------

class TestSpectrumIngestion:
    def test_ingest_array_format(self):
        bridge, registry, _, signal_dbs = make_bridge()

        # First register the device
        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        # Send spectrum data
        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/spectrum", {
            "freq_hz": [100_000_000, 101_000_000, 102_000_000],
            "power_dbm": [-40.0, -35.0, -50.0],
            "timestamp": 1000.0,
        })
        bridge._on_message(None, None, msg)

        sig_db = signal_dbs["hackrf-rpi01"]
        assert sig_db.count == 3

        results = sig_db.query()
        freqs = sorted([r["freq_hz"] for r in results])
        assert freqs == [100_000_000, 101_000_000, 102_000_000]

    def test_ingest_list_of_dicts_format(self):
        bridge, _, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/spectrum", [
            {"freq_hz": 100_000_000, "power_dbm": -40.0},
            {"freq_hz": 101_000_000, "power_dbm": -35.0},
        ])
        bridge._on_message(None, None, msg)

        sig_db = signal_dbs["hackrf-rpi01"]
        assert sig_db.count == 2

    def test_auto_register_on_spectrum(self):
        """Spectrum from unknown device should auto-register it."""
        bridge, registry, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-new/spectrum", {
            "freq_hz": [100_000_000],
            "power_dbm": [-40.0],
        })
        bridge._on_message(None, None, msg)

        assert "hackrf-new" in registry
        assert "hackrf-new" in signal_dbs
        assert signal_dbs["hackrf-new"].count == 1

    def test_empty_spectrum_ignored(self):
        bridge, _, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/spectrum", {
            "freq_hz": [],
            "power_dbm": [],
        })
        bridge._on_message(None, None, msg)

        assert signal_dbs["hackrf-rpi01"].count == 0

    def test_mismatched_lengths_uses_minimum(self):
        bridge, _, _, signal_dbs = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/status", {"online": True})
        bridge._on_message(None, None, msg)

        msg = make_mqtt_msg("tritium/home/sdr/hackrf-rpi01/spectrum", {
            "freq_hz": [100_000_000, 101_000_000, 102_000_000],
            "power_dbm": [-40.0, -35.0],
        })
        bridge._on_message(None, None, msg)

        assert signal_dbs["hackrf-rpi01"].count == 2


# ---------------------------------------------------------------------------
# Topic parsing
# ---------------------------------------------------------------------------

class TestTopicParsing:
    def test_extracts_device_id_from_status(self):
        bridge, registry, _, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/my-device-42/status", {"online": True})
        bridge._on_message(None, None, msg)

        assert "my-device-42" in registry

    def test_extracts_device_id_from_spectrum(self):
        bridge, registry, _, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr/remote-sdr-7/spectrum", {
            "freq_hz": [100_000_000],
            "power_dbm": [-40.0],
        })
        bridge._on_message(None, None, msg)

        assert "remote-sdr-7" in registry

    def test_short_topic_ignored(self):
        bridge, registry, _, _ = make_bridge()

        msg = make_mqtt_msg("tritium/home/sdr", {"online": True})
        bridge._on_message(None, None, msg)

        assert registry.device_count == 0

    def test_invalid_json_ignored(self):
        bridge, registry, _, _ = make_bridge()

        msg = SimpleNamespace(topic="tritium/home/sdr/dev/status", payload=b"not json")
        bridge._on_message(None, None, msg)

        assert registry.device_count == 0


# ---------------------------------------------------------------------------
# ingest_remote_sweep standalone
# ---------------------------------------------------------------------------

class TestIngestRemoteSweep:
    def test_returns_count(self):
        bridge, *_ = make_bridge()
        sig_db = SignalDatabase()

        count = bridge.ingest_remote_sweep(sig_db, {
            "freq_hz": [1, 2, 3, 4, 5],
            "power_dbm": [-10, -20, -30, -40, -50],
        })
        assert count == 5
        assert sig_db.count == 5

    def test_uses_provided_timestamp(self):
        bridge, *_ = make_bridge()
        sig_db = SignalDatabase()

        bridge.ingest_remote_sweep(sig_db, {
            "freq_hz": [100_000_000],
            "power_dbm": [-40.0],
            "timestamp": 9999.0,
        })

        results = sig_db.query()
        assert results[0]["timestamp"] == 9999.0
