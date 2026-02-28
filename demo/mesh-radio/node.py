# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mesh radio node state: position, battery, SNR, text messaging.

Simulates a Meshtastic or MeshCore LoRa mesh radio node.
Supports movement patterns: stationary, random_walk, waypoint.
"""

import math
import random
import time
from datetime import datetime, timezone
from enum import Enum


class MovementPattern(Enum):
    STATIONARY = "stationary"
    RANDOM_WALK = "random_walk"
    WAYPOINT = "waypoint"


# Battery curve: 4.2V full -> 3.0V empty (LiPo single cell)
_VOLTAGE_FULL = 4.2
_VOLTAGE_EMPTY = 3.0

# Battery drain rate: ~0.01% per minute (~16 hours of runtime)
_DRAIN_RATE_PER_SECOND = 0.0001 / 60.0

# Random walk speed in degrees per second (very slow GPS drift)
_WALK_SPEED_DEG_PER_S = 0.000005

# Waypoint approach speed in degrees per second
_WAYPOINT_SPEED_DEG_PER_S = 0.00001

# SNR baseline and jitter
_SNR_BASE = 5.0
_SNR_JITTER = 3.0

# RSSI baseline and jitter
_RSSI_BASE = -90
_RSSI_JITTER = 15


class MeshNode:
    """Simulated mesh radio node with position, battery, and SNR."""

    def __init__(
        self,
        node_id: str,
        long_name: str,
        short_name: str = "",
        protocol: str = "meshtastic",
        lat: float = 0.0,
        lng: float = 0.0,
        alt: float = 0.0,
        hardware: str = "heltec_v3",
        movement: str = "stationary",
        waypoints: list[tuple[float, float]] | None = None,
    ):
        self.node_id = node_id
        self.long_name = long_name
        self.protocol = protocol
        self.lat = lat
        self.lng = lng
        self.alt = alt
        self.hardware = hardware
        self.channel = 0
        self.hops = 0

        # Auto-generate short name from long name if not provided
        if short_name:
            self.short_name = short_name
        else:
            self.short_name = self._auto_short_name(long_name)

        # Movement pattern
        if isinstance(movement, MovementPattern):
            self.movement = movement
        else:
            self.movement = MovementPattern(movement)

        # Waypoints for waypoint pattern
        self._waypoints = waypoints or []
        self._waypoint_index = 0

        # Battery simulation
        self.battery = 1.0  # 0.0 to 1.0

        # Radio simulation
        self.snr = _SNR_BASE + random.uniform(-_SNR_JITTER, _SNR_JITTER)
        self.rssi = _RSSI_BASE + random.randint(-_RSSI_JITTER, _RSSI_JITTER)

        # Counters
        self.tx_count = 0
        self.rx_count = 0
        self.uptime_s = 0.0

    @staticmethod
    def _auto_short_name(long_name: str) -> str:
        """Generate a short name from the long name (first letters of words, or first two chars)."""
        words = long_name.split()
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words[:4])
        elif long_name:
            return long_name[:2].upper()
        return "??"

    @property
    def voltage(self) -> float:
        """Battery voltage: linear interpolation between 3.0V (empty) and 4.2V (full)."""
        return _VOLTAGE_EMPTY + self.battery * (_VOLTAGE_FULL - _VOLTAGE_EMPTY)

    def tick(self, dt: float) -> None:
        """Advance the node simulation by dt seconds.

        Updates battery, SNR/RSSI jitter, movement, and uptime.
        """
        # Uptime
        self.uptime_s += dt

        # Battery drain
        self.battery = max(0.0, self.battery - _DRAIN_RATE_PER_SECOND * dt)

        # SNR/RSSI jitter (random walk)
        self.snr += random.uniform(-0.5, 0.5) * (dt / 10.0)
        self.snr = max(-20.0, min(15.0, self.snr))
        self.rssi += random.randint(-1, 1)
        self.rssi = max(-140, min(-30, self.rssi))

        # Movement
        if self.movement == MovementPattern.RANDOM_WALK:
            self._tick_random_walk(dt)
        elif self.movement == MovementPattern.WAYPOINT:
            self._tick_waypoint(dt)
        # STATIONARY: no movement

    def _tick_random_walk(self, dt: float) -> None:
        """Random walk: small random GPS drift."""
        self.lat += random.uniform(-_WALK_SPEED_DEG_PER_S, _WALK_SPEED_DEG_PER_S) * dt
        self.lng += random.uniform(-_WALK_SPEED_DEG_PER_S, _WALK_SPEED_DEG_PER_S) * dt

    def _tick_waypoint(self, dt: float) -> None:
        """Move toward next waypoint, loop back to start when done."""
        if not self._waypoints:
            return

        target_lat, target_lng = self._waypoints[self._waypoint_index]
        dlat = target_lat - self.lat
        dlng = target_lng - self.lng
        dist = math.sqrt(dlat * dlat + dlng * dlng)

        if dist < _WAYPOINT_SPEED_DEG_PER_S * dt:
            # Arrived at waypoint
            self.lat = target_lat
            self.lng = target_lng
            self._waypoint_index = (self._waypoint_index + 1) % len(self._waypoints)
        else:
            # Move toward waypoint
            step = _WAYPOINT_SPEED_DEG_PER_S * dt
            self.lat += (dlat / dist) * step
            self.lng += (dlng / dist) * step

    def position_payload(self) -> dict:
        """Build the position payload matching DEMO-SPEC.md section 3.4."""
        return {
            "node_id": self.node_id,
            "long_name": self.long_name,
            "short_name": self.short_name,
            "protocol": self.protocol,
            "position": {
                "lat": self.lat,
                "lng": self.lng,
                "alt": self.alt,
            },
            "battery": round(self.battery, 4),
            "voltage": round(self.voltage, 2),
            "snr": round(self.snr, 1),
            "rssi": self.rssi,
            "hops": self.hops,
            "hardware": self.hardware,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def telemetry_payload(self) -> dict:
        """Build the telemetry payload with battery, voltage, SNR, counters."""
        return {
            "node_id": self.node_id,
            "battery": round(self.battery, 4),
            "voltage": round(self.voltage, 2),
            "snr": round(self.snr, 1),
            "rssi": self.rssi,
            "channel": self.channel,
            "uptime_s": round(self.uptime_s, 1),
            "tx_count": self.tx_count,
            "rx_count": self.rx_count,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def status_payload(self, status: str) -> dict:
        """Build a status payload for online/offline reporting."""
        return {
            "status": status,
            "node_id": self.node_id,
            "long_name": self.long_name,
            "protocol": self.protocol,
            "hardware": self.hardware,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def create_text_message(self, text: str, to: str = "^all") -> dict:
        """Create a text message payload and increment tx counter."""
        self.tx_count += 1
        return {
            "from": self.node_id,
            "to": to,
            "text": text,
            "channel": self.channel,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def set_channel(self, channel: int) -> None:
        """Set the active radio channel."""
        self.channel = channel

    def record_tx(self) -> None:
        """Increment the transmit counter."""
        self.tx_count += 1

    def record_rx(self) -> None:
        """Increment the receive counter."""
        self.rx_count += 1

    def reboot(self) -> None:
        """Simulate a node reboot: reset uptime and counters, preserve position."""
        self.uptime_s = 0.0
        self.tx_count = 0
        self.rx_count = 0
