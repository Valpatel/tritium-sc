# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDRMonitorPlugin — comprehensive SDR monitoring for ISM, ADS-B, and spectrum.

Bridges rtl_433 (ISM band devices), dump1090 (ADS-B aircraft), and raw
spectrum data into the command center's EventBus and TargetTracker.

Capabilities:
- ISM band device detection and classification via rtl_433 MQTT
- ADS-B aircraft tracking via dump1090 or MQTT
- Spectrum sweep data for waterfall display
- RF baseline learning with anomaly detection (24h rolling window)
- Demo data generation with synthetic aircraft, ISM devices, and spectrum

MQTT topics:
    IN:  rtl_433/events                        — rtl_433 decoded devices
    IN:  tritium/{site}/sdr/{id}/spectrum       — spectrum sweep data
    IN:  tritium/{site}/sdr/{id}/devices        — rtl_433 decoded devices
    IN:  tritium/{site}/sdr/{id}/adsb           — ADS-B aircraft positions
    OUT: tritium/{site}/sdr/alerts              — RF anomaly alerts
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("sdr_monitor")

# Defaults
DEFAULT_MQTT_TOPIC = "rtl_433/events"
DEFAULT_DEVICE_TTL = 600.0          # seconds before a device is considered stale
DEFAULT_ADSB_TTL = 60.0             # seconds before an aircraft track is stale
MAX_DEVICE_HISTORY = 5000
MAX_SIGNAL_HISTORY = 2000
MAX_SPECTRUM_HISTORY = 100
MAX_ANOMALY_HISTORY = 500
DEFAULT_POLL_INTERVAL = 10.0        # cleanup loop interval
BASELINE_WINDOW_S = 86400.0         # 24-hour rolling window for RF baseline


class ISMDevice:
    """A detected ISM band device from rtl_433."""

    __slots__ = (
        "device_id",
        "model",
        "protocol",
        "device_type",
        "frequency_mhz",
        "rssi_db",
        "snr_db",
        "first_seen",
        "last_seen",
        "message_count",
        "metadata",
    )

    def __init__(
        self,
        device_id: str,
        model: str = "unknown",
        protocol: str = "",
        device_type: str = "ism_device",
        frequency_mhz: float = 0.0,
        rssi_db: float = 0.0,
        snr_db: float = 0.0,
    ) -> None:
        self.device_id = device_id
        self.model = model
        self.protocol = protocol
        self.device_type = device_type
        self.frequency_mhz = frequency_mhz
        self.rssi_db = rssi_db
        self.snr_db = snr_db
        now = time.time()
        self.first_seen = now
        self.last_seen = now
        self.message_count = 1
        self.metadata: dict[str, Any] = {}

    def update(
        self,
        rssi_db: float = 0.0,
        snr_db: float = 0.0,
        frequency_mhz: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> None:
        """Update device with a new observation."""
        self.last_seen = time.time()
        self.message_count += 1
        if rssi_db != 0.0:
            self.rssi_db = rssi_db
        if snr_db != 0.0:
            self.snr_db = snr_db
        if frequency_mhz != 0.0:
            self.frequency_mhz = frequency_mhz
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "model": self.model,
            "protocol": self.protocol,
            "device_type": self.device_type,
            "frequency_mhz": self.frequency_mhz,
            "rssi_db": self.rssi_db,
            "snr_db": self.snr_db,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
            "metadata": dict(self.metadata),
        }


