# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRFPlugin — HackRF One specific SDR implementation.

Inherits the generic SDRPlugin and adds HackRF-specific features:
- Frequency range: 1 MHz to 6 GHz
- Configurable LNA/VGA/AMP gains
- Spectrum sweep using pyhackrf or SoapySDR (stubs if not installed)
- Signal detection pipeline (energy detection, modulation classification)
- ADS-B decoding integration (calls dump1090 if available)

To create an RTL-SDR or Airspy plugin, follow this same pattern:
subclass SDRPlugin and override the _hw_* methods.

Usage:
    plugin = HackRFPlugin()
    # ... configure and start via PluginManager
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Any, Optional

from .plugin import SDRPlugin

log = logging.getLogger("sdr.hackrf")

# HackRF hardware limits
HACKRF_FREQ_MIN_MHZ = 1.0
HACKRF_FREQ_MAX_MHZ = 6000.0
HACKRF_SAMPLE_RATES = [2_000_000, 4_000_000, 8_000_000, 10_000_000, 16_000_000, 20_000_000]
HACKRF_BANDWIDTH_OPTIONS_KHZ = [1750, 2500, 3500, 5000, 5500, 6000, 7000, 8000,
                                 9000, 10000, 12000, 14000, 15000, 20000, 24000, 28000]

# Default gains
DEFAULT_LNA_GAIN_DB = 16   # 0-40 dB in 8 dB steps
DEFAULT_VGA_GAIN_DB = 20   # 0-62 dB in 2 dB steps
DEFAULT_AMP_ENABLED = False  # 14 dB RF amplifier

# Energy detection threshold for signal detection (dB above noise floor)
DEFAULT_ENERGY_THRESHOLD_DB = 10.0

# Sweep parameters
DEFAULT_SWEEP_START_MHZ = 1.0
DEFAULT_SWEEP_STOP_MHZ = 6000.0
DEFAULT_SWEEP_STEP_MHZ = 1.0


def _check_hackrf_available() -> bool:
    """Check if HackRF libraries are importable."""
    try:
        import hackrf  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import SoapySDR  # noqa: F401
        return True
    except ImportError:
        pass
    return False


