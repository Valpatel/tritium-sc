# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the generic SDR plugin and HackRF implementation.

Tests cover:
- Plugin identity and lifecycle
- RF device registry (ingest, dedup, aging)
- Signal history
- ADS-B ingestion
- HackRF-specific: gains, frequency validation, modulation classification
- Route creation
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from sdr.plugin import SDRPlugin, SDRDevice
from sdr.hackrf import HackRFPlugin, HACKRF_FREQ_MIN_MHZ, HACKRF_FREQ_MAX_MHZ


# -- SDRDevice tests -------------------------------------------------------

class TestSDRDevice:
    def test_create_device(self):
        dev = SDRDevice(
            device_id="sdr_acurite_123",
            protocol="acurite",
            model="Acurite-Tower",
            frequency_mhz=433.92,
            rssi_db=-45.0,
        )
        assert dev.device_id == "sdr_acurite_123"
        assert dev.protocol == "acurite"
        assert dev.model == "Acurite-Tower"
        assert dev.frequency_mhz == 433.92
        assert dev.rssi_db == -45.0
        assert dev.message_count == 1

    def test_update_device(self):
        dev = SDRDevice(device_id="sdr_test_1")
        first_seen = dev.first_seen
        time.sleep(0.01)
        dev.update(rssi_db=-30.0, metadata={"temp_c": 22.5})
        assert dev.message_count == 2
        assert dev.rssi_db == -30.0
        assert dev.metadata["temp_c"] == 22.5
        assert dev.first_seen == first_seen
        assert dev.last_seen > first_seen

    def test_to_dict(self):
        dev = SDRDevice(device_id="sdr_test_2", model="WeatherStation")
        d = dev.to_dict()
        assert d["device_id"] == "sdr_test_2"
        assert d["model"] == "WeatherStation"
        assert "first_seen" in d
        assert "last_seen" in d
        assert "metadata" in d


# -- Generic SDR plugin tests ---------------------------------------------

