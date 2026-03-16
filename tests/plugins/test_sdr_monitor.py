# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the SDR Monitor plugin — rtl_433 MQTT integration.

Tests cover:
- Plugin identity and lifecycle
- rtl_433 JSON message parsing
- ISM device tracking and dedup
- Device type classification
- Frequency activity tracking
- Signal history
- TrackedTarget creation
- Route creation
- EventBus integration
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from sdr_monitor.plugin import (
    SDRMonitorPlugin,
    ISMDevice,
    classify_device_type,
    build_device_id,
)


# -- ISMDevice tests -------------------------------------------------------

class TestISMDevice:
    def test_create_device(self):
        dev = ISMDevice(
            device_id="sdr_acurite_tower_123",
            model="Acurite-Tower",
            protocol="acurite",
            device_type="weather_station",
            frequency_mhz=433.92,
            rssi_db=-45.0,
        )
        assert dev.device_id == "sdr_acurite_tower_123"
        assert dev.model == "Acurite-Tower"
        assert dev.device_type == "weather_station"
        assert dev.frequency_mhz == 433.92
        assert dev.rssi_db == -45.0
        assert dev.message_count == 1

    def test_update_device(self):
        dev = ISMDevice(device_id="sdr_test_1")
        first_seen = dev.first_seen
        time.sleep(0.01)
        dev.update(rssi_db=-30.0, metadata={"temperature_C": 22.5})
        assert dev.message_count == 2
        assert dev.rssi_db == -30.0
        assert dev.metadata["temperature_C"] == 22.5
        assert dev.first_seen == first_seen
        assert dev.last_seen > first_seen

    def test_to_dict(self):
        dev = ISMDevice(device_id="sdr_test_2", model="WeatherStation")
        d = dev.to_dict()
        assert d["device_id"] == "sdr_test_2"
        assert d["model"] == "WeatherStation"
        assert "first_seen" in d
        assert "last_seen" in d
        assert "metadata" in d
        assert "message_count" in d


# -- Device classification tests -------------------------------------------

class TestClassifyDeviceType:
    def test_weather_station(self):
        assert classify_device_type("Acurite-Tower") == "weather_station"
        assert classify_device_type("Oregon-v2.1") == "weather_station"
        assert classify_device_type("LaCrosse-TX141Bv3") == "weather_station"
        assert classify_device_type("Bresser-5in1") == "weather_station"
        assert classify_device_type("Fine-Offset-WH2") == "weather_station"

    def test_tire_pressure(self):
        assert classify_device_type("Toyota-TPMS") == "tire_pressure"
        assert classify_device_type("Schrader-TPMS") == "tire_pressure"

    def test_doorbell(self):
        assert classify_device_type("Generic-Doorbell") == "doorbell"

    def test_soil_moisture(self):
        assert classify_device_type("Soil-Moisture-Sensor") == "soil_moisture"

    def test_unknown(self):
        assert classify_device_type("SomeRandomModel") == "ism_device"


class TestBuildDeviceId:
    def test_basic(self):
        did = build_device_id({"model": "Acurite-Tower", "id": 12345})
        assert did == "sdr_acurite-tower_12345"

    def test_with_channel(self):
        did = build_device_id({"model": "Oregon", "id": 99, "channel": 3})
        assert did == "sdr_oregon_99_ch3"

    def test_no_id(self):
        did = build_device_id({"model": "Unknown"})
        assert did == "sdr_unknown"

    def test_spaces_replaced(self):
        did = build_device_id({"model": "Some Model", "id": 1})
        assert " " not in did


# -- SDRMonitorPlugin tests ------------------------------------------------

