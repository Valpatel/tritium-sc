# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDRPlugin — Generic Software Defined Radio base plugin.

Handles common SDR functionality that any radio backend can use:
- MQTT subscriptions for decoded signals (rtl_433, dump1090, etc.)
- Detected RF device registry with dedup and aging
- Common API routes for spectrum, devices, signals, stats
- EventBus integration for real-time UI updates

Hardware-specific backends (HackRF, RTL-SDR, Airspy, LimeSDR)
subclass this and override the abstract methods for initialization,
tuning, and spectrum capture.

MQTT topics:
    IN:  tritium/{site}/sdr/{device}/signal   — decoded RF signal
    IN:  tritium/{site}/sdr/{device}/spectrum  — raw spectrum data
    IN:  tritium/{site}/sdr/{device}/adsb      — ADS-B aircraft data
    OUT: tritium/{site}/sdr/alerts             — RF anomaly alerts
"""

from __future__ import annotations

import logging
import threading
import time
import queue as queue_mod
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("sdr")

# How often to prune stale devices (seconds)
DEFAULT_POLL_INTERVAL = 5.0

# Time before a device is considered stale (seconds)
DEFAULT_DEVICE_TTL = 300.0

# Maximum history sizes
MAX_SIGNAL_HISTORY = 1000
MAX_SPECTRUM_HISTORY = 100
MAX_DEVICE_REGISTRY = 5000


class SDRDevice:
    """A detected RF device (ISM transmitter, weather station, tire sensor, etc.)."""

    __slots__ = (
        "device_id", "protocol", "model", "frequency_mhz",
        "rssi_db", "first_seen", "last_seen", "message_count",
        "metadata", "lat", "lon",
    )

    def __init__(
        self,
        device_id: str,
        protocol: str = "unknown",
        model: str = "unknown",
        frequency_mhz: float = 0.0,
        rssi_db: float = -100.0,
        metadata: Optional[dict] = None,
        lat: float = 0.0,
        lon: float = 0.0,
    ) -> None:
        self.device_id = device_id
        self.protocol = protocol
        self.model = model
        self.frequency_mhz = frequency_mhz
        self.rssi_db = rssi_db
        self.first_seen = time.time()
        self.last_seen = self.first_seen
        self.message_count = 1
        self.metadata = metadata or {}
        self.lat = lat
        self.lon = lon

    def update(self, rssi_db: float = -100.0, metadata: Optional[dict] = None) -> None:
        """Update device with a new sighting."""
        self.last_seen = time.time()
        self.message_count += 1
        self.rssi_db = rssi_db
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "protocol": self.protocol,
            "model": self.model,
            "frequency_mhz": self.frequency_mhz,
            "rssi_db": self.rssi_db,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
            "metadata": self.metadata,
            "lat": self.lat,
            "lon": self.lon,
        }


class SDRPlugin(PluginInterface):
    """Generic SDR plugin base class.

    Provides:
    - RF device registry with dedup and TTL-based aging
    - Signal history buffer
    - Spectrum data buffer
    - Common API routes (registered via routes.py)
    - EventBus integration for real-time updates

    Subclass this for hardware-specific SDR backends. Override:
    - ``_hw_init()``       — Initialize the SDR hardware
    - ``_hw_shutdown()``   — Shut down the SDR hardware
    - ``_hw_tune(freq_mhz, bandwidth_khz)`` — Tune to a frequency
    - ``_hw_get_spectrum()`` — Capture current spectrum data
    - ``_hw_get_config()`` — Return hardware-specific configuration
    - ``_hw_name``         — Human-readable hardware name
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        self._running = False
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._device_ttl = DEFAULT_DEVICE_TTL
        self._cleanup_thread: Optional[threading.Thread] = None
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

        # Device registry: device_id -> SDRDevice
        self._devices: dict[str, SDRDevice] = {}
        self._lock = threading.Lock()

        # Signal history (decoded messages from rtl_433, etc.)
        self._signal_history: list[dict] = []

        # Spectrum data buffer (raw FFT bins for waterfall display)
        self._spectrum_history: list[dict] = []

        # Current tuning
        self._center_freq_mhz: float = 433.92
        self._bandwidth_khz: float = 250.0
        self._gain_db: float = 40.0
        self._sample_rate_hz: int = 2_000_000

        # Statistics
        self._stats = {
            "signals_received": 0,
            "devices_detected": 0,
            "spectrum_captures": 0,
            "adsb_messages": 0,
            "errors": 0,
        }

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.sdr"

    @property
    def name(self) -> str:
        return f"SDR ({self._hw_name})"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- Hardware abstraction (override in subclasses) ---------------------

    @property
    def _hw_name(self) -> str:
        """Human-readable hardware backend name."""
        return "generic"

    def _hw_init(self) -> bool:
        """Initialize the SDR hardware. Return True on success."""
        return True

    def _hw_shutdown(self) -> None:
        """Shut down the SDR hardware."""

    def _hw_tune(self, freq_mhz: float, bandwidth_khz: float = 250.0) -> bool:
        """Tune to a center frequency. Return True on success."""
        return True

    def _hw_get_spectrum(self) -> Optional[dict]:
        """Capture current spectrum data.

        Returns dict with:
            center_freq_mhz: float
            bandwidth_khz: float
            bins: list[float]  — power in dB per FFT bin
            timestamp: float
        Or None if not available.
        """
        return None

    def _hw_get_config(self) -> dict:
        """Return hardware-specific configuration dict."""
        return {}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        settings = ctx.settings or {}
        if "poll_interval" in settings:
            self._poll_interval = float(settings["poll_interval"])
        if "device_ttl" in settings:
            self._device_ttl = float(settings["device_ttl"])
        if "center_freq_mhz" in settings:
            self._center_freq_mhz = float(settings["center_freq_mhz"])
        if "bandwidth_khz" in settings:
            self._bandwidth_khz = float(settings["bandwidth_khz"])
        if "gain_db" in settings:
            self._gain_db = float(settings["gain_db"])
        if "sample_rate_hz" in settings:
            self._sample_rate_hz = int(settings["sample_rate_hz"])

        # Register API routes
        self._register_routes()

        # Initialize hardware
        hw_ok = self._hw_init()
        self._logger.info(
            "SDR plugin configured (hw=%s, init=%s, freq=%.3f MHz)",
            self._hw_name, hw_ok, self._center_freq_mhz,
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Cleanup thread (prune stale devices)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="sdr-cleanup",
        )
        self._cleanup_thread.start()

        # EventBus subscriber
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="sdr-events",
            )
            self._event_thread.start()

        self._logger.info("SDR plugin started (hw=%s)", self._hw_name)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        self._hw_shutdown()

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=3.0)

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("SDR plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API (called by routes) -------------------------------------

    def get_devices(self, limit: int = 100) -> list[dict]:
        """Return detected RF devices, newest first."""
        with self._lock:
            devices = sorted(
                self._devices.values(),
                key=lambda d: d.last_seen,
                reverse=True,
            )
            return [d.to_dict() for d in devices[:limit]]

    def get_signals(self, limit: int = 100) -> list[dict]:
        """Return recent decoded signals."""
        with self._lock:
            return list(self._signal_history[-limit:])

    def get_spectrum(self) -> Optional[dict]:
        """Return the latest spectrum capture, or try a live capture."""
        # Try hardware capture first
        spectrum = self._hw_get_spectrum()
        if spectrum:
            self._record_spectrum(spectrum)
            return spectrum
        # Fall back to most recent buffered capture
        with self._lock:
            if self._spectrum_history:
                return self._spectrum_history[-1]
        return None

    def get_spectrum_history(self, limit: int = 50) -> list[dict]:
        """Return recent spectrum captures (for waterfall display)."""
        with self._lock:
            return list(self._spectrum_history[-limit:])

    def get_config(self) -> dict:
        """Return current SDR configuration."""
        base = {
            "hw_name": self._hw_name,
            "center_freq_mhz": self._center_freq_mhz,
            "bandwidth_khz": self._bandwidth_khz,
            "gain_db": self._gain_db,
            "sample_rate_hz": self._sample_rate_hz,
            "device_ttl": self._device_ttl,
        }
        base.update(self._hw_get_config())
        return base

    def tune(self, freq_mhz: float, bandwidth_khz: Optional[float] = None) -> dict:
        """Tune the SDR to a new frequency."""
        bw = bandwidth_khz if bandwidth_khz is not None else self._bandwidth_khz
        ok = self._hw_tune(freq_mhz, bw)
        if ok:
            self._center_freq_mhz = freq_mhz
            self._bandwidth_khz = bw
            self._logger.info("Tuned to %.3f MHz (BW=%.0f kHz)", freq_mhz, bw)
        return {
            "status": "ok" if ok else "error",
            "center_freq_mhz": self._center_freq_mhz,
            "bandwidth_khz": self._bandwidth_khz,
        }

    def get_stats(self) -> dict:
        """Return plugin statistics."""
        with self._lock:
            return {
                **self._stats,
                "device_count": len(self._devices),
                "signal_history_size": len(self._signal_history),
                "spectrum_history_size": len(self._spectrum_history),
                "hw_name": self._hw_name,
                "center_freq_mhz": self._center_freq_mhz,
                "running": self._running,
            }

    # -- Signal ingestion --------------------------------------------------

    def ingest_signal(self, signal: dict) -> None:
        """Process an incoming decoded RF signal (e.g., from rtl_433 MQTT).

        Expected fields (rtl_433 format):
            model: str          — device model name
            id: int/str         — device ID
            protocol: str       — protocol name (optional)
            freq: float         — frequency in MHz (optional)
            rssi: float         — signal strength in dB (optional)
            ... (any additional decoded fields)
        """
        now = time.time()
        model = signal.get("model", "unknown")
        dev_id_raw = signal.get("id", signal.get("device_id", ""))
        protocol = signal.get("protocol", model)
        freq = signal.get("freq", signal.get("frequency_mhz", self._center_freq_mhz))
        rssi = signal.get("rssi", signal.get("rssi_db", -100.0))

        # Build a unique device ID
        device_id = f"sdr_{protocol}_{dev_id_raw}" if dev_id_raw else f"sdr_{model}_{int(now)}"

        with self._lock:
            self._stats["signals_received"] += 1

            # Update or create device
            if device_id in self._devices:
                self._devices[device_id].update(rssi_db=rssi, metadata=signal)
            else:
                self._devices[device_id] = SDRDevice(
                    device_id=device_id,
                    protocol=protocol,
                    model=model,
                    frequency_mhz=freq,
                    rssi_db=rssi,
                    metadata=signal,
                )
                self._stats["devices_detected"] += 1

            # Record signal
            record = {
                "device_id": device_id,
                "model": model,
                "protocol": protocol,
                "frequency_mhz": freq,
                "rssi_db": rssi,
                "timestamp": now,
                "raw": signal,
            }
            self._signal_history.append(record)
            if len(self._signal_history) > MAX_SIGNAL_HISTORY:
                self._signal_history = self._signal_history[-MAX_SIGNAL_HISTORY:]

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish("sdr:signal", data=record)

        # Create/update target in tracker
        self._update_tracker_target(device_id, model, freq, rssi)

    def ingest_adsb(self, message: dict) -> None:
        """Process an ADS-B message (e.g., from dump1090 MQTT).

        Expected fields:
            hex: str        — ICAO hex address
            flight: str     — callsign (optional)
            lat: float      — latitude (optional)
            lon: float      — longitude (optional)
            altitude: int   — altitude in feet (optional)
            speed: float    — ground speed in knots (optional)
            track: float    — heading in degrees (optional)
            squawk: str     — squawk code (optional)
        """
        icao = message.get("hex", "").strip()
        if not icao:
            return

        with self._lock:
            self._stats["adsb_messages"] += 1

        target_id = f"adsb_{icao}"
        flight = message.get("flight", "").strip()
        lat = message.get("lat", 0.0)
        lon = message.get("lon", 0.0)
        alt = message.get("altitude", message.get("alt_baro", 0))

        record = {
            "target_id": target_id,
            "icao": icao,
            "flight": flight,
            "lat": lat,
            "lon": lon,
            "altitude_ft": alt,
            "speed_kts": message.get("speed", message.get("gs", 0.0)),
            "track_deg": message.get("track", 0.0),
            "squawk": message.get("squawk", ""),
            "timestamp": time.time(),
            "raw": message,
        }

        with self._lock:
            # Store as a device too
            if target_id in self._devices:
                self._devices[target_id].update(metadata=record)
                self._devices[target_id].lat = lat
                self._devices[target_id].lon = lon
            else:
                self._devices[target_id] = SDRDevice(
                    device_id=target_id,
                    protocol="adsb",
                    model=flight or icao,
                    frequency_mhz=1090.0,
                    rssi_db=-50.0,
                    metadata=record,
                    lat=lat,
                    lon=lon,
                )

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish("sdr:adsb", data=record)

        # Create/update ADS-B target
        if lat and lon and self._tracker:
            self._update_adsb_target(target_id, flight, icao, lat, lon, alt)

    # -- Target tracker integration ----------------------------------------

    def _update_tracker_target(
        self,
        device_id: str,
        model: str,
        freq_mhz: float,
        rssi_db: float,
    ) -> None:
        """Create or update a target in TargetTracker for a detected RF device."""
        if self._tracker is None:
            return
        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget

            with self._tracker._lock:
                if device_id in self._tracker._targets:
                    t = self._tracker._targets[device_id]
                    t.last_seen = time.monotonic()
                    t.status = f"rf:{model}:{freq_mhz:.1f}MHz"
                else:
                    self._tracker._targets[device_id] = TrackedTarget(
                        target_id=device_id,
                        name=f"RF: {model} ({freq_mhz:.1f} MHz)",
                        alliance="unknown",
                        asset_type="rf_device",
                        position=(0.0, 0.0),
                        last_seen=time.monotonic(),
                        source="sdr",
                        position_source="rf_signal",
                        position_confidence=0.1,
                        status=f"rf:{model}:{freq_mhz:.1f}MHz",
                    )
        except Exception as exc:
            log.error("Failed to update SDR target: %s", exc)

    def _update_adsb_target(
        self,
        target_id: str,
        flight: str,
        icao: str,
        lat: float,
        lon: float,
        alt_ft: int,
    ) -> None:
        """Create or update an ADS-B aircraft target."""
        if self._tracker is None:
            return
        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget

            label = flight if flight else icao
            with self._tracker._lock:
                if target_id in self._tracker._targets:
                    t = self._tracker._targets[target_id]
                    t.last_seen = time.monotonic()
                    t.position = (lat, lon)
                    t.status = f"adsb:{label}:FL{alt_ft // 100}"
                else:
                    self._tracker._targets[target_id] = TrackedTarget(
                        target_id=target_id,
                        name=f"Aircraft: {label}",
                        alliance="unknown",
                        asset_type="aircraft",
                        position=(lat, lon),
                        last_seen=time.monotonic(),
                        source="sdr",
                        position_source="adsb",
                        position_confidence=0.95,
                        status=f"adsb:{label}:FL{alt_ft // 100}",
                    )
        except Exception as exc:
            log.error("Failed to update ADS-B target: %s", exc)

    # -- Spectrum recording ------------------------------------------------

    def _record_spectrum(self, spectrum: dict) -> None:
        """Buffer a spectrum capture for waterfall display."""
        with self._lock:
            self._stats["spectrum_captures"] += 1
            self._spectrum_history.append(spectrum)
            if len(self._spectrum_history) > MAX_SPECTRUM_HISTORY:
                self._spectrum_history = self._spectrum_history[-MAX_SPECTRUM_HISTORY:]

    # -- Cleanup loop ------------------------------------------------------

    def _cleanup_loop(self) -> None:
        """Background: prune stale devices past TTL."""
        while self._running:
            try:
                now = time.time()
                expired = []
                with self._lock:
                    for did, dev in self._devices.items():
                        if now - dev.last_seen > self._device_ttl:
                            expired.append(did)
                    for did in expired:
                        del self._devices[did]

                # Remove from tracker
                if self._tracker and expired:
                    try:
                        with self._tracker._lock:
                            for did in expired:
                                self._tracker._targets.pop(did, None)
                    except Exception:
                        pass

            except Exception as exc:
                log.error("SDR cleanup error: %s", exc)

            deadline = time.monotonic() + self._poll_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- EventBus listener -------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Background: drain EventBus for incoming SDR data."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("SDR event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process incoming events: MQTT-bridged rtl_433 / dump1090 data."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type in ("sdr:raw_signal", "rtl_433:message"):
            self.ingest_signal(data)
        elif event_type in ("sdr:adsb", "dump1090:message", "adsb:message"):
            self.ingest_adsb(data)
        elif event_type == "sdr:spectrum":
            self._record_spectrum(data)

    # -- Route registration ------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
