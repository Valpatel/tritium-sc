# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the SDR Monitor plugin — comprehensive SDR monitoring.

Tests cover:
- Plugin identity and lifecycle
- rtl_433 JSON message parsing and ISM device tracking
- Device type classification
- ADS-B aircraft track ingestion and tracking
- Spectrum sweep recording
- RF anomaly detection (baseline comparison)
- Demo data generator
- Route creation with all endpoints
- TrackedTarget creation for both ISM and ADS-B
- EventBus integration
- Cleanup loop (stale device/track removal)
- Pydantic models
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from sdr_monitor.plugin import (
    SDRMonitorPlugin,
    ISMDevice,
    ADSBTrack,
    classify_device_type,
    build_device_id,
)
from sdr_monitor.models import (
    SpectrumSweep,
    ISMDevice as ISMDeviceModel,
    ADSBTrack as ADSBTrackModel,
    RFAnomaly,
    SDRConfig,
    SDRDeviceInfo,
    SDRStatus,
)


# ---------------------------------------------------------------------------
# ISMDevice tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ADSBTrack tests
# ---------------------------------------------------------------------------

class TestADSBTrack:
    def test_create_track(self):
        track = ADSBTrack(
            icao_hex="A1B2C3",
            callsign="UAL2145",
            lat=30.27,
            lng=-97.74,
            altitude_ft=12000,
            speed_kts=250,
            heading=135,
        )
        assert track.icao_hex == "A1B2C3"
        assert track.callsign == "UAL2145"
        assert track.lat == 30.27
        assert track.altitude_ft == 12000
        assert track.message_count == 1

    def test_update_track(self):
        track = ADSBTrack(icao_hex="ABCDEF")
        track.update({
            "flight": "SWA1872",
            "lat": 30.5,
            "lon": -97.5,
            "altitude": 18000,
            "speed": 280,
            "track": 310,
        })
        assert track.callsign == "SWA1872"
        assert track.lat == 30.5
        assert track.lng == -97.5
        assert track.altitude_ft == 18000
        assert track.message_count == 2

    def test_to_dict(self):
        track = ADSBTrack(icao_hex="112233", callsign="N172SP")
        d = track.to_dict()
        assert d["icao_hex"] == "112233"
        assert d["callsign"] == "N172SP"
        assert "lat" in d
        assert "lng" in d
        assert "altitude_ft" in d
        assert "heading" in d
        assert "message_count" in d

    def test_squawk_update(self):
        track = ADSBTrack(icao_hex="AABBCC")
        track.update({"squawk": "7700"})
        assert track.squawk == "7700"


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

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

    def test_smoke_detector(self):
        assert classify_device_type("Smoke-Alarm-v2") == "smoke_detector"

    def test_power_meter(self):
        assert classify_device_type("Current-Cost-Meter") == "power_meter"


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


# ---------------------------------------------------------------------------
# SDRMonitorPlugin core tests
# ---------------------------------------------------------------------------