class ADSBTrack:
    """An ADS-B aircraft track."""

    __slots__ = (
        "icao_hex",
        "callsign",
        "lat",
        "lng",
        "altitude_ft",
        "speed_kts",
        "heading",
        "vertical_rate",
        "squawk",
        "first_seen",
        "last_seen",
        "message_count",
        "on_ground",
    )

    def __init__(
        self,
        icao_hex: str,
        callsign: str = "",
        lat: float = 0.0,
        lng: float = 0.0,
        altitude_ft: int = 0,
        speed_kts: float = 0.0,
        heading: float = 0.0,
        vertical_rate: int = 0,
        squawk: str = "",
    ) -> None:
        self.icao_hex = icao_hex
        self.callsign = callsign
        self.lat = lat
        self.lng = lng
        self.altitude_ft = altitude_ft
        self.speed_kts = speed_kts
        self.heading = heading
        self.vertical_rate = vertical_rate
        self.squawk = squawk
        now = time.time()
        self.first_seen = now
        self.last_seen = now
        self.message_count = 1
        self.on_ground = False

    def update(self, msg: dict) -> None:
        """Update track from a dump1090-style message."""
        self.last_seen = time.time()
        self.message_count += 1
        flight = msg.get("flight", "").strip()
        if flight:
            self.callsign = flight
        lat = msg.get("lat", 0.0)
        lon = msg.get("lon", 0.0)
        if lat and lon:
            self.lat = lat
            self.lng = lon
        alt = msg.get("altitude", msg.get("alt_baro", 0))
        if alt:
            self.altitude_ft = int(alt)
        speed = msg.get("speed", msg.get("gs", 0.0))
        if speed:
            self.speed_kts = float(speed)
        track = msg.get("track", 0.0)
        if track:
            self.heading = float(track)
        vr = msg.get("vert_rate", msg.get("baro_rate", 0))
        if vr:
            self.vertical_rate = int(vr)
        squawk = msg.get("squawk", "")
        if squawk:
            self.squawk = squawk
        self.on_ground = bool(msg.get("ground", False))

    def to_dict(self) -> dict:
        return {
            "icao_hex": self.icao_hex,
            "callsign": self.callsign,
            "lat": self.lat,
            "lng": self.lng,
            "altitude_ft": self.altitude_ft,
            "speed_kts": self.speed_kts,
            "heading": self.heading,
            "vertical_rate": self.vertical_rate,
            "squawk": self.squawk,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
            "on_ground": self.on_ground,
        }


# -- Device type classification from rtl_433 model names --------------------

_DEVICE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "weather_station": ["weather", "acurite", "oregon", "lacrosse", "bresser", "fineoffset", "fine-offset", "ambient"],
    "tire_pressure": ["tpms", "tire", "tyre"],
    "doorbell": ["doorbell", "door-bell", "chime"],
    "car_key_fob": ["keyfob", "key-fob", "car-key", "remote"],
    "soil_moisture": ["soil", "moisture"],
    "smoke_detector": ["smoke", "fire"],
    "garage_door": ["garage"],
    "thermostat": ["thermostat", "heat", "hvac"],
    "power_meter": ["power", "energy", "meter", "current-cost"],
    "water_meter": ["water-meter"],
    "gas_meter": ["gas-meter"],
    "lightning": ["lightning"],
    "pool_thermometer": ["pool"],
}


def classify_device_type(model: str) -> str:
    """Classify an rtl_433 model string into a device type category."""
    model_lower = model.lower()
    for dtype, keywords in _DEVICE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in model_lower:
                return dtype
    return "ism_device"


def build_device_id(msg: dict) -> str:
    """Build a unique device ID from an rtl_433 JSON message.

    rtl_433 messages typically include 'model' and 'id' fields. Some also
    include 'channel' or 'subtype' for disambiguation.
    """
    model = msg.get("model", "unknown")
    dev_id = msg.get("id", "")
    channel = msg.get("channel", "")
    parts = ["sdr", model.replace(" ", "_")]
    if dev_id != "":
        parts.append(str(dev_id))
    if channel != "":
        parts.append(f"ch{channel}")
    return "_".join(parts).lower()


