# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo data generator for the SDR Monitor plugin.

Generates synthetic:
- ADS-B aircraft tracks (commercial flights, GA aircraft, helicopters)
- ISM device detections (weather stations, TPMS, doorbells, soil sensors)
- Spectrum sweep data with realistic noise floor and occasional anomalies
- RF anomalies (new transmitters, power spikes)

All data is published through the plugin's ingest methods so it flows
through the same pipeline as real SDR data.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .plugin import SDRMonitorPlugin

log = logging.getLogger("sdr_monitor.demo")

# -- ADS-B flight patterns --------------------------------------------------

# Approximate center for demo (Austin, TX area — matches Tritium defaults)
DEMO_CENTER_LAT = 30.27
DEMO_CENTER_LNG = -97.74

# Pre-defined flight tracks: (callsign, icao_hex, start_lat, start_lng, heading, speed_kts, altitude_ft)
DEMO_FLIGHTS = [
    ("UAL2145", "A1B2C3", 30.50, -97.90, 135, 250, 12000),
    ("SWA1872", "D4E5F6", 30.10, -97.50, 310, 280, 18000),
    ("AAL456", "789ABC", 30.35, -98.10, 90, 320, 35000),
    ("N172SP", "ABCDEF", 30.30, -97.70, 180, 95, 3500),
    ("LIF3", "112233", 30.22, -97.68, 45, 60, 1500),
]

# -- ISM device templates ---------------------------------------------------

ISM_DEVICE_TEMPLATES = [
    {
        "model": "Acurite-Tower",
        "protocol": "Acurite Tower Sensor",
        "id": 12345,
        "freq": 433.92,
        "fields": {
            "temperature_C": (15.0, 35.0),
            "humidity": (30, 90),
            "battery_ok": 1,
        },
    },
    {
        "model": "Oregon-THR228N",
        "protocol": "Oregon Scientific v2.1",
        "id": 67,
        "channel": 2,
        "freq": 433.92,
        "fields": {
            "temperature_C": (18.0, 28.0),
            "battery_ok": 1,
        },
    },
    {
        "model": "Schrader-TPMS",
        "protocol": "Schrader TPMS EG53MA4",
        "id": 0xABCD1234,
        "freq": 315.0,
        "fields": {
            "pressure_kPa": (200.0, 260.0),
            "temperature_C": (20.0, 45.0),
        },
    },
    {
        "model": "LaCrosse-TX141Bv3",
        "protocol": "LaCrosse TX141-Bv3",
        "id": 88,
        "freq": 433.92,
        "fields": {
            "temperature_C": (10.0, 30.0),
            "humidity": (40, 85),
            "battery_ok": 1,
        },
    },
    {
        "model": "Generic-Doorbell",
        "protocol": "Generic Remote",
        "id": 55555,
        "freq": 433.92,
        "fields": {
            "cmd": "ring",
        },
    },
    {
        "model": "Fine-Offset-WH2",
        "protocol": "Fine Offset WH2",
        "id": 200,
        "channel": 1,
        "freq": 433.92,
        "fields": {
            "temperature_C": (12.0, 32.0),
            "humidity": (35, 95),
        },
    },
    {
        "model": "Bresser-5in1",
        "protocol": "Bresser 5-in-1",
        "id": 301,
        "freq": 868.3,
        "fields": {
            "temperature_C": (5.0, 38.0),
            "humidity": (20, 99),
            "wind_avg_km_h": (0.0, 40.0),
            "wind_dir_deg": (0, 360),
            "rain_mm": (0.0, 50.0),
        },
    },
    {
        "model": "Soil-Moisture-Sensor",
        "protocol": "Generic Soil Moisture",
        "id": 420,
        "freq": 433.92,
        "fields": {
            "moisture": (10, 90),
            "temperature_C": (8.0, 35.0),
            "battery_ok": 1,
        },
    },
]