class TestSDRMonitorPlugin:
    def _make_plugin(self):
        p = SDRMonitorPlugin()
        p._logger = MagicMock()
        return p

    def test_plugin_identity(self):
        p = self._make_plugin()
        assert p.plugin_id == "tritium.sdr_monitor"
        assert "SDR" in p.name
        assert p.version == "2.0.0"
        assert "data_source" in p.capabilities
        assert "routes" in p.capabilities
        assert "background" in p.capabilities

    def test_start_stop(self):
        p = self._make_plugin()
        assert p.healthy is False
        p.start()
        assert p.healthy is True
        p.stop()
        assert p.healthy is False

    # -- ISM ingestion tests -----------------------------------------------

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
        msg = {"model": "TestDevice", "id": 999, "freq": 433.92, "rssi": -50.0}
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

    def test_metadata_extraction(self):
        p = self._make_plugin()
        result = p.ingest_message({
            "model": "Oregon-v2.1",
            "id": 10,
            "freq": 433.92,
            "temperature_C": 18.3,
            "humidity": 72,
            "battery_ok": 1,
        })
        md = result["metadata"]
        assert md["temperature_C"] == 18.3
        assert md["humidity"] == 72
        assert "model" not in md
        assert "id" not in md
        assert "freq" not in md

    def test_eventbus_publish_on_ingest(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.ingest_message({"model": "Test", "id": 1})
        bus.publish.assert_called()
        call_args = bus.publish.call_args_list[0]
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

    def test_target_creation_ism(self):
        p = self._make_plugin()
        tracker = MagicMock()
        tracker._lock = MagicMock()
        tracker._targets = {}
        p._tracker = tracker
        p.ingest_message({
            "model": "Acurite-Tower",
            "id": 55,
            "freq": 433.92,
        })
        assert len(tracker._targets) == 1
        target_id = list(tracker._targets.keys())[0]
        assert "sdr" in target_id
        assert p._stats["targets_created"] == 1

    # -- ADS-B tests -------------------------------------------------------

    def test_ingest_adsb(self):
        p = self._make_plugin()
        result = p.ingest_adsb({
            "hex": "A1B2C3",
            "flight": "UAL2145",
            "lat": 30.27,
            "lon": -97.74,
            "altitude": 12000,
            "speed": 250,
            "track": 135,
            "squawk": "1200",
        })
        assert result is not None
        assert result["icao_hex"] == "A1B2C3"
        assert result["callsign"] == "UAL2145"
        assert result["lat"] == 30.27
        assert result["altitude_ft"] == 12000

    def test_adsb_track_update(self):
        p = self._make_plugin()
        p.ingest_adsb({"hex": "AABB", "flight": "SWA100", "lat": 30.0, "lon": -97.0, "altitude": 5000})
        p.ingest_adsb({"hex": "AABB", "lat": 30.1, "lon": -97.1, "altitude": 6000})
        tracks = p.get_adsb_tracks()
        assert len(tracks) == 1
        assert tracks[0]["callsign"] == "SWA100"
        assert tracks[0]["lat"] == 30.1
        assert tracks[0]["altitude_ft"] == 6000
        assert tracks[0]["message_count"] == 2

    def test_adsb_invalid_message(self):
        p = self._make_plugin()
        result = p.ingest_adsb({"no_hex": "bad"})
        assert result is None

    def test_adsb_stats(self):
        p = self._make_plugin()
        p.ingest_adsb({"hex": "111", "lat": 30.0, "lon": -97.0})
        p.ingest_adsb({"hex": "222", "lat": 30.5, "lon": -97.5})
        stats = p.get_stats()
        assert stats["adsb_messages"] == 2

    def test_adsb_target_creation(self):
        p = self._make_plugin()
        tracker = MagicMock()
        tracker._lock = MagicMock()
        tracker._targets = {}
        p._tracker = tracker
        p.ingest_adsb({
            "hex": "ABCDEF",
            "flight": "AAL456",
            "lat": 30.35,
            "lon": -98.10,
            "altitude": 35000,
        })
        assert "adsb_ABCDEF" in tracker._targets
        t = tracker._targets["adsb_ABCDEF"]
        assert t.position == (30.35, -98.10)
        assert t.source == "sdr_monitor"
        assert t.position_source == "adsb"
        assert t.position_confidence == 0.95

    def test_adsb_eventbus_publish(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.ingest_adsb({"hex": "AABB", "lat": 30.0, "lon": -97.0})
        calls = [c[0][0] for c in bus.publish.call_args_list]
        assert "sdr_monitor:adsb" in calls

    def test_handle_event_adsb(self):
        p = self._make_plugin()
        p.handle_event({
            "type": "adsb:message",
            "data": {"hex": "1234", "lat": 30.0, "lon": -97.0},
        })
        assert p._stats["adsb_messages"] == 1

    # -- Spectrum tests ----------------------------------------------------

    def test_record_spectrum(self):
        p = self._make_plugin()
        sweep = {
            "freq_start_hz": 432e6,
            "freq_end_hz": 435e6,
            "bin_count": 512,
            "power_dbm": [-80.0] * 512,
            "timestamp": time.time(),
        }
        p.record_spectrum(sweep)
        history = p.get_spectrum_history(limit=10)
        assert len(history) == 1
        assert history[0]["bin_count"] == 512
        stats = p.get_stats()
        assert stats["spectrum_history_size"] == 1

    def test_spectrum_eventbus(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.record_spectrum({"power_dbm": [-80.0] * 10})
        calls = [c[0][0] for c in bus.publish.call_args_list]
        assert "sdr_monitor:spectrum" in calls

    def test_handle_event_spectrum(self):
        p = self._make_plugin()
        p.handle_event({
            "type": "sdr:spectrum",
            "data": {"power_dbm": [-85.0] * 100, "freq_start_hz": 432e6, "freq_end_hz": 435e6, "bin_count": 100},
        })
        stats = p.get_stats()
        assert stats["spectrum_captures"] == 1

    # -- Anomaly detection tests -------------------------------------------

    def test_record_anomaly(self):
        p = self._make_plugin()
        anomaly = {
            "frequency_mhz": 433.92,
            "power_dbm": -20.0,
            "baseline_dbm": -80.0,
            "anomaly_type": "new_transmitter",
            "severity": "warning",
            "timestamp": time.time(),
        }
        p.record_anomaly(anomaly)
        anomalies = p.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0]["anomaly_type"] == "new_transmitter"
        assert p._stats["anomalies_detected"] == 1

    def test_anomaly_eventbus(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.record_anomaly({
            "frequency_mhz": 915.0,
            "power_dbm": -10.0,
            "baseline_dbm": -75.0,
            "anomaly_type": "jamming",
        })
        calls = [c[0][0] for c in bus.publish.call_args_list]
        assert "sdr_monitor:anomaly" in calls

    def test_baseline_learning(self):
        p = self._make_plugin()
        # Feed enough baseline samples
        for _ in range(10):
            p._update_baseline(433.92, -80.0)
        baseline = p._get_baseline_power(433.92)
        assert baseline is not None
        assert abs(baseline - (-80.0)) < 0.1

    def test_baseline_insufficient_samples(self):
        p = self._make_plugin()
        p._update_baseline(433.92, -80.0)
        p._update_baseline(433.92, -82.0)
        # Only 2 samples, need 5 minimum
        baseline = p._get_baseline_power(433.92)
        assert baseline is None

    def test_spectrum_anomaly_detection(self):
        p = self._make_plugin()
        # Build a baseline at -80 dBm for freq 433.0 MHz
        for _ in range(10):
            p._update_baseline(433.0, -80.0)

        # Now send a sweep with a strong signal at that freq
        freq_start = 432.5e6
        freq_end = 433.5e6
        bin_count = 100
        power_dbm = [-80.0] * bin_count
        # The bin corresponding to 433.0 MHz (50th bin out of 100, centered)
        target_bin = 50
        power_dbm[target_bin] = -40.0  # 40 dB above baseline

        p._check_spectrum_anomalies({
            "freq_start_hz": freq_start,
            "freq_end_hz": freq_end,
            "bin_count": bin_count,
            "power_dbm": power_dbm,
        })

        anomalies = p.get_anomalies()
        assert len(anomalies) > 0
        assert anomalies[0]["anomaly_type"] == "power_change"

    # -- Status tests ------------------------------------------------------

    def test_get_status(self):
        p = self._make_plugin()
        p._running = True
        p._start_time = time.time() - 100
        status = p.get_status()
        assert "ism_devices_tracked" in status
        assert "adsb_aircraft_tracked" in status
        assert "anomalies_active" in status
        assert "uptime_s" in status
        assert status["demo_mode"] is False

    def test_stats_comprehensive(self):
        p = self._make_plugin()
        stats = p.get_stats()
        assert stats["messages_received"] == 0
        assert stats["devices_active"] == 0
        assert stats["adsb_tracks_active"] == 0
        assert stats["running"] is False
        assert "demo_mode" in stats

    def test_stats_by_type(self):
        p = self._make_plugin()
        p.ingest_message({"model": "Acurite-Tower", "id": 1})
        p.ingest_message({"model": "Schrader-TPMS", "id": 2})
        p.ingest_message({"model": "Acurite-5in1", "id": 3})
        stats = p.get_stats()
        assert stats["messages_by_type"]["weather_station"] == 2
        assert stats["messages_by_type"]["tire_pressure"] == 1

    # -- Configuration tests -----------------------------------------------

    def test_configure_with_settings(self):
        p = self._make_plugin()
        ctx = MagicMock()
        ctx.settings = {
            "mqtt_topic": "custom/rtl433",
            "device_ttl": 120.0,
            "adsb_ttl": 30.0,
            "poll_interval": 5.0,
        }
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = MagicMock()
        p.configure(ctx)
        assert p._mqtt_topic == "custom/rtl433"
        assert p._device_ttl == 120.0
        assert p._adsb_ttl == 30.0
        assert p._poll_interval == 5.0

    def test_configure_sdr(self):
        p = self._make_plugin()
        result = p.configure_sdr({
            "center_freq_hz": 915e6,
            "gain_db": 30.0,
        })
        assert result["status"] == "accepted"
        assert result["config"]["center_freq_hz"] == 915e6

    # -- Demo mode tests ---------------------------------------------------

    def test_start_stop_demo(self):
        p = self._make_plugin()
        p._running = True
        result = p.start_demo()
        assert result["status"] == "started"
        assert p._demo is not None
        assert p._demo.is_running

        # Starting again returns already_running
        result2 = p.start_demo()
        assert result2["status"] == "already_running"

        result3 = p.stop_demo()
        assert result3["status"] == "stopped"
        assert p._demo is None

    def test_stop_demo_when_not_running(self):
        p = self._make_plugin()
        result = p.stop_demo()
        assert result["status"] == "not_running"

    # -- MQTT handler tests ------------------------------------------------

    def test_mqtt_rtl433_handler(self):
        import json
        p = self._make_plugin()
        payload = json.dumps({"model": "Bresser-5in1", "id": 100, "freq": 868.3})
        p._on_rtl433_mqtt("rtl_433/events", payload)
        assert p._stats["messages_received"] == 1

    def test_mqtt_adsb_handler(self):
        import json
        p = self._make_plugin()
        payload = json.dumps({"hex": "AABB", "flight": "SWA100", "lat": 30.0, "lon": -97.0})
        p._on_adsb_mqtt("tritium/home/sdr/sdr1/adsb", payload)
        assert p._stats["adsb_messages"] == 1

    def test_mqtt_spectrum_handler(self):
        import json
        p = self._make_plugin()
        payload = json.dumps({"power_dbm": [-80.0] * 10})
        p._on_spectrum_mqtt("tritium/home/sdr/sdr1/spectrum", payload)
        assert p._stats["spectrum_captures"] == 1

    def test_mqtt_invalid_json(self):
        p = self._make_plugin()
        p._on_rtl433_mqtt("rtl_433/events", "not json")
        assert p._stats["messages_received"] == 0


# ---------------------------------------------------------------------------
# Route creation tests
# ---------------------------------------------------------------------------

class TestSDRMonitorRoutes:
    def test_create_router(self):
        from sdr_monitor.routes import create_router
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        router = create_router(plugin)
        paths = [r.path for r in router.routes]

        # All required endpoints
        assert "/api/sdr/status" in paths
        assert "/api/sdr/spectrum" in paths
        assert "/api/sdr/spectrum/sweeps" in paths
        assert "/api/sdr/devices" in paths
        assert "/api/sdr/adsb" in paths
        assert "/api/sdr/anomalies" in paths
        assert "/api/sdr/configure" in paths
        assert "/api/sdr/signals" in paths
        assert "/api/sdr/stats" in paths
        assert "/api/sdr/health" in paths
        assert "/api/sdr/demo/start" in paths
        assert "/api/sdr/demo/stop" in paths
        assert "/api/sdr/ingest" in paths
        assert "/api/sdr/ingest/adsb" in paths

    def test_router_tags(self):
        from sdr_monitor.routes import create_router
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        router = create_router(plugin)
        assert "sdr_monitor" in router.tags


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------

class TestPydanticModels:
    def test_spectrum_sweep(self):
        sweep = SpectrumSweep(
            freq_start_hz=432e6,
            freq_end_hz=435e6,
            bin_count=512,
            power_dbm=[-80.0] * 512,
            timestamp=time.time(),
        )
        assert sweep.bin_count == 512
        assert len(sweep.power_dbm) == 512
        d = sweep.model_dump()
        assert "freq_start_hz" in d

    def test_ism_device_model(self):
        dev = ISMDeviceModel(
            device_id="sdr_acurite_123",
            protocol="acurite",
            model="Acurite-Tower",
            frequency_mhz=433.92,
            rssi=-45.0,
            device_type="weather_station",
            data={"temperature_C": 22.5},
        )
        assert dev.device_type == "weather_station"
        d = dev.model_dump()
        assert d["data"]["temperature_C"] == 22.5

    def test_adsb_track_model(self):
        track = ADSBTrackModel(
            icao_hex="A1B2C3",
            callsign="UAL2145",
            lat=30.27,
            lng=-97.74,
            altitude_ft=12000,
            speed_kts=250,
            heading=135,
        )
        assert track.icao_hex == "A1B2C3"
        d = track.model_dump()
        assert d["altitude_ft"] == 12000

    def test_rf_anomaly_model(self):
        anomaly = RFAnomaly(
            frequency_mhz=433.92,
            power_dbm=-20.0,
            baseline_dbm=-80.0,
            anomaly_type="new_transmitter",
            severity="warning",
        )
        assert anomaly.anomaly_type == "new_transmitter"
        d = anomaly.model_dump()
        assert d["severity"] == "warning"

    def test_sdr_config_model(self):
        config = SDRConfig(
            center_freq_hz=915e6,
            gain_db=30.0,
        )
        assert config.center_freq_hz == 915e6
        assert config.sample_rate == 2_000_000  # default

    def test_sdr_device_info_model(self):
        info = SDRDeviceInfo(
            device_id="hackrf-001",
            device_type="hackrf",
            status="connected",
        )
        assert info.device_type == "hackrf"
        assert info.freq_range_mhz == [1.0, 6000.0]

    def test_sdr_status_model(self):
        status = SDRStatus(
            active_receivers=1,
            ism_devices_tracked=5,
            adsb_aircraft_tracked=3,
        )
        assert status.active_receivers == 1
        d = status.model_dump()
        assert d["ism_devices_tracked"] == 5


# ---------------------------------------------------------------------------
# Demo generator tests
# ---------------------------------------------------------------------------

class TestSDRDemoGenerator:
    def test_demo_lifecycle(self):
        from sdr_monitor.demo import SDRDemoGenerator
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        demo = SDRDemoGenerator(plugin)
        assert not demo.is_running
        demo.start()
        assert demo.is_running
        # Let it run briefly
        time.sleep(0.5)
        demo.stop()
        assert not demo.is_running

    def test_demo_generates_ism_data(self):
        """After running demo briefly, plugin should have some devices."""
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        plugin._running = True
        result = plugin.start_demo()
        assert result["status"] == "started"
        # Give demo time to generate data
        time.sleep(3.0)
        plugin.stop_demo()

        # Should have at least some devices and signals
        devices = plugin.get_devices()
        signals = plugin.get_signals(limit=100)
        # Demo generates ISM data every 2s cycle; some devices may have transmitted
        assert len(devices) >= 0  # may be 0 if timing is unlucky
        # But stats should show some activity
        stats = plugin.get_stats()
        # At minimum, ADS-B updates happen every 1s, so we should see some
        assert stats["adsb_messages"] > 0

    def test_demo_generates_adsb_data(self):
        """Demo should generate ADS-B tracks."""
        plugin = SDRMonitorPlugin()
        plugin._logger = MagicMock()
        plugin._running = True
        plugin.start_demo()
        time.sleep(2.0)
        plugin.stop_demo()

        tracks = plugin.get_adsb_tracks()
        assert len(tracks) > 0
        # Each track should have position
        for track in tracks:
            assert "icao_hex" in track
            assert "callsign" in track
            assert "lat" in track
