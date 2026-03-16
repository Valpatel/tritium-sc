# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ISM band device decoder — rtl_433 integration for ISM band monitoring.

Processes decoded ISM band device transmissions from rtl_433 and
maintains a registry of detected devices. Handles device type
classification, deduplication, frequency activity tracking, and
TrackedTarget creation.

rtl_433 decodes 200+ device protocols across ISM bands:
- 315 MHz (North America): TPMS, garage doors, car key fobs
- 433.92 MHz (worldwide): weather stations, doorbells, soil sensors
- 868 MHz (Europe): weather stations, smart home
- 915 MHz (North America): smart meters, LoRa

Data sources:
    - MQTT topic: tritium/{site}/sdr/{id}/ism
    - MQTT topic: rtl_433/events (rtl_433 default output)
    - REST API: POST /api/sdr/ingest
    - EventBus: event type 'rtl_433:message'

Message format (rtl_433 JSON):
    {
        "model": "Acurite-Tower",
        "id": 12345,
        "channel": "A",
        "temperature_C": 22.5,
        "humidity": 65,
        "freq": 433.92,
        "rssi": -42.0,
        "snr": 15.0
    }
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("sdr_monitor.ism_decoder")

# Default ISM device time-to-live (seconds)
DEFAULT_DEVICE_TTL_S = 600.0

# Maximum histories
MAX_SIGNAL_HISTORY = 2000
MAX_DEVICE_REGISTRY = 5000

# Core fields in rtl_433 messages that are NOT sensor metadata
CORE_FIELDS = {
    "model", "id", "channel", "protocol", "freq", "frequency",
    "rssi", "rssi_db", "snr", "snr_db", "time", "subtype",
}


# -- Device type classification from rtl_433 model names --------------------

_DEVICE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "weather_station": [
        "weather", "acurite", "oregon", "lacrosse", "bresser",
        "fineoffset", "fine-offset", "ambient",
    ],
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
    """Classify an rtl_433 model string into a device type category.

    Args:
        model: The 'model' field from an rtl_433 JSON message.

    Returns:
        Device type string (e.g., 'weather_station', 'tire_pressure')
        or 'ism_device' if no match is found.
    """
    model_lower = model.lower()
    for dtype, keywords in _DEVICE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in model_lower:
                return dtype
    return "ism_device"


def build_device_id(msg: dict) -> str:
    """Build a unique device ID from an rtl_433 JSON message.

    rtl_433 messages typically include 'model' and 'id' fields. Some
    also include 'channel' or 'subtype' for disambiguation.

    Args:
        msg: rtl_433 JSON message dict.

    Returns:
        Unique device ID string like 'ism_acurite-tower_12345_chA'.
    """
    model = msg.get("model", "unknown")
    dev_id = msg.get("id", "")
    channel = msg.get("channel", "")
    parts = ["ism", model.replace(" ", "_")]
    if dev_id != "":
        parts.append(str(dev_id))
    if channel != "":
        parts.append(f"ch{channel}")
    return "_".join(parts).lower()


def extract_metadata(msg: dict) -> dict:
    """Extract sensor metadata from an rtl_433 message.

    Returns all fields that are NOT core protocol fields (model, id,
    freq, rssi, etc.). These are the actual sensor readings
    (temperature, humidity, pressure, battery_ok, etc.).
    """
    return {k: v for k, v in msg.items() if k not in CORE_FIELDS}


class ISMDevice:
    """A detected ISM band device from rtl_433.

    Tracks the device identity, signal characteristics, observation
    counts, and decoded sensor metadata.
    """

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


class ISMDecoder:
    """ISM band device decoder and registry.

    Processes rtl_433 JSON messages, classifies device types,
    deduplicates observations, and maintains a registry of detected
    devices with their latest sensor readings.

    Usage::

        decoder = ISMDecoder()
        device_dict = decoder.ingest(rtl_433_message)
        devices = decoder.get_devices()
        decoder.expire_stale()
    """

    def __init__(self, ttl_s: float = DEFAULT_DEVICE_TTL_S) -> None:
        self._devices: dict[str, ISMDevice] = {}
        self._signal_history: list[dict] = []
        self._frequency_activity: dict[float, int] = {}
        self._ttl_s = ttl_s
        self._messages_received = 0
        self._devices_detected = 0
        self._messages_by_type: dict[str, int] = {}

    def ingest(self, msg: dict) -> dict:
        """Parse and ingest an rtl_433 JSON message.

        Creates or updates the device in the registry and records
        signal history.

        Args:
            msg: rtl_433 JSON message dict.

        Returns:
            The processed device dict.
        """
        device_id = build_device_id(msg)
        model = msg.get("model", "unknown")
        protocol = msg.get("protocol", model)
        frequency_mhz = float(msg.get("freq", msg.get("frequency", 0.0)))
        rssi_db = float(msg.get("rssi", msg.get("rssi_db", 0.0)))
        snr_db = float(msg.get("snr", msg.get("snr_db", 0.0)))
        device_type = classify_device_type(model)
        metadata = extract_metadata(msg)

        self._messages_received += 1

        # Track frequency activity
        if frequency_mhz > 0:
            rounded = round(frequency_mhz, 2)
            self._frequency_activity[rounded] = (
                self._frequency_activity.get(rounded, 0) + 1
            )

        # Track message count by device type
        self._messages_by_type[device_type] = (
            self._messages_by_type.get(device_type, 0) + 1
        )

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
            self._devices_detected += 1

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

        return dev.to_dict()

    def get_devices(self) -> list[dict]:
        """Return all detected ISM devices."""
        return [d.to_dict() for d in self._devices.values()]

    def get_device(self, device_id: str) -> Optional[dict]:
        """Get a specific device by ID, or None if not found."""
        dev = self._devices.get(device_id)
        return dev.to_dict() if dev else None

    def get_signals(self, limit: int = 50) -> list[dict]:
        """Return recent signal history."""
        return list(self._signal_history[-limit:])

    def get_frequency_activity(self) -> dict:
        """Return frequency activity summary."""
        return {
            "frequency_activity": dict(self._frequency_activity),
            "total_frequencies": len(self._frequency_activity),
        }

    def expire_stale(self) -> list[str]:
        """Remove devices older than TTL. Returns list of expired device IDs."""
        now = time.time()
        expired = [
            did
            for did, dev in self._devices.items()
            if now - dev.last_seen > self._ttl_s
        ]
        for did in expired:
            del self._devices[did]
        return expired

    @property
    def device_count(self) -> int:
        return len(self._devices)

    def get_stats(self) -> dict:
        """Return decoder statistics."""
        return {
            "messages_received": self._messages_received,
            "devices_detected": self._devices_detected,
            "devices_active": len(self._devices),
            "messages_by_type": dict(self._messages_by_type),
            "signal_history_size": len(self._signal_history),
            "ttl_s": self._ttl_s,
        }
