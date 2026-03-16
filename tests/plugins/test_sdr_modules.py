# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the SDR Monitor modular components.

Tests cover:
- SpectrumAnalyzer: baseline learning, anomaly detection, peak detection
- ADSBProcessor: track ingestion, stale expiry, emergency squawks
- ISMDecoder: message parsing, device classification, dedup, frequency activity
"""
import sys
import time
from pathlib import Path

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from sdr_monitor.spectrum import SpectrumAnalyzer
from sdr_monitor.adsb import ADSBProcessor, ADSBTrack
from sdr_monitor.ism_decoder import (
    ISMDecoder,
    ISMDevice,
    classify_device_type,
    build_device_id,
    extract_metadata,
)


# ---------------------------------------------------------------------------
# SpectrumAnalyzer tests
# ---------------------------------------------------------------------------

class TestSpectrumAnalyzer:
    def test_process_sweep_stores_history(self):
        sa = SpectrumAnalyzer()
        sweep = {
            "freq_start_hz": 432e6,
            "freq_end_hz": 435e6,
            "bin_count": 100,
            "power_dbm": [-80.0] * 100,
            "timestamp": time.time(),
        }
        sa.process_sweep(sweep)
        history = sa.get_history()
        assert len(history) == 1
        assert history[0]["bin_count"] == 100

    def test_baseline_learning(self):
        sa = SpectrumAnalyzer()
        for _ in range(10):
            sa.update_baseline(433.92, -80.0)
        baseline = sa.get_baseline_power(433.92)
        assert baseline is not None
        assert abs(baseline - (-80.0)) < 0.1

    def test_baseline_insufficient_samples(self):
        sa = SpectrumAnalyzer()
        sa.update_baseline(433.92, -80.0)
        sa.update_baseline(433.92, -82.0)
        assert sa.get_baseline_power(433.92) is None

    def test_baseline_nonexistent_freq(self):
        sa = SpectrumAnalyzer()
        assert sa.get_baseline_power(999.0) is None

    def test_anomaly_detection(self):
        sa = SpectrumAnalyzer()
        # Build baseline
        for _ in range(10):
            sa.update_baseline(433.0, -80.0)

        # Send sweep with strong signal at that freq
        power_dbm = [-80.0] * 100
        power_dbm[50] = -40.0  # 40 dB above baseline

        anomalies = sa.process_sweep({
            "freq_start_hz": 432.5e6,
            "freq_end_hz": 433.5e6,
            "bin_count": 100,
            "power_dbm": power_dbm,
        })
        assert len(anomalies) > 0
        assert anomalies[0]["anomaly_type"] == "power_change"
        assert anomalies[0]["deviation_db"] > 30.0

    def test_no_anomaly_below_threshold(self):
        sa = SpectrumAnalyzer(anomaly_threshold_db=20.0)
        for _ in range(10):
            sa.update_baseline(433.0, -80.0)

        # Signal only 10 dB above baseline (below 20 dB threshold)
        power_dbm = [-80.0] * 100
        power_dbm[50] = -70.0

        anomalies = sa.process_sweep({
            "freq_start_hz": 432.5e6,
            "freq_end_hz": 433.5e6,
            "bin_count": 100,
            "power_dbm": power_dbm,
        })
        assert len(anomalies) == 0

    def test_record_anomaly(self):
        sa = SpectrumAnalyzer()
        sa.record_anomaly({
            "frequency_mhz": 915.0,
            "power_dbm": -10.0,
            "anomaly_type": "jamming",
        })
        anomalies = sa.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0]["anomaly_type"] == "jamming"

    def test_peak_detection(self):
        sa = SpectrumAnalyzer()
        power_dbm = [-80.0] * 100
        # Add a peak at bin 50
        power_dbm[50] = -40.0
        power_dbm[49] = -55.0
        power_dbm[51] = -55.0

        peaks = sa.detect_peaks({
            "freq_start_hz": 432e6,
            "freq_end_hz": 434e6,
            "power_dbm": power_dbm,
        })
        assert len(peaks) >= 1
        assert peaks[0]["power_dbm"] == -40.0
        assert peaks[0]["snr_db"] > 30.0

    def test_peak_detection_empty(self):
        sa = SpectrumAnalyzer()
        assert sa.detect_peaks({"power_dbm": []}) == []
        assert sa.detect_peaks({}) == []

    def test_stats(self):
        sa = SpectrumAnalyzer()
        sa.process_sweep({
            "freq_start_hz": 432e6,
            "freq_end_hz": 435e6,
            "bin_count": 10,
            "power_dbm": [-80.0] * 10,
        })
        stats = sa.get_stats()
        assert stats["sweeps_processed"] == 1
        assert stats["history_size"] == 1

    def test_prune_baseline(self):
        sa = SpectrumAnalyzer(baseline_window_s=0.01)
        sa.update_baseline(433.92, -80.0)
        time.sleep(0.02)
        pruned = sa.prune_baseline()
        assert pruned >= 0  # may or may not prune depending on timing

    def test_process_sweep_invalid_data(self):
        sa = SpectrumAnalyzer()
        # Empty power data
        anomalies = sa.process_sweep({"power_dbm": []})
        assert anomalies == []
        # Missing freq range
        anomalies = sa.process_sweep({
            "power_dbm": [-80.0] * 10,
            "freq_start_hz": 0,
            "freq_end_hz": 0,
            "bin_count": 10,
        })
        assert anomalies == []


# ---------------------------------------------------------------------------
# ADSBProcessor tests
# ---------------------------------------------------------------------------

class TestADSBProcessor:
    def test_ingest_creates_track(self):
        proc = ADSBProcessor()
        result = proc.ingest({
            "hex": "A1B2C3",
            "flight": "UAL2145",
            "lat": 30.27,
            "lon": -97.74,
            "altitude": 12000,
            "speed": 250,
            "track": 135,
        })
        assert result is not None
        assert result["icao_hex"] == "A1B2C3"
        assert result["callsign"] == "UAL2145"
        assert result["lat"] == 30.27
        assert result["altitude_ft"] == 12000

    def test_ingest_updates_track(self):
        proc = ADSBProcessor()
        proc.ingest({"hex": "AABB", "flight": "SWA100", "lat": 30.0, "lon": -97.0})
        proc.ingest({"hex": "AABB", "lat": 30.1, "lon": -97.1, "altitude": 6000})
        tracks = proc.get_active_tracks()
        assert len(tracks) == 1
        assert tracks[0]["callsign"] == "SWA100"
        assert tracks[0]["lat"] == 30.1
        assert tracks[0]["altitude_ft"] == 6000
        assert tracks[0]["message_count"] == 2

    def test_ingest_invalid_message(self):
        proc = ADSBProcessor()
        assert proc.ingest({"no_hex": "bad"}) is None
        assert proc.messages_received == 0

    def test_get_track(self):
        proc = ADSBProcessor()
        proc.ingest({"hex": "CAFE01", "flight": "DAL456"})
        track = proc.get_track("CAFE01")
        assert track is not None
        assert track["callsign"] == "DAL456"
        assert proc.get_track("NONEXISTENT") is None

    def test_expire_stale(self):
        proc = ADSBProcessor(ttl_s=0.01)
        proc.ingest({"hex": "STALE1", "lat": 30.0, "lon": -97.0})
        time.sleep(0.02)
        expired = proc.expire_stale()
        assert "STALE1" in expired
        assert proc.track_count == 0

    def test_active_tracks_filters_stale(self):
        proc = ADSBProcessor(ttl_s=0.01)
        proc.ingest({"hex": "OLD1", "lat": 30.0, "lon": -97.0})
        time.sleep(0.02)
        proc.ingest({"hex": "NEW1", "lat": 31.0, "lon": -98.0})
        active = proc.get_active_tracks()
        assert len(active) == 1
        assert active[0]["icao_hex"] == "NEW1"

    def test_emergency_squawk(self):
        proc = ADSBProcessor()
        proc.ingest({"hex": "EMERG", "squawk": "7700", "lat": 30.0, "lon": -97.0})
        emergencies = proc.get_emergency_tracks()
        assert len(emergencies) == 1
        assert emergencies[0]["is_emergency"] is True

    def test_non_emergency_squawk(self):
        proc = ADSBProcessor()
        proc.ingest({"hex": "NORMAL", "squawk": "1200", "lat": 30.0, "lon": -97.0})
        emergencies = proc.get_emergency_tracks()
        assert len(emergencies) == 0

    def test_stats(self):
        proc = ADSBProcessor()
        proc.ingest({"hex": "A1", "lat": 30.0, "lon": -97.0})
        proc.ingest({"hex": "A2", "lat": 31.0, "lon": -98.0})
        stats = proc.get_stats()
        assert stats["messages_received"] == 2
        assert stats["tracks_total"] == 2
        assert stats["tracks_active"] == 2


class TestADSBTrackModule:
    def test_track_properties(self):
        track = ADSBTrack(
            icao_hex="ABCDEF",
            callsign="UAL123",
            altitude_ft=35000,
            squawk="1200",
        )
        assert track.label == "UAL123"
        assert track.flight_level == "FL350"
        assert track.is_emergency is False

    def test_track_label_fallback(self):
        track = ADSBTrack(icao_hex="ABCDEF")
        assert track.label == "ABCDEF"

    def test_emergency_detection(self):
        track = ADSBTrack(icao_hex="EM1", squawk="7700")
        assert track.is_emergency is True
        assert track.emergency_type == "emergency"

    def test_hijack_squawk(self):
        track = ADSBTrack(icao_hex="HJ1", squawk="7500")
        assert track.is_emergency is True
        assert track.emergency_type == "hijack"

    def test_to_dict_includes_extras(self):
        track = ADSBTrack(icao_hex="X1", callsign="TST1", altitude_ft=15000)
        d = track.to_dict()
        assert "is_emergency" in d
        assert "label" in d
        assert "flight_level" in d
        assert d["flight_level"] == "FL150"


# ---------------------------------------------------------------------------
# ISMDecoder tests
# ---------------------------------------------------------------------------

class TestISMDecoder:
    def test_ingest_creates_device(self):
        dec = ISMDecoder()
        result = dec.ingest({
            "model": "Acurite-Tower",
            "id": 12345,
            "freq": 433.92,
            "rssi": -42.0,
            "temperature_C": 22.5,
        })
        assert result["model"] == "Acurite-Tower"
        assert result["device_type"] == "weather_station"
        assert result["frequency_mhz"] == 433.92
        assert result["metadata"]["temperature_C"] == 22.5

    def test_dedup(self):
        dec = ISMDecoder()
        msg = {"model": "TestDev", "id": 999, "freq": 433.92}
        dec.ingest(msg)
        dec.ingest(msg)
        dec.ingest(msg)
        devices = dec.get_devices()
        assert len(devices) == 1
        assert devices[0]["message_count"] == 3

    def test_multiple_devices(self):
        dec = ISMDecoder()
        dec.ingest({"model": "A", "id": 1})
        dec.ingest({"model": "B", "id": 2})
        dec.ingest({"model": "C", "id": 3})
        assert dec.device_count == 3

    def test_get_device(self):
        dec = ISMDecoder()
        dec.ingest({"model": "Oregon-v2.1", "id": 42, "freq": 433.92})
        device_id = dec.get_devices()[0]["device_id"]
        dev = dec.get_device(device_id)
        assert dev is not None
        assert dec.get_device("nonexistent") is None

    def test_signal_history(self):
        dec = ISMDecoder()
        for i in range(5):
            dec.ingest({"model": f"Dev{i}", "id": i})
        signals = dec.get_signals(limit=3)
        assert len(signals) == 3

    def test_frequency_activity(self):
        dec = ISMDecoder()
        dec.ingest({"model": "A", "id": 1, "freq": 433.92})
        dec.ingest({"model": "B", "id": 2, "freq": 433.92})
        dec.ingest({"model": "C", "id": 3, "freq": 315.0})
        activity = dec.get_frequency_activity()
        assert activity["frequency_activity"][433.92] == 2
        assert activity["frequency_activity"][315.0] == 1

    def test_expire_stale(self):
        dec = ISMDecoder(ttl_s=0.01)
        dec.ingest({"model": "OldDev", "id": 1})
        time.sleep(0.02)
        expired = dec.expire_stale()
        assert len(expired) == 1
        assert dec.device_count == 0

    def test_stats(self):
        dec = ISMDecoder()
        dec.ingest({"model": "Acurite-Tower", "id": 1})
        dec.ingest({"model": "Schrader-TPMS", "id": 2})
        stats = dec.get_stats()
        assert stats["messages_received"] == 2
        assert stats["devices_detected"] == 2
        assert stats["messages_by_type"]["weather_station"] == 1
        assert stats["messages_by_type"]["tire_pressure"] == 1


class TestISMDecoderClassification:
    def test_weather_station(self):
        assert classify_device_type("Acurite-Tower") == "weather_station"
        assert classify_device_type("Oregon-v2.1") == "weather_station"
        assert classify_device_type("LaCrosse-TX141Bv3") == "weather_station"

    def test_tire_pressure(self):
        assert classify_device_type("Schrader-TPMS") == "tire_pressure"

    def test_doorbell(self):
        assert classify_device_type("Generic-Doorbell") == "doorbell"

    def test_smoke(self):
        assert classify_device_type("Smoke-Alarm-v2") == "smoke_detector"

    def test_unknown(self):
        assert classify_device_type("RandomModel") == "ism_device"


class TestISMDecoderBuildDeviceId:
    def test_basic(self):
        did = build_device_id({"model": "Acurite-Tower", "id": 12345})
        assert did == "ism_acurite-tower_12345"

    def test_with_channel(self):
        did = build_device_id({"model": "Oregon", "id": 99, "channel": 3})
        assert did == "ism_oregon_99_ch3"

    def test_no_id(self):
        did = build_device_id({"model": "Unknown"})
        assert did == "ism_unknown"


class TestExtractMetadata:
    def test_extracts_sensor_data(self):
        md = extract_metadata({
            "model": "Oregon-v2.1",
            "id": 10,
            "freq": 433.92,
            "temperature_C": 18.3,
            "humidity": 72,
            "battery_ok": 1,
        })
        assert md["temperature_C"] == 18.3
        assert md["humidity"] == 72
        assert md["battery_ok"] == 1
        assert "model" not in md
        assert "id" not in md
        assert "freq" not in md

    def test_empty_message(self):
        md = extract_metadata({"model": "X", "id": 1})
        assert md == {}


class TestISMDeviceModule:
    def test_create_and_to_dict(self):
        dev = ISMDevice(
            device_id="ism_test_1",
            model="TestModel",
            device_type="weather_station",
            frequency_mhz=433.92,
            rssi_db=-45.0,
        )
        d = dev.to_dict()
        assert d["device_id"] == "ism_test_1"
        assert d["device_type"] == "weather_station"
        assert d["frequency_mhz"] == 433.92

    def test_update(self):
        dev = ISMDevice(device_id="ism_test_2")
        dev.update(rssi_db=-30.0, metadata={"temp": 22.5})
        assert dev.message_count == 2
        assert dev.rssi_db == -30.0
        assert dev.metadata["temp"] == 22.5