class SDRDemoGenerator:
    """Generates synthetic SDR data for demo mode.

    Produces realistic-looking:
    - ADS-B aircraft tracks with smooth movement
    - ISM band device transmissions at realistic intervals
    - Spectrum sweep data with noise floor and signal peaks
    - Occasional RF anomalies
    """

    def __init__(self, plugin: SDRMonitorPlugin) -> None:
        self._plugin = plugin
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._adsb_thread: Optional[threading.Thread] = None

        # ADS-B state: track positions for each flight
        self._flight_state: dict[str, dict[str, Any]] = {}
        for flight in DEMO_FLIGHTS:
            callsign, icao, lat, lng, hdg, spd, alt = flight
            self._flight_state[icao] = {
                "callsign": callsign,
                "lat": lat,
                "lng": lng,
                "heading": hdg,
                "speed_kts": spd,
                "altitude_ft": alt,
                "vertical_rate": 0,
            }

        # ISM device state: when each device last transmitted
        self._ism_last_tx: dict[str, float] = {}

        # Anomaly generation state
        self._anomaly_cooldown = 0.0

    def start(self) -> None:
        """Start generating demo data."""
        if self._running:
            return
        self._running = True

        self._thread = threading.Thread(
            target=self._ism_loop,
            daemon=True,
            name="sdr-demo-ism",
        )
        self._thread.start()

        self._adsb_thread = threading.Thread(
            target=self._adsb_loop,
            daemon=True,
            name="sdr-demo-adsb",
        )
        self._adsb_thread.start()

        log.info("SDR demo generator started")

    def stop(self) -> None:
        """Stop generating demo data."""
        if not self._running:
            return
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._adsb_thread and self._adsb_thread.is_alive():
            self._adsb_thread.join(timeout=3.0)

        log.info("SDR demo generator stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # -- ISM device loop ---------------------------------------------------

    def _ism_loop(self) -> None:
        """Generate ISM device transmissions at realistic intervals."""
        while self._running:
            try:
                now = time.time()
                for template in ISM_DEVICE_TEMPLATES:
                    dev_key = f"{template['model']}_{template['id']}"
                    last_tx = self._ism_last_tx.get(dev_key, 0.0)

                    # Weather stations transmit every 30-60s,
                    # TPMS every 15-30s, doorbells sporadically
                    if "doorbell" in template["model"].lower():
                        interval = random.uniform(60, 300)
                    elif "tpms" in template["model"].lower():
                        interval = random.uniform(15, 30)
                    else:
                        interval = random.uniform(30, 60)

                    if now - last_tx < interval:
                        continue

                    self._ism_last_tx[dev_key] = now

                    # Build the rtl_433-style message
                    msg = {
                        "model": template["model"],
                        "id": template["id"],
                        "freq": template["freq"],
                        "rssi": random.uniform(-65, -35),
                        "snr": random.uniform(8, 25),
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    if "channel" in template:
                        msg["channel"] = template["channel"]
                    if "protocol" in template:
                        msg["protocol"] = template["protocol"]

                    # Generate field values
                    for field_name, spec in template["fields"].items():
                        if isinstance(spec, tuple):
                            if isinstance(spec[0], float):
                                msg[field_name] = round(
                                    random.uniform(spec[0], spec[1]), 1
                                )
                            else:
                                msg[field_name] = random.randint(spec[0], spec[1])
                        else:
                            msg[field_name] = spec

                    # Ingest through the plugin pipeline
                    self._plugin.ingest_message(msg)

                # Maybe generate a spectrum sweep
                if random.random() < 0.1:
                    self._generate_spectrum()

                # Maybe generate an anomaly
                if now > self._anomaly_cooldown and random.random() < 0.05:
                    self._generate_anomaly()
                    self._anomaly_cooldown = now + 30.0

            except Exception as exc:
                log.error("SDR demo ISM error: %s", exc)

            # Sleep 2 seconds between cycles
            deadline = time.monotonic() + 2.0
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- ADS-B loop --------------------------------------------------------

    def _adsb_loop(self) -> None:
        """Generate ADS-B aircraft position updates."""
        while self._running:
            try:
                for icao, state in self._flight_state.items():
                    # Move aircraft along heading
                    speed_deg_per_sec = (state["speed_kts"] * 1.852) / (
                        111320.0
                    )  # rough conversion
                    dt = 1.0  # 1 second update rate

                    hdg_rad = math.radians(state["heading"])
                    state["lat"] += math.cos(hdg_rad) * speed_deg_per_sec * dt
                    state["lng"] += (
                        math.sin(hdg_rad) * speed_deg_per_sec * dt
                    ) / math.cos(math.radians(state["lat"]))

                    # Altitude changes
                    state["altitude_ft"] += state["vertical_rate"] * dt / 60.0
                    state["altitude_ft"] = max(0, state["altitude_ft"])

                    # Occasionally change heading slightly (realistic turns)
                    if random.random() < 0.05:
                        state["heading"] = (
                            state["heading"] + random.uniform(-10, 10)
                        ) % 360
                    if random.random() < 0.02:
                        state["vertical_rate"] = random.choice(
                            [0, 0, 0, 500, -500, 1000, -1000]
                        )

                    # Wrap around demo area
                    dist = math.sqrt(
                        (state["lat"] - DEMO_CENTER_LAT) ** 2
                        + (state["lng"] - DEMO_CENTER_LNG) ** 2
                    )
                    if dist > 1.0:
                        # Reset to near center
                        state["lat"] = DEMO_CENTER_LAT + random.uniform(-0.3, 0.3)
                        state["lng"] = DEMO_CENTER_LNG + random.uniform(-0.3, 0.3)
                        state["heading"] = random.uniform(0, 360)

                    # Build ADS-B message (dump1090 format)
                    adsb_msg = {
                        "hex": icao,
                        "flight": state["callsign"],
                        "lat": round(state["lat"], 6),
                        "lon": round(state["lng"], 6),
                        "altitude": int(state["altitude_ft"]),
                        "speed": state["speed_kts"],
                        "track": state["heading"],
                        "squawk": "1200",
                    }

                    self._plugin.ingest_adsb(adsb_msg)

            except Exception as exc:
                log.error("SDR demo ADS-B error: %s", exc)

            # ADS-B updates every 1 second
            deadline = time.monotonic() + 1.0
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- Spectrum generation -----------------------------------------------

    def _generate_spectrum(self) -> None:
        """Generate a synthetic spectrum sweep."""
        center_freq_mhz = random.choice([433.92, 315.0, 868.3, 915.0])
        bandwidth_mhz = 2.0
        num_bins = 512

        freq_start_hz = (center_freq_mhz - bandwidth_mhz / 2) * 1e6
        freq_end_hz = (center_freq_mhz + bandwidth_mhz / 2) * 1e6

        # Noise floor around -90 dBm with gaussian variation
        noise_floor = -90.0
        power_dbm = [
            round(random.gauss(noise_floor, 3.0), 1) for _ in range(num_bins)
        ]

        # Add a few signal peaks
        for _ in range(random.randint(1, 4)):
            peak_bin = random.randint(50, num_bins - 50)
            peak_power = random.uniform(-60, -30)
            spread = random.randint(3, 15)
            for j in range(max(0, peak_bin - spread), min(num_bins, peak_bin + spread)):
                dist = abs(j - peak_bin)
                power_dbm[j] = max(
                    power_dbm[j], peak_power - dist * 2.0
                )

        sweep = {
            "freq_start_hz": freq_start_hz,
            "freq_end_hz": freq_end_hz,
            "center_freq_hz": center_freq_mhz * 1e6,
            "bandwidth_hz": bandwidth_mhz * 1e6,
            "bin_count": num_bins,
            "power_dbm": power_dbm,
            "timestamp": time.time(),
            "source_id": "demo",
        }

        self._plugin.record_spectrum(sweep)

    # -- Anomaly generation ------------------------------------------------

    def _generate_anomaly(self) -> None:
        """Generate a synthetic RF anomaly."""
        anomaly_types = [
            ("new_transmitter", "info", "New transmitter detected"),
            ("power_change", "warning", "Significant power increase"),
            ("interference", "warning", "Wideband interference detected"),
            ("jamming", "critical", "Possible jamming signal detected"),
        ]

        atype, severity, desc = random.choice(anomaly_types)
        freq = random.choice([433.92, 315.0, 868.3, 915.0, 1090.0])

        anomaly = {
            "frequency_mhz": freq,
            "power_dbm": random.uniform(-40, -10),
            "baseline_dbm": random.uniform(-85, -70),
            "anomaly_type": atype,
            "severity": severity,
            "timestamp": time.time(),
            "duration_s": random.uniform(0.5, 30.0),
            "description": f"{desc} at {freq} MHz",
            "source_id": "demo",
        }

        self._plugin.record_anomaly(anomaly)