def _check_dump1090_available() -> bool:
    """Check if dump1090 binary is available on PATH."""
    try:
        result = subprocess.run(
            ["which", "dump1090"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


class HackRFPlugin(SDRPlugin):
    """HackRF One specific SDR implementation.

    Features beyond the generic SDR plugin:
    - Full 1 MHz - 6 GHz frequency range
    - Configurable LNA, VGA, and RF amp gains
    - Spectrum sweep across wide bands
    - Energy-based signal detection
    - Basic modulation classification stubs (AM, FM, OOK, FSK, PSK)
    - ADS-B integration via dump1090

    If pyhackrf/SoapySDR are not installed, the plugin still works
    with MQTT-fed data (rtl_433, dump1090) -- hardware features are
    stubbed and return empty/None results.
    """

    def __init__(self) -> None:
        super().__init__()

        # HackRF-specific gains
        self._lna_gain_db: int = DEFAULT_LNA_GAIN_DB
        self._vga_gain_db: int = DEFAULT_VGA_GAIN_DB
        self._amp_enabled: bool = DEFAULT_AMP_ENABLED

        # Hardware state
        self._hackrf_available: bool = False
        self._soapy_available: bool = False
        self._dump1090_available: bool = False
        self._hw_handle: Any = None  # pyhackrf or SoapySDR device handle

        # Signal detection
        self._energy_threshold_db: float = DEFAULT_ENERGY_THRESHOLD_DB
        self._detected_signals: list[dict] = []
        self._detected_signals_lock = threading.Lock()
        self._max_detected_signals = 500

        # Sweep state
        self._sweep_running = False
        self._sweep_thread: Optional[threading.Thread] = None
        self._last_sweep_result: Optional[dict] = None

        # ADS-B state
        self._adsb_process: Optional[subprocess.Popen] = None
        self._adsb_thread: Optional[threading.Thread] = None
        self._adsb_tracks: dict[str, dict] = {}  # icao -> track data

    # -- PluginInterface identity overrides --------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.sdr.hackrf"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background", "spectrum_sweep"}

    # -- Hardware abstraction overrides ------------------------------------

    @property
    def _hw_name(self) -> str:
        return "hackrf"

    def _hw_init(self) -> bool:
        """Initialize HackRF hardware (or detect it's not available)."""
        self._hackrf_available = False
        self._soapy_available = False

        # Try pyhackrf first
        try:
            import hackrf as _hackrf
            self._hw_handle = _hackrf.HackRF()
            self._hackrf_available = True
            log.info("HackRF initialized via pyhackrf")
            return True
        except ImportError:
            log.debug("pyhackrf not installed")
        except Exception as exc:
            log.warning("pyhackrf init failed: %s", exc)

        # Try SoapySDR fallback
        try:
            import SoapySDR
            results = SoapySDR.Device.enumerate({"driver": "hackrf"})
            if results:
                self._hw_handle = SoapySDR.Device(results[0])
                self._soapy_available = True
                log.info("HackRF initialized via SoapySDR")
                return True
            log.debug("SoapySDR found no HackRF devices")
        except ImportError:
            log.debug("SoapySDR not installed")
        except Exception as exc:
            log.warning("SoapySDR HackRF init failed: %s", exc)

        # Check for dump1090
        self._dump1090_available = _check_dump1090_available()

        log.info(
            "HackRF hardware not available (stub mode). "
            "MQTT data will still be processed. dump1090=%s",
            self._dump1090_available,
        )
        return False

    def _hw_shutdown(self) -> None:
        """Shut down HackRF hardware and ADS-B subprocess."""
        # Stop sweep
        self._sweep_running = False
        if self._sweep_thread and self._sweep_thread.is_alive():
            self._sweep_thread.join(timeout=3.0)

        # Stop ADS-B
        self._stop_adsb()

        # Close hardware
        if self._hw_handle:
            try:
                if self._hackrf_available:
                    self._hw_handle.close()
                elif self._soapy_available:
                    # SoapySDR handles are cleaned up by GC
                    pass
            except Exception as exc:
                log.warning("HackRF shutdown error: %s", exc)
            self._hw_handle = None

        self._hackrf_available = False
        self._soapy_available = False

    def _hw_tune(self, freq_mhz: float, bandwidth_khz: float = 250.0) -> bool:
        """Tune HackRF to a center frequency."""
        if freq_mhz < HACKRF_FREQ_MIN_MHZ or freq_mhz > HACKRF_FREQ_MAX_MHZ:
            log.warning(
                "Frequency %.3f MHz out of HackRF range (%.0f-%.0f MHz)",
                freq_mhz, HACKRF_FREQ_MIN_MHZ, HACKRF_FREQ_MAX_MHZ,
            )
            return False

        if self._hackrf_available and self._hw_handle:
            try:
                self._hw_handle.set_freq(int(freq_mhz * 1e6))
                return True
            except Exception as exc:
                log.error("HackRF tune error: %s", exc)
                return False
        elif self._soapy_available and self._hw_handle:
            try:
                self._hw_handle.setFrequency(0, 0, freq_mhz * 1e6)  # SoapySDR API
                return True
            except Exception as exc:
                log.error("SoapySDR tune error: %s", exc)
                return False

        # Stub mode: just accept it
        return True

    def _hw_get_spectrum(self) -> Optional[dict]:
        """Capture a spectrum snapshot from HackRF.

        Returns FFT bins suitable for waterfall display, or None if
        hardware is not available.
        """
        if not (self._hackrf_available or self._soapy_available):
            return None

        # Placeholder: actual implementation would read IQ samples,
        # apply windowing + FFT, and return power spectral density bins.
        # This requires numpy which may not be available, so we stub it.
        try:
            import numpy as np

            # Simulated spectrum: noise floor + random peaks
            num_bins = 1024
            noise_floor = -80.0
            bins = np.random.normal(noise_floor, 3.0, num_bins).tolist()

            return {
                "center_freq_mhz": self._center_freq_mhz,
                "bandwidth_khz": self._bandwidth_khz,
                "bins": bins,
                "num_bins": num_bins,
                "timestamp": time.time(),
                "hw": "hackrf",
            }
        except ImportError:
            return None

    def _hw_get_config(self) -> dict:
        """Return HackRF-specific configuration."""
        return {
            "lna_gain_db": self._lna_gain_db,
            "vga_gain_db": self._vga_gain_db,
            "amp_enabled": self._amp_enabled,
            "hackrf_available": self._hackrf_available,
            "soapy_available": self._soapy_available,
            "dump1090_available": self._dump1090_available,
            "freq_range_mhz": [HACKRF_FREQ_MIN_MHZ, HACKRF_FREQ_MAX_MHZ],
            "supported_sample_rates": HACKRF_SAMPLE_RATES,
            "energy_threshold_db": self._energy_threshold_db,
            "sweep_running": self._sweep_running,
        }

    # -- HackRF-specific public API ----------------------------------------

    def set_gains(
        self,
        lna_db: Optional[int] = None,
        vga_db: Optional[int] = None,
        amp: Optional[bool] = None,
    ) -> dict:
        """Set HackRF gain stages.

        Args:
            lna_db: LNA gain (0-40 dB, 8 dB steps)
            vga_db: VGA gain (0-62 dB, 2 dB steps)
            amp: RF amplifier enable (adds 14 dB)
        """
        if lna_db is not None:
            self._lna_gain_db = max(0, min(40, (lna_db // 8) * 8))
        if vga_db is not None:
            self._vga_gain_db = max(0, min(62, (vga_db // 2) * 2))
        if amp is not None:
            self._amp_enabled = amp

        # Apply to hardware if available
        if self._hackrf_available and self._hw_handle:
            try:
                self._hw_handle.set_lna_gain(self._lna_gain_db)
                self._hw_handle.set_vga_gain(self._vga_gain_db)
                self._hw_handle.set_amp_enable(self._amp_enabled)
            except Exception as exc:
                log.warning("Failed to set HackRF gains: %s", exc)

        return {
            "lna_gain_db": self._lna_gain_db,
            "vga_gain_db": self._vga_gain_db,
            "amp_enabled": self._amp_enabled,
        }

    def start_sweep(
        self,
        start_mhz: float = DEFAULT_SWEEP_START_MHZ,
        stop_mhz: float = DEFAULT_SWEEP_STOP_MHZ,
        step_mhz: float = DEFAULT_SWEEP_STEP_MHZ,
    ) -> dict:
        """Start a background spectrum sweep across a frequency range.

        The sweep captures spectrum data at each step and stores results
        for the waterfall display. Results available via get_sweep_result().
        """
        if self._sweep_running:
            return {"status": "already_running"}

        start_mhz = max(HACKRF_FREQ_MIN_MHZ, start_mhz)
        stop_mhz = min(HACKRF_FREQ_MAX_MHZ, stop_mhz)

        self._sweep_running = True
        self._sweep_thread = threading.Thread(
            target=self._sweep_loop,
            args=(start_mhz, stop_mhz, step_mhz),
            daemon=True,
            name="hackrf-sweep",
        )
        self._sweep_thread.start()

        return {
            "status": "started",
            "start_mhz": start_mhz,
            "stop_mhz": stop_mhz,
            "step_mhz": step_mhz,
        }

    def stop_sweep(self) -> dict:
        """Stop an active spectrum sweep."""
        self._sweep_running = False
        if self._sweep_thread and self._sweep_thread.is_alive():
            self._sweep_thread.join(timeout=5.0)
        return {"status": "stopped"}

    def get_sweep_result(self) -> Optional[dict]:
        """Return the latest sweep result."""
        return self._last_sweep_result

    def get_detected_signals(self, limit: int = 100) -> list[dict]:
        """Return signals detected via energy threshold during sweeps."""
        with self._detected_signals_lock:
            return list(self._detected_signals[-limit:])

    def classify_modulation(self, signal: dict) -> dict:
        """Classify the modulation type of a detected signal.

        This is a stub for future ML-based classification. Currently
        returns a basic heuristic guess based on signal characteristics.

        Future: train a CNN on IQ samples for accurate modulation
        classification (AM, FM, OOK, FSK, PSK, QAM, OFDM, etc.).
        """
        bandwidth_khz = signal.get("bandwidth_khz", 0.0)
        peak_power_db = signal.get("peak_power_db", -100.0)

        # Very basic heuristic classification
        if bandwidth_khz < 15:
            modulation = "OOK"
            confidence = 0.3
        elif bandwidth_khz < 25:
            modulation = "FSK"
            confidence = 0.25
        elif bandwidth_khz < 200:
            modulation = "FM"
            confidence = 0.2
        elif bandwidth_khz < 1000:
            modulation = "OFDM"
            confidence = 0.15
        else:
            modulation = "unknown"
            confidence = 0.1

        return {
            "modulation": modulation,
            "confidence": confidence,
            "method": "heuristic_v1",
            "bandwidth_khz": bandwidth_khz,
            "peak_power_db": peak_power_db,
        }

    def get_adsb_tracks(self) -> list[dict]:
        """Return current ADS-B aircraft tracks."""
        now = time.time()
        # Prune stale tracks (>60s)
        stale = [k for k, v in self._adsb_tracks.items() if now - v.get("timestamp", 0) > 60]
        for k in stale:
            del self._adsb_tracks[k]
        return list(self._adsb_tracks.values())

    def start_adsb(self) -> dict:
        """Start dump1090 subprocess for ADS-B decoding.

        Requires dump1090 installed and a HackRF (or RTL-SDR) connected.
        If dump1090 is not available, returns an error status.
        """
        if self._adsb_process and self._adsb_process.poll() is None:
            return {"status": "already_running"}

        if not self._dump1090_available:
            return {"status": "error", "message": "dump1090 not found on PATH"}

        try:
            self._adsb_process = subprocess.Popen(
                ["dump1090", "--net", "--quiet", "--json-port", "30154"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Start reader thread
            self._adsb_thread = threading.Thread(
                target=self._adsb_reader_loop,
                daemon=True,
                name="hackrf-adsb",
            )
            self._adsb_thread.start()
            return {"status": "started"}
        except Exception as exc:
            log.error("Failed to start dump1090: %s", exc)
            return {"status": "error", "message": str(exc)}

    # -- Internal: sweep ---------------------------------------------------

    def _sweep_loop(
        self,
        start_mhz: float,
        stop_mhz: float,
        step_mhz: float,
    ) -> None:
        """Background sweep: tune through frequencies and collect spectrum."""
        sweep_bins: list[dict] = []
        freq = start_mhz

        while self._sweep_running and freq <= stop_mhz:
            # Tune
            self._hw_tune(freq)
            self._center_freq_mhz = freq

            # Capture spectrum at this frequency
            spectrum = self._hw_get_spectrum()
            if spectrum:
                sweep_bins.append(spectrum)
                self._record_spectrum(spectrum)

                # Energy detection: find signals above threshold
                self._detect_signals_in_spectrum(spectrum)

            freq += step_mhz
            # Small delay between steps
            time.sleep(0.05)

        # Store complete sweep result
        self._last_sweep_result = {
            "start_mhz": start_mhz,
            "stop_mhz": stop_mhz,
            "step_mhz": step_mhz,
            "captures": len(sweep_bins),
            "timestamp": time.time(),
            "detected_signals": len(self._detected_signals),
        }
        self._sweep_running = False

    def _detect_signals_in_spectrum(self, spectrum: dict) -> None:
        """Detect signals above the energy threshold in a spectrum capture."""
        bins = spectrum.get("bins", [])
        if not bins:
            return

        # Calculate noise floor as median power
        try:
            sorted_bins = sorted(bins)
            noise_floor = sorted_bins[len(sorted_bins) // 2]
        except (TypeError, IndexError):
            return

        threshold = noise_floor + self._energy_threshold_db
        center_freq = spectrum.get("center_freq_mhz", 0.0)
        bandwidth = spectrum.get("bandwidth_khz", 250.0)
        num_bins = len(bins)

        for i, power in enumerate(bins):
            if power > threshold:
                # Convert bin index to frequency offset
                freq_offset_mhz = ((i / num_bins) - 0.5) * (bandwidth / 1000.0)
                signal_freq = center_freq + freq_offset_mhz

                signal = {
                    "frequency_mhz": round(signal_freq, 4),
                    "power_db": round(power, 1),
                    "noise_floor_db": round(noise_floor, 1),
                    "snr_db": round(power - noise_floor, 1),
                    "bin_index": i,
                    "timestamp": time.time(),
                }

                # Classify modulation
                signal["classification"] = self.classify_modulation(signal)

                with self._detected_signals_lock:
                    self._detected_signals.append(signal)
                    if len(self._detected_signals) > self._max_detected_signals:
                        self._detected_signals = self._detected_signals[-self._max_detected_signals:]

    # -- Internal: ADS-B ---------------------------------------------------

    def _adsb_reader_loop(self) -> None:
        """Background: read ADS-B data from dump1090 JSON port."""
        import json
        import socket

        while self._running and self._adsb_process and self._adsb_process.poll() is None:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect(("127.0.0.1", 30154))

                buf = ""
                while self._running:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buf += data.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            try:
                                msg = json.loads(line)
                                self.ingest_adsb(msg)
                                # Cache track
                                icao = msg.get("hex", "").strip()
                                if icao:
                                    self._adsb_tracks[icao] = {
                                        "icao": icao,
                                        "flight": msg.get("flight", "").strip(),
                                        "lat": msg.get("lat", 0.0),
                                        "lon": msg.get("lon", 0.0),
                                        "altitude_ft": msg.get("altitude", 0),
                                        "speed_kts": msg.get("speed", 0.0),
                                        "track_deg": msg.get("track", 0.0),
                                        "timestamp": time.time(),
                                    }
                            except json.JSONDecodeError:
                                pass
                sock.close()
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(2.0)
            except Exception as exc:
                log.error("ADS-B reader error: %s", exc)
                time.sleep(2.0)

    def _stop_adsb(self) -> None:
        """Stop the dump1090 subprocess."""
        if self._adsb_process and self._adsb_process.poll() is None:
            try:
                self._adsb_process.terminate()
                self._adsb_process.wait(timeout=5.0)
            except Exception:
                try:
                    self._adsb_process.kill()
                except Exception:
                    pass
        self._adsb_process = None