class TestSDRMonitorPlugin:
    def _make_plugin(self):
        p = SDRMonitorPlugin()
        p._logger = MagicMock()
        return p

    def test_plugin_identity(self):
        p = self._make_plugin()
        assert p.plugin_id == "tritium.sdr_monitor"
        assert "SDR" in p.name
        assert "rtl_433" in p.name
        assert p.version == "2.0.0"
        assert "data_source" in p.capabilities
        assert "routes" in p.capabilities
        assert "background" in p.capabilities

    def test_ingest_weather_station(self):
        p = self._make_plugin()
        result = p.ingest_message({
            "model": "Acurite-Tower",
            "id": 12345,
            "channel": "A",
            "temperature_C": 22.5,
            "humidity": 65,
            "freq": 433.92,
            "rssi": -42.0,
            "snr": 15.0,
        })
        assert result["model"] == "Acurite-Tower"
        assert result["device_type"] == "weather_station"
        assert result["frequency_mhz"] == 433.92
        assert result["rssi_db"] == -42.0
        assert result["metadata"]["temperature_C"] == 22.5
        assert result["metadata"]["humidity"] == 65

        devices = p.get_devices()
        assert len(devices) == 1
        assert p._stats["messages_received"] == 1
        assert p._stats["devices_detected"] == 1

    def test_ingest_tpms(self):
        p = self._make_plugin()
        p.ingest_message({
            "model": "Schrader-TPMS",
            "id": 0xABCD,
            "pressure_kPa": 230.0,
            "temperature_C": 35.0,
            "freq": 315.0,
            "rssi": -55.0,
        })
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["device_type"] == "tire_pressure"

    def test_dedup_same_device(self):
        p = self._make_plugin()
        msg = {
            "model": "TestDevice",
            "id": 999,
            "freq": 433.92,
            "rssi": -50.0,
        }
        p.ingest_message(msg)
        p.ingest_message(msg)
        p.ingest_message(msg)
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["message_count"] == 3
        assert p._stats["messages_received"] == 3
        assert p._stats["devices_detected"] == 1

    def test_multiple_devices(self):
        p = self._make_plugin()
        p.ingest_message({"model": "Device-A", "id": 1})
        p.ingest_message({"model": "Device-B", "id": 2})
        p.ingest_message({"model": "Device-C", "id": 3})
        devices = p.get_devices()
        assert len(devices) == 3

    def test_signal_history(self):
        p = self._make_plugin()
        for i in range(5):
            p.ingest_message({"model": f"Dev{i}", "id": i, "freq": 433.92})
        signals = p.get_signals(limit=3)
        assert len(signals) == 3
        signals_all = p.get_signals(limit=100)
        assert len(signals_all) == 5

    def test_frequency_activity(self):
        p = self._make_plugin()
        p.ingest_message({"model": "A", "id": 1, "freq": 433.92})
        p.ingest_message({"model": "B", "id": 2, "freq": 433.92})
        p.ingest_message({"model": "C", "id": 3, "freq": 315.0})
        spectrum = p.get_spectrum()
        assert spectrum["frequency_activity"][433.92] == 2
        assert spectrum["frequency_activity"][315.0] == 1
        assert spectrum["total_frequencies"] == 2

    def test_stats(self):
        p = self._make_plugin()
        stats = p.get_stats()
        assert stats["messages_received"] == 0
        assert stats["devices_active"] == 0
        assert stats["running"] is False
        assert stats["mqtt_topic"] == "rtl_433/events"

    def test_stats_by_type(self):
        p = self._make_plugin()
        p.ingest_message({"model": "Acurite-Tower", "id": 1})
        p.ingest_message({"model": "Schrader-TPMS", "id": 2})
        p.ingest_message({"model": "Acurite-5in1", "id": 3})
        stats = p.get_stats()
        assert stats["messages_by_type"]["weather_station"] == 2
        assert stats["messages_by_type"]["tire_pressure"] == 1

    def test_eventbus_publish_on_ingest(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.ingest_message({"model": "Test", "id": 1})
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "sdr_monitor:device"

    def test_handle_event_rtl_433(self):
        p = self._make_plugin()
        p.handle_event({
            "type": "rtl_433:message",
            "data": {"model": "Oregon-v2.1", "id": 42, "freq": 433.92},
        })
        assert p._stats["messages_received"] == 1
        devices = p.get_devices()
        assert len(devices) == 1

    def test_mqtt_message_handler(self):
        """Test the MQTT callback parses JSON correctly."""
        p = self._make_plugin()
        import json
        payload = json.dumps({"model": "Bresser-5in1", "id": 100, "freq": 868.3})
        p._on_rtl433_mqtt("rtl_433/events", payload)
        assert p._stats["messages_received"] == 1
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["model"] == "Bresser-5in1"

    def test_mqtt_invalid_json(self):
        p = self._make_plugin()
        p._on_rtl433_mqtt("rtl_433/events", "not json")
        assert p._stats["messages_received"] == 0

    def test_configure_with_settings(self):
        p = self._make_plugin()
        ctx = MagicMock()
        ctx.settings = {
            "mqtt_topic": "custom/rtl433",
            "device_ttl": 120.0,
            "poll_interval": 5.0,
        }
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = MagicMock()
        p.configure(ctx)
        assert p._mqtt_topic == "custom/rtl433"
        assert p._device_ttl == 120.0
        assert p._poll_interval == 5.0

    def test_start_stop(self):
        p = self._make_plugin()
        assert p.healthy is False
        p.start()
        assert p.healthy is True
        p.stop()
        assert p.healthy is False

    def test_target_creation(self):
        """Test that ingest creates a TrackedTarget in the tracker."""
        p = self._make_plugin()
        tracker = MagicMock()
        tracker._lock = MagicMock()
        tracker._targets = {}
        p._tracker = tracker
        p.ingest_message({
            "model": "Acurite-Tower",
            "id": 55,
            "freq": 433.92,
            "rssi": -40.0,
        })
        assert len(tracker._targets) == 1
        target_id = list(tracker._targets.keys())[0]
        assert "sdr" in target_id
        assert p._stats["targets_created"] == 1

    def test_metadata_extraction(self):
        """Non-core fields become metadata."""
        p = self._make_plugin()
        result = p.ingest_message({
            "model": "Oregon-v2.1",
            "id": 10,
            "freq": 433.92,
            "temperature_C": 18.3,
            "humidity": 72,
            "battery_ok": 1,
            "wind_avg_km_h": 5.2,
        })
        md = result["metadata"]
        assert md["temperature_C"] == 18.3
        assert md["humidity"] == 72
        assert md["battery_ok"] == 1
        assert md["wind_avg_km_h"] == 5.2
        # Core fields should NOT be in metadata
        assert "model" not in md
        assert "id" not in md
        assert "freq" not in md


# -- Route creation test ---------------------------------------------------

class TestSDRMonitorRoutes:
    def test_create_router(self):
        from sdr_monitor.routes import create_router
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        router = create_router(plugin)
        paths = [r.path for r in router.routes]
        assert "/api/sdr/devices" in paths
        assert "/api/sdr/spectrum" in paths
        assert "/api/sdr/stats" in paths
        assert "/api/sdr/signals" in paths
        assert "/api/sdr/health" in paths
        assert "/api/sdr/ingest" in paths