class SDRMonitorPlugin(PluginInterface):
    """Comprehensive SDR monitoring: ISM devices, ADS-B, spectrum, anomalies.

    Unifies rtl_433 ISM band monitoring, dump1090 ADS-B tracking,
    spectrum analysis, and RF anomaly detection into a single plugin.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._mqtt_bridge: Any = None
        self._logger: logging.Logger = log

        self._running = False
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0

        # Config
        self._mqtt_topic: str = DEFAULT_MQTT_TOPIC
        self._device_ttl: float = DEFAULT_DEVICE_TTL
        self._adsb_ttl: float = DEFAULT_ADSB_TTL
        self._poll_interval: float = DEFAULT_POLL_INTERVAL

        # ISM device state
        self._devices: dict[str, ISMDevice] = {}
        self._signal_history: list[dict] = []
        self._frequency_activity: dict[float, int] = {}

        # ADS-B state
        self._adsb_tracks: dict[str, ADSBTrack] = {}

        # Spectrum state
        self._spectrum_history: list[dict] = []

        # Anomaly detection
        self._anomalies: list[dict] = []
        self._rf_baseline: dict[float, deque] = defaultdict(
            lambda: deque(maxlen=1440)
        )  # freq -> rolling power samples (1 per minute for 24h)

        # Demo generator
        self._demo: Any = None

        # Stats
        self._stats = {
            "messages_received": 0,
            "devices_detected": 0,
            "devices_active": 0,
            "targets_created": 0,
            "adsb_messages": 0,
            "adsb_tracks_active": 0,
            "spectrum_captures": 0,
            "anomalies_detected": 0,
            "messages_by_type": {},
        }

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.sdr_monitor"

    @property
    def name(self) -> str:
        return "SDR Monitor — rtl_433 ISM Band Tracker"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        settings = ctx.settings or {}
        if "mqtt_topic" in settings:
            self._mqtt_topic = str(settings["mqtt_topic"])
        if "device_ttl" in settings:
            self._device_ttl = float(settings["device_ttl"])
        if "adsb_ttl" in settings:
            self._adsb_ttl = float(settings["adsb_ttl"])
        if "poll_interval" in settings:
            self._poll_interval = float(settings["poll_interval"])

        # Subscribe to MQTT if bridge is available
        self._subscribe_mqtt(ctx)

        # Register API routes
        self._register_routes()

        self._logger.info(
            "SDR Monitor configured (topic=%s, ttl=%.0fs)",
            self._mqtt_topic,
            self._device_ttl,
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_time = time.time()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="sdr-monitor-cleanup",
        )
        self._cleanup_thread.start()
        self._logger.info("SDR Monitor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        # Stop demo if running
        if self._demo is not None:
            self._demo.stop()
            self._demo = None

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=3.0)

        self._logger.info("SDR Monitor stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- MQTT subscription -------------------------------------------------

    def _subscribe_mqtt(self, ctx: PluginContext) -> None:
        """Subscribe to MQTT topics via the system MQTT bridge."""
        mqtt_bridge = getattr(ctx, "mqtt_bridge", None)
        if mqtt_bridge is None and hasattr(ctx, "app") and ctx.app:
            mqtt_bridge = getattr(ctx.app.state, "mqtt_bridge", None)

        if mqtt_bridge is None:
            self._logger.info(
                "No MQTT bridge available — data accepted via EventBus or API"
            )
            return

        self._mqtt_bridge = mqtt_bridge
        topics = [
            (self._mqtt_topic, self._on_rtl433_mqtt),
            ("tritium/+/sdr/+/devices", self._on_rtl433_mqtt),
            ("tritium/+/sdr/+/ism", self._on_rtl433_mqtt),
            ("tritium/+/sdr/+/adsb", self._on_adsb_mqtt),
            ("tritium/+/sdr/+/spectrum", self._on_spectrum_mqtt),
        ]
        for topic, handler in topics:
            try:
                mqtt_bridge.subscribe(topic, handler)
                self._logger.info("Subscribed to MQTT topic: %s", topic)
            except Exception as exc:
                self._logger.warning(
                    "Could not subscribe to %s: %s", topic, exc
                )

    def _on_rtl433_mqtt(self, topic: str, payload: bytes | str) -> None:
        """Handle incoming rtl_433 MQTT message."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self.ingest_message(data)
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.debug("Invalid rtl_433 JSON: %s", exc)

    def _on_adsb_mqtt(self, topic: str, payload: bytes | str) -> None:
        """Handle incoming ADS-B MQTT message."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self.ingest_adsb(data)
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.debug("Invalid ADS-B JSON: %s", exc)

    def _on_spectrum_mqtt(self, topic: str, payload: bytes | str) -> None:
        """Handle incoming spectrum MQTT message."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self.record_spectrum(data)
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.debug("Invalid spectrum JSON: %s", exc)

    # -- ISM device ingestion ----------------------------------------------

    def ingest_message(self, msg: dict) -> dict:
        """Parse and ingest an rtl_433 JSON message.

        Returns the processed device dict.
        """
        device_id = build_device_id(msg)
        model = msg.get("model", "unknown")
        protocol = msg.get("protocol", model)
        frequency_mhz = float(msg.get("freq", msg.get("frequency", 0.0)))
        rssi_db = float(msg.get("rssi", msg.get("rssi_db", 0.0)))
        snr_db = float(msg.get("snr", msg.get("snr_db", 0.0)))
        device_type = classify_device_type(model)

        # Extract metadata (everything that isn't a core field)
        core_keys = {"model", "id", "channel", "protocol", "freq", "frequency",
                      "rssi", "rssi_db", "snr", "snr_db", "time", "subtype"}
        metadata = {k: v for k, v in msg.items() if k not in core_keys}

        with self._lock:
            self._stats["messages_received"] += 1

            # Track frequency activity
            if frequency_mhz > 0:
                rounded = round(frequency_mhz, 2)
                self._frequency_activity[rounded] = (
                    self._frequency_activity.get(rounded, 0) + 1
                )

            # Track message count by device type
            type_counts = self._stats["messages_by_type"]
            type_counts[device_type] = type_counts.get(device_type, 0) + 1

            # Update or create device
            if device_id in self._devices:
                dev = self._devices[device_id]
                dev.update(
                    rssi_db=rssi_db,
                    snr_db=snr_db,
                    frequency_mhz=frequency_mhz,
                    metadata=metadata,
                )
            else:
                dev = ISMDevice(
                    device_id=device_id,
                    model=model,
                    protocol=protocol,
                    device_type=device_type,
                    frequency_mhz=frequency_mhz,
                    rssi_db=rssi_db,
                    snr_db=snr_db,
                )
                dev.metadata = metadata
                self._devices[device_id] = dev
                self._stats["devices_detected"] += 1

            # Record in signal history
            signal_record = {
                "device_id": device_id,
                "model": model,
                "device_type": device_type,
                "frequency_mhz": frequency_mhz,
                "rssi_db": rssi_db,
                "snr_db": snr_db,
                "timestamp": time.time(),
                "metadata": metadata,
            }
            self._signal_history.append(signal_record)
            if len(self._signal_history) > MAX_SIGNAL_HISTORY:
                self._signal_history = self._signal_history[-MAX_SIGNAL_HISTORY:]

            device_dict = dev.to_dict()

        # Update RF baseline for anomaly detection
        if frequency_mhz > 0:
            self._update_baseline(frequency_mhz, rssi_db)

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish("sdr_monitor:device", data=device_dict)

        # Create/update TrackedTarget for ISM device
        self._update_ism_target(dev)

        return device_dict

    # -- ADS-B ingestion ---------------------------------------------------

    def ingest_adsb(self, msg: dict) -> Optional[dict]:
        """Process an ADS-B message (dump1090 JSON format).

        Creates a TrackedTarget with source='adsb' and target_id='adsb_{icao}'.
        Returns the track dict, or None if invalid.
        """
        icao = msg.get("hex", "").strip()
        if not icao:
            return None

        with self._lock:
            self._stats["adsb_messages"] += 1

            if icao in self._adsb_tracks:
                track = self._adsb_tracks[icao]
                track.update(msg)
            else:
                flight = msg.get("flight", "").strip()
                lat = msg.get("lat", 0.0)
                lon = msg.get("lon", 0.0)
                alt = int(msg.get("altitude", msg.get("alt_baro", 0)))
                speed = float(msg.get("speed", msg.get("gs", 0.0)))
                heading = float(msg.get("track", 0.0))
                squawk = msg.get("squawk", "")

                track = ADSBTrack(
                    icao_hex=icao,
                    callsign=flight,
                    lat=lat,
                    lng=lon,
                    altitude_ft=alt,
                    speed_kts=speed,
                    heading=heading,
                    squawk=squawk,
                )
                self._adsb_tracks[icao] = track

            track_dict = track.to_dict()

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish("sdr_monitor:adsb", data=track_dict)

        # Create/update TrackedTarget for aircraft
        lat = track.lat
        lng = track.lng
        if lat and lng:
            self._update_adsb_target(track)

        return track_dict

    # -- Spectrum recording ------------------------------------------------

    def record_spectrum(self, sweep: dict) -> None:
        """Record a spectrum sweep for waterfall display and anomaly detection."""
        with self._lock:
            self._stats["spectrum_captures"] += 1
            self._spectrum_history.append(sweep)
            if len(self._spectrum_history) > MAX_SPECTRUM_HISTORY:
                self._spectrum_history = self._spectrum_history[-MAX_SPECTRUM_HISTORY:]

        # Check for anomalies in the spectrum
        self._check_spectrum_anomalies(sweep)

        if self._event_bus:
            self._event_bus.publish("sdr_monitor:spectrum", data=sweep)

    # -- Anomaly detection -------------------------------------------------

    def record_anomaly(self, anomaly: dict) -> None:
        """Record an RF anomaly."""
        with self._lock:
            self._stats["anomalies_detected"] += 1
            self._anomalies.append(anomaly)
            if len(self._anomalies) > MAX_ANOMALY_HISTORY:
                self._anomalies = self._anomalies[-MAX_ANOMALY_HISTORY:]

        if self._event_bus:
            self._event_bus.publish("sdr_monitor:anomaly", data=anomaly)

        self._logger.warning(
            "RF anomaly: %s at %.2f MHz (%.1f dBm, baseline %.1f dBm)",
            anomaly.get("anomaly_type", "unknown"),
            anomaly.get("frequency_mhz", 0),
            anomaly.get("power_dbm", 0),
            anomaly.get("baseline_dbm", 0),
        )

    def _update_baseline(self, freq_mhz: float, power_dbm: float) -> None:
        """Update the rolling RF baseline for a frequency."""
        rounded = round(freq_mhz, 1)
        self._rf_baseline[rounded].append((time.time(), power_dbm))

    def _get_baseline_power(self, freq_mhz: float) -> Optional[float]:
        """Get the average baseline power for a frequency."""
        rounded = round(freq_mhz, 1)
        samples = self._rf_baseline.get(rounded)
        if not samples or len(samples) < 5:
            return None
        now = time.time()
        recent = [p for t, p in samples if now - t < BASELINE_WINDOW_S]
        if not recent:
            return None
        return sum(recent) / len(recent)

    def _check_spectrum_anomalies(self, sweep: dict) -> None:
        """Check spectrum sweep for anomalies against the baseline."""
        power_dbm = sweep.get("power_dbm", [])
        if not power_dbm:
            return

        freq_start = sweep.get("freq_start_hz", 0)
        freq_end = sweep.get("freq_end_hz", 0)
        bin_count = sweep.get("bin_count", len(power_dbm))

        if freq_start <= 0 or freq_end <= 0 or bin_count <= 0:
            return

        # Check each bin against baseline
        freq_step = (freq_end - freq_start) / bin_count
        threshold_db = 15.0  # 15 dB above baseline = anomaly

        for i, power in enumerate(power_dbm):
            freq_hz = freq_start + i * freq_step
            freq_mhz = freq_hz / 1e6
            baseline = self._get_baseline_power(freq_mhz)

            if baseline is not None and power - baseline > threshold_db:
                self.record_anomaly({
                    "frequency_mhz": round(freq_mhz, 3),
                    "power_dbm": round(power, 1),
                    "baseline_dbm": round(baseline, 1),
                    "anomaly_type": "power_change",
                    "severity": "warning" if power - baseline < 25 else "critical",
                    "timestamp": time.time(),
                    "description": f"Power {power - baseline:.1f} dB above baseline at {freq_mhz:.3f} MHz",
                    "source_id": sweep.get("source_id", ""),
                })

    # -- Public query API --------------------------------------------------

    def get_devices(self) -> list[dict]:
        """Return all detected ISM devices."""
        with self._lock:
            return [d.to_dict() for d in self._devices.values()]

    def get_adsb_tracks(self) -> list[dict]:
        """Return all active ADS-B aircraft tracks."""
        with self._lock:
            now = time.time()
            active = [
                t.to_dict()
                for t in self._adsb_tracks.values()
                if now - t.last_seen < self._adsb_ttl
            ]
            return active

    def get_spectrum(self) -> dict:
        """Return frequency activity summary (ISM band)."""
        with self._lock:
            return {
                "frequency_activity": dict(self._frequency_activity),
                "total_frequencies": len(self._frequency_activity),
            }

    def get_spectrum_history(self, limit: int = 50) -> list[dict]:
        """Return recent spectrum sweep captures for waterfall display."""
        with self._lock:
            return list(self._spectrum_history[-limit:])

    def get_anomalies(self, limit: int = 100) -> list[dict]:
        """Return recent RF anomalies."""
        with self._lock:
            return list(self._anomalies[-limit:])

    def get_stats(self) -> dict:
        """Return detection statistics."""
        with self._lock:
            return {
                **self._stats,
                "devices_active": len(self._devices),
                "adsb_tracks_active": len(self._adsb_tracks),
                "signal_history_size": len(self._signal_history),
                "spectrum_history_size": len(self._spectrum_history),
                "anomalies_active": len(self._anomalies),
                "running": self._running,
                "mqtt_topic": self._mqtt_topic,
                "demo_mode": self._demo is not None and self._demo.is_running,
                "uptime_s": time.time() - self._start_time if self._running else 0,
            }

    def get_signals(self, limit: int = 50) -> list[dict]:
        """Return recent signal history."""
        with self._lock:
            return list(self._signal_history[-limit:])

    def get_status(self) -> dict:
        """Return comprehensive SDR system status."""
        with self._lock:
            return {
                "connected_devices": [],  # No hardware in SC — data comes via MQTT
                "active_receivers": 1 if self._running else 0,
                "ism_devices_tracked": len(self._devices),
                "adsb_aircraft_tracked": len(self._adsb_tracks),
                "anomalies_active": len(self._anomalies),
                "uptime_s": time.time() - self._start_time if self._running else 0,
                "messages_total": self._stats["messages_received"] + self._stats["adsb_messages"],
                "demo_mode": self._demo is not None and self._demo.is_running,
            }

    # -- Demo mode ---------------------------------------------------------

    def start_demo(self) -> dict:
        """Start the demo data generator."""
        if self._demo is not None and self._demo.is_running:
            return {"status": "already_running"}

        from .demo import SDRDemoGenerator
        self._demo = SDRDemoGenerator(self)
        self._demo.start()
        return {"status": "started"}

    def stop_demo(self) -> dict:
        """Stop the demo data generator."""
        if self._demo is None or not self._demo.is_running:
            return {"status": "not_running"}

        self._demo.stop()
        self._demo = None
        return {"status": "stopped"}

    # -- SDR configuration -------------------------------------------------

    def configure_sdr(self, config: dict) -> dict:
        """Apply SDR configuration changes.

        In practice, this publishes a config command to the edge SDR
        device via MQTT. The SC doesn't run SDR hardware directly.
        """
        if self._mqtt_bridge and self._event_bus:
            self._event_bus.publish("sdr_monitor:configure", data=config)

        return {
            "status": "accepted",
            "config": config,
            "note": "Configuration sent to edge SDR devices via EventBus",
        }

    # -- Target tracking ---------------------------------------------------

    def _update_ism_target(self, dev: ISMDevice) -> None:
        """Create or update a TrackedTarget for an ISM device."""
        if self._tracker is None:
            return

        try:
            from engine.tactical.target_tracker import TrackedTarget

            with self._tracker._lock:
                if dev.device_id in self._tracker._targets:
                    t = self._tracker._targets[dev.device_id]
                    t.last_seen = time.monotonic()
                    t.status = f"{dev.device_type}:{dev.model}"
                else:
                    self._tracker._targets[dev.device_id] = TrackedTarget(
                        target_id=dev.device_id,
                        name=f"ISM: {dev.model}",
                        alliance="unknown",
                        asset_type=dev.device_type,
                        position=(0.0, 0.0),
                        last_seen=time.monotonic(),
                        source="sdr_monitor",
                        position_source="rf_proximity",
                        position_confidence=0.1,
                        status=f"{dev.device_type}:{dev.model}",
                    )
                    with self._lock:
                        self._stats["targets_created"] += 1
        except Exception as exc:
            self._logger.error("Failed to create ISM target: %s", exc)

    def _update_adsb_target(self, track: ADSBTrack) -> None:
        """Create or update a TrackedTarget for an ADS-B aircraft."""
        if self._tracker is None:
            return

        try:
            from engine.tactical.target_tracker import TrackedTarget

            target_id = f"adsb_{track.icao_hex}"
            label = track.callsign if track.callsign else track.icao_hex

            with self._tracker._lock:
                if target_id in self._tracker._targets:
                    t = self._tracker._targets[target_id]
                    t.last_seen = time.monotonic()
                    t.position = (track.lat, track.lng)
                    t.heading = track.heading
                    t.speed = track.speed_kts
                    t.status = f"adsb:{label}:FL{track.altitude_ft // 100}"
                else:
                    self._tracker._targets[target_id] = TrackedTarget(
                        target_id=target_id,
                        name=f"Aircraft: {label}",
                        alliance="unknown",
                        asset_type="aircraft",
                        position=(track.lat, track.lng),
                        heading=track.heading,
                        speed=track.speed_kts,
                        last_seen=time.monotonic(),
                        source="sdr_monitor",
                        position_source="adsb",
                        position_confidence=0.95,
                        status=f"adsb:{label}:FL{track.altitude_ft // 100}",
                    )
                    with self._lock:
                        self._stats["targets_created"] += 1
        except Exception as exc:
            self._logger.error("Failed to update ADS-B target: %s", exc)

    # -- Cleanup loop (remove stale devices/tracks) -------------------------

    def _cleanup_loop(self) -> None:
        """Background loop: remove stale devices and ADS-B tracks."""
        while self._running:
            try:
                now = time.time()

                # Expire ISM devices
                expired_ism = []
                with self._lock:
                    for did, dev in self._devices.items():
                        if (now - dev.last_seen) > self._device_ttl:
                            expired_ism.append(did)
                    for did in expired_ism:
                        del self._devices[did]

                # Expire ADS-B tracks
                expired_adsb = []
                with self._lock:
                    for icao, track in self._adsb_tracks.items():
                        if (now - track.last_seen) > self._adsb_ttl:
                            expired_adsb.append(icao)
                    for icao in expired_adsb:
                        del self._adsb_tracks[icao]

                # Remove expired targets from tracker
                all_expired = expired_ism + [f"adsb_{icao}" for icao in expired_adsb]
                if self._tracker and all_expired:
                    try:
                        with self._tracker._lock:
                            for did in all_expired:
                                self._tracker._targets.pop(did, None)
                    except Exception:
                        pass

                # Prune old baseline samples
                cutoff = now - BASELINE_WINDOW_S
                for freq in list(self._rf_baseline.keys()):
                    samples = self._rf_baseline[freq]
                    while samples and samples[0][0] < cutoff:
                        samples.popleft()
                    if not samples:
                        del self._rf_baseline[freq]

            except Exception as exc:
                self._logger.error("SDR Monitor cleanup error: %s", exc)

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + self._poll_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- Routes ------------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router

        router = create_router(self)
        self._app.include_router(router)

    # -- EventBus handler (alternative to MQTT) ----------------------------

    def handle_event(self, event: dict) -> None:
        """Process EventBus events for SDR data."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "rtl_433:message":
            self.ingest_message(data)
        elif event_type in ("adsb:message", "dump1090:message"):
            self.ingest_adsb(data)
        elif event_type == "sdr:spectrum":
            self.record_spectrum(data)