class TestSDRPlugin:
    def _make_plugin(self):
        p = SDRPlugin()
        p._logger = MagicMock()
        return p

    def test_plugin_identity(self):
        p = self._make_plugin()
        assert p.plugin_id == "tritium.sdr"
        assert "SDR" in p.name
        assert p.version == "1.0.0"
        assert "data_source" in p.capabilities
        assert "routes" in p.capabilities

    def test_ingest_signal_creates_device(self):
        p = self._make_plugin()
        p.ingest_signal({
            "model": "Acurite-Tower",
            "id": 12345,
            "protocol": "acurite",
            "freq": 433.92,
            "rssi": -42.0,
            "temperature_C": 22.5,
        })
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["model"] == "Acurite-Tower"
        assert devices[0]["rssi_db"] == -42.0
        assert p._stats["signals_received"] == 1
        assert p._stats["devices_detected"] == 1

    def test_ingest_signal_dedup(self):
        p = self._make_plugin()
        signal = {"model": "Test", "id": 999, "protocol": "test", "rssi": -50.0}
        p.ingest_signal(signal)
        p.ingest_signal(signal)
        p.ingest_signal(signal)
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["message_count"] == 3
        assert p._stats["signals_received"] == 3
        assert p._stats["devices_detected"] == 1

    def test_signal_history(self):
        p = self._make_plugin()
        for i in range(5):
            p.ingest_signal({"model": f"Dev{i}", "id": i, "protocol": "test"})
        signals = p.get_signals(limit=3)
        assert len(signals) == 3
        signals_all = p.get_signals(limit=100)
        assert len(signals_all) == 5

    def test_ingest_adsb(self):
        p = self._make_plugin()
        p.ingest_adsb({
            "hex": "A1B2C3",
            "flight": "UAL123",
            "lat": 40.7128,
            "lon": -74.0060,
            "altitude": 35000,
            "speed": 450.0,
            "track": 90.0,
        })
        devices = p.get_devices()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "adsb_A1B2C3"
        assert devices[0]["protocol"] == "adsb"
        assert p._stats["adsb_messages"] == 1

    def test_tune(self):
        p = self._make_plugin()
        result = p.tune(915.0, 500.0)
        assert result["status"] == "ok"
        assert p._center_freq_mhz == 915.0
        assert p._bandwidth_khz == 500.0

    def test_get_config(self):
        p = self._make_plugin()
        config = p.get_config()
        assert "center_freq_mhz" in config
        assert "bandwidth_khz" in config
        assert "hw_name" in config

    def test_get_stats(self):
        p = self._make_plugin()
        stats = p.get_stats()
        assert stats["signals_received"] == 0
        assert stats["device_count"] == 0
        assert stats["running"] is False

    def test_spectrum_no_hardware(self):
        p = self._make_plugin()
        # Generic plugin has no hardware — should return None
        assert p.get_spectrum() is None

    def test_spectrum_history_buffered(self):
        p = self._make_plugin()
        p._record_spectrum({
            "center_freq_mhz": 433.92,
            "bins": [1.0, 2.0, 3.0],
            "timestamp": time.time(),
        })
        spectrum = p.get_spectrum()
        assert spectrum is not None
        assert spectrum["center_freq_mhz"] == 433.92

    def test_event_handling_signal(self):
        p = self._make_plugin()
        p._handle_event({
            "type": "rtl_433:message",
            "data": {"model": "Tire-TPMS", "id": 42, "protocol": "tpms"},
        })
        assert p._stats["signals_received"] == 1

    def test_event_handling_adsb(self):
        p = self._make_plugin()
        p._handle_event({
            "type": "dump1090:message",
            "data": {"hex": "AABBCC", "flight": "DAL456", "lat": 33.0, "lon": -118.0},
        })
        assert p._stats["adsb_messages"] == 1

    def test_event_handling_spectrum(self):
        p = self._make_plugin()
        p._handle_event({
            "type": "sdr:spectrum",
            "data": {"center_freq_mhz": 900.0, "bins": [0.0], "timestamp": 1.0},
        })
        assert p._stats["spectrum_captures"] == 1

    def test_configure_with_settings(self):
        p = self._make_plugin()
        ctx = MagicMock()
        ctx.settings = {
            "center_freq_mhz": 915.0,
            "gain_db": 30.0,
            "device_ttl": 600.0,
        }
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = MagicMock()
        p.configure(ctx)
        assert p._center_freq_mhz == 915.0
        assert p._gain_db == 30.0
        assert p._device_ttl == 600.0

    def test_eventbus_publish_on_signal(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.ingest_signal({"model": "Test", "id": 1, "protocol": "test"})
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "sdr:signal"

    def test_eventbus_publish_on_adsb(self):
        p = self._make_plugin()
        bus = MagicMock()
        p._event_bus = bus
        p.ingest_adsb({"hex": "ABCDEF"})
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "sdr:adsb"


# -- HackRF plugin tests --------------------------------------------------

class TestHackRFPlugin:
    def _make_plugin(self):
        p = HackRFPlugin()
        p._logger = MagicMock()
        return p

    def test_plugin_identity(self):
        p = self._make_plugin()
        assert p.plugin_id == "tritium.sdr.hackrf"
        assert "hackrf" in p.name.lower() or "SDR" in p.name
        assert "spectrum_sweep" in p.capabilities

    def test_inherits_sdr_plugin(self):
        p = self._make_plugin()
        assert isinstance(p, SDRPlugin)

    def test_hw_init_stub_mode(self):
        """Without pyhackrf or SoapySDR, init returns False (stub mode)."""
        p = self._make_plugin()
        result = p._hw_init()
        # In test env, neither pyhackrf nor SoapySDR is installed
        assert result is False
        assert p._hackrf_available is False
        assert p._soapy_available is False

    def test_tune_valid_range(self):
        p = self._make_plugin()
        assert p._hw_tune(433.92) is True
        assert p._hw_tune(1090.0) is True
        assert p._hw_tune(2400.0) is True
        assert p._hw_tune(5800.0) is True

    def test_tune_out_of_range(self):
        p = self._make_plugin()
        assert p._hw_tune(0.5) is False   # below 1 MHz
        assert p._hw_tune(7000.0) is False  # above 6 GHz

    def test_set_gains(self):
        p = self._make_plugin()
        result = p.set_gains(lna_db=24, vga_db=30, amp=True)
        assert result["lna_gain_db"] == 24
        assert result["vga_gain_db"] == 30
        assert result["amp_enabled"] is True

    def test_gain_clamping(self):
        p = self._make_plugin()
        result = p.set_gains(lna_db=100, vga_db=100)
        assert result["lna_gain_db"] == 40   # max LNA
        assert result["vga_gain_db"] == 62   # max VGA

    def test_gain_stepping(self):
        p = self._make_plugin()
        # LNA: 8 dB steps, VGA: 2 dB steps
        result = p.set_gains(lna_db=13, vga_db=15)
        assert result["lna_gain_db"] == 8    # rounded down to 8 dB step
        assert result["vga_gain_db"] == 14   # rounded down to 2 dB step

    def test_get_config_hackrf(self):
        p = self._make_plugin()
        config = p._hw_get_config()
        assert "lna_gain_db" in config
        assert "vga_gain_db" in config
        assert "amp_enabled" in config
        assert "freq_range_mhz" in config
        assert config["freq_range_mhz"] == [HACKRF_FREQ_MIN_MHZ, HACKRF_FREQ_MAX_MHZ]

    def test_classify_modulation_narrow(self):
        p = self._make_plugin()
        result = p.classify_modulation({"bandwidth_khz": 10.0})
        assert result["modulation"] == "OOK"
        assert result["method"] == "heuristic_v1"

    def test_classify_modulation_medium(self):
        p = self._make_plugin()
        result = p.classify_modulation({"bandwidth_khz": 20.0})
        assert result["modulation"] == "FSK"

    def test_classify_modulation_wide(self):
        p = self._make_plugin()
        result = p.classify_modulation({"bandwidth_khz": 100.0})
        assert result["modulation"] == "FM"

    def test_classify_modulation_very_wide(self):
        p = self._make_plugin()
        result = p.classify_modulation({"bandwidth_khz": 500.0})
        assert result["modulation"] == "OFDM"

    def test_classify_modulation_unknown(self):
        p = self._make_plugin()
        result = p.classify_modulation({"bandwidth_khz": 5000.0})
        assert result["modulation"] == "unknown"

    def test_adsb_tracks_empty(self):
        p = self._make_plugin()
        assert p.get_adsb_tracks() == []

    def test_adsb_tracks_stale_pruning(self):
        p = self._make_plugin()
        p._adsb_tracks["ABC123"] = {
            "icao": "ABC123",
            "timestamp": time.time() - 120,  # 2 minutes old
        }
        tracks = p.get_adsb_tracks()
        assert len(tracks) == 0  # pruned

    def test_detected_signals_empty(self):
        p = self._make_plugin()
        assert p.get_detected_signals() == []

    def test_sweep_not_running_initially(self):
        p = self._make_plugin()
        assert p._sweep_running is False
        assert p.get_sweep_result() is None

    def test_stop_sweep_when_not_running(self):
        p = self._make_plugin()
        result = p.stop_sweep()
        assert result["status"] == "stopped"

    def test_energy_detection(self):
        """Test signal detection in spectrum data."""
        p = self._make_plugin()
        spectrum = {
            "center_freq_mhz": 433.92,
            "bandwidth_khz": 250.0,
            # Most bins at -80 dB (noise), one spike at -40 dB
            "bins": [-80.0] * 511 + [-40.0] + [-80.0] * 512,
        }
        p._detect_signals_in_spectrum(spectrum)
        signals = p.get_detected_signals()
        assert len(signals) >= 1
        # The spike should be detected
        spike = signals[0]
        assert spike["snr_db"] > 10.0

    def test_full_ingest_pipeline_inherited(self):
        """HackRF inherits all generic SDR ingest methods."""
        p = self._make_plugin()
        p.ingest_signal({"model": "Oregon-v2", "id": 555, "protocol": "oregon"})
        assert p._stats["signals_received"] == 1
        devices = p.get_devices()
        assert len(devices) == 1

    def test_start_adsb_no_dump1090(self):
        """Without dump1090 installed, start_adsb returns error."""
        p = self._make_plugin()
        p._dump1090_available = False
        result = p.start_adsb()
        assert result["status"] == "error"


# -- Route creation test ---------------------------------------------------

class TestSDRRoutes:
    def test_create_router_generic(self):
        from sdr.routes import create_router
        plugin = SDRPlugin()
        plugin._logger = MagicMock()
        router = create_router(plugin)
        # Routes include the /api/sdr prefix
        paths = [r.path for r in router.routes]
        assert "/api/sdr/devices" in paths
        assert "/api/sdr/spectrum" in paths
        assert "/api/sdr/signals" in paths
        assert "/api/sdr/config" in paths
        assert "/api/sdr/tune" in paths
        assert "/api/sdr/stats" in paths
        assert "/api/sdr/health" in paths
        assert "/api/sdr/adsb" in paths

    def test_create_router_hackrf(self):
        from sdr.routes import create_router
        plugin = HackRFPlugin()
        plugin._logger = MagicMock()
        router = create_router(plugin)
        paths = [r.path for r in router.routes]
        # HackRF-specific routes should also be present
        assert "/api/sdr/gains" in paths
        assert "/api/sdr/sweep/start" in paths
        assert "/api/sdr/sweep/stop" in paths
        assert "/api/sdr/sweep/result" in paths
        assert "/api/sdr/signals/detected" in paths
